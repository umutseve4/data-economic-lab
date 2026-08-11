"""Ingestion layer: fetch raw series, cache them, parse them into tidy frames.

Two sources are supported:

* ``evds``  -- TCMB EVDS REST API. Requires ``EVDS_API_KEY``.
* ``sample`` -- offline CSV files under ``data/sample/``. No network, no key.

Raw EVDS responses are cached verbatim under ``data/raw/`` so that a re-run
does not re-download. The cache key includes the series code and the date range.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from .config import Settings, SeriesSpec, require_api_key
from .errors import (
    AuthenticationError,
    EcolabError,
    EmptyResponseError,
    TransientNetworkError,
)

__all__ = [
    "COLUMNS",
    "cache_path",
    "fetch_series",
    "ingest_series",
    "load_sample",
    "parse_evds_payload",
]

logger = logging.getLogger(__name__)

#: Canonical tidy column order produced by this module.
COLUMNS: tuple[str, ...] = ("series_code", "period", "value")

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_AUTH_STATUS = frozenset({401, 403})


def _fmt_evds_date(value: date) -> str:
    """EVDS expects DD-MM-YYYY."""
    return value.strftime("%d-%m-%Y")


def cache_path(settings: Settings, spec: SeriesSpec, start: date, end: date) -> Path:
    """Deterministic cache location for one (series, range) pair."""
    safe_code = spec.code.replace(".", "_").replace("/", "_")
    return settings.raw_dir / f"{safe_code}__{start.isoformat()}__{end.isoformat()}.json"


def _request_once(
    url: str,
    params: Mapping[str, str],
    api_key: str,
    timeout: int,
    session: requests.Session | None,
) -> dict[str, Any]:
    """Perform a single HTTP GET and translate transport errors into typed errors."""
    client = session or requests
    try:
        response = client.get(url, params=dict(params), headers={"key": api_key}, timeout=timeout)
    except requests.Timeout as exc:
        raise TransientNetworkError(f"Request to EVDS timed out after {timeout}s") from exc
    except requests.RequestException as exc:
        raise TransientNetworkError(f"Network error talking to EVDS: {exc}") from exc

    status = response.status_code
    if status in _AUTH_STATUS:
        raise AuthenticationError(
            f"EVDS rejected the API key (HTTP {status}). "
            "Check EVDS_API_KEY; the value is not logged."
        )
    if status in _RETRYABLE_STATUS:
        raise TransientNetworkError(f"EVDS returned retryable status HTTP {status}")
    if status != 200:
        raise EcolabError(f"EVDS returned unexpected status HTTP {status}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise EcolabError("EVDS returned a body that is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise EcolabError(f"EVDS returned unexpected JSON type: {type(payload).__name__}")
    return payload


def fetch_series(
    spec: SeriesSpec,
    start: date,
    end: date,
    settings: Settings,
    *,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Fetch one series from EVDS, with caching and bounded exponential backoff.

    Raises:
        AuthenticationError: the API key was missing or rejected.
        EmptyResponseError: the API answered with zero observations.
        TransientNetworkError: all retries were exhausted.
    """
    target = cache_path(settings, spec, start, end)
    if use_cache and target.exists():
        logger.info("Cache hit for %s (%s)", spec.code, target)
        return json.loads(target.read_text(encoding="utf-8"))

    api_key = require_api_key()
    url = f"{settings.evds_base_url}/series={spec.code}"
    params = {
        "startDate": _fmt_evds_date(start),
        "endDate": _fmt_evds_date(end),
        "type": "json",
        "frequency": "5",  # 5 = monthly
        "aggregationTypes": spec.aggregation,
        "formulas": "0",  # 0 = level, no transformation
    }

    last_error: TransientNetworkError | None = None
    for attempt in range(1, settings.max_retries + 1):
        try:
            payload = _request_once(url, params, api_key, settings.http_timeout, session)
        except TransientNetworkError as exc:
            last_error = exc
            if attempt == settings.max_retries:
                break
            delay = settings.backoff_base * (2 ** (attempt - 1))
            logger.warning(
                "Attempt %d/%d for %s failed (%s); retrying in %.1fs",
                attempt,
                settings.max_retries,
                spec.code,
                exc,
                delay,
            )
            sleep(delay)
            continue

        items = payload.get("items")
        if not items:
            raise EmptyResponseError(
                f"EVDS returned no observations for {spec.code} between {start} and {end}"
            )
        settings.raw_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Fetched %d raw rows for %s -> %s", len(items), spec.code, target)
        return payload

    assert last_error is not None
    raise TransientNetworkError(
        f"Giving up on {spec.code} after {settings.max_retries} attempts: {last_error}"
    ) from last_error


def _normalise_period(raw: object) -> pd.Timestamp:
    """Parse EVDS period labels ('2019-1', '2019-01', '01-2019') to a month start."""
    text = str(raw).strip()
    for fmt in ("%Y-%m", "%m-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return pd.Timestamp(pd.to_datetime(text, format=fmt)).normalize().replace(day=1)
        except ValueError:
            continue
    raise EcolabError(f"Unparseable period label from source: {raw!r}")


def parse_evds_payload(payload: Mapping[str, Any], spec: SeriesSpec) -> pd.DataFrame:
    """Convert a raw EVDS payload into the tidy ``COLUMNS`` frame.

    Values that the API returns as ``None`` or empty strings become ``NaN``.
    They are reported by the validation layer and are never filled here.
    """
    items = payload.get("items")
    if not items:
        raise EmptyResponseError(f"No items in payload for {spec.code}")

    value_key = spec.code.replace(".", "_").replace("-", "_")
    records: list[dict[str, Any]] = []
    for item in items:
        if "Tarih" not in item:
            raise EcolabError(f"Payload row is missing the 'Tarih' field: {item!r}")
        if value_key not in item:
            candidates = [k for k in item if k not in {"Tarih", "UNIXTIME"}]
            if len(candidates) != 1:
                raise EcolabError(
                    f"Cannot locate value column for {spec.code}; candidates={candidates}"
                )
            value_key = candidates[0]
        raw_value = item[value_key]
        records.append(
            {
                "series_code": spec.code,
                "period": _normalise_period(item["Tarih"]),
                "value": pd.to_numeric(raw_value, errors="coerce")
                if raw_value not in (None, "")
                else float("nan"),
            }
        )

    frame = pd.DataFrame.from_records(records, columns=list(COLUMNS))
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    return frame


def load_sample(spec: SeriesSpec, settings: Settings) -> pd.DataFrame:
    """Load the offline sample CSV for a series (used by tests and CI)."""
    path = settings.sample_dir / spec.sample_filename
    if not path.exists():
        raise EcolabError(f"Sample file not found: {path}")
    raw = pd.read_csv(path, comment="#")
    missing = {"period", "value"} - set(raw.columns)
    if missing:
        raise EcolabError(f"Sample file {path} is missing columns: {sorted(missing)}")
    frame = pd.DataFrame(
        {
            "series_code": spec.code,
            "period": [_normalise_period(p) for p in raw["period"]],
            "value": pd.to_numeric(raw["value"], errors="coerce"),
        },
        columns=list(COLUMNS),
    )
    logger.info("Loaded %d sample rows for %s from %s", len(frame), spec.code, path)
    return frame


def ingest_series(
    spec: SeriesSpec,
    settings: Settings,
    *,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> pd.DataFrame:
    """Return a tidy frame for one series from the configured source."""
    if settings.source == "sample":
        frame = load_sample(spec, settings)
    else:
        payload = fetch_series(
            spec, settings.start, settings.end, settings, session=session, sleep=sleep
        )
        frame = parse_evds_payload(payload, spec)

    mask = (frame["period"] >= pd.Timestamp(settings.start)) & (
        frame["period"] <= pd.Timestamp(settings.end)
    )
    return frame.loc[mask].sort_values("period").reset_index(drop=True)
