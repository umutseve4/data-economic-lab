"""Ingestion tests. Every network interaction is faked; no socket is opened."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import requests

from ecolab.config import DEFAULT_SERIES, Settings
from ecolab.errors import (
    AuthenticationError,
    ConfigError,
    EcolabError,
    EmptyResponseError,
    TransientNetworkError,
)
from ecolab.ingest import (
    COLUMNS,
    cache_path,
    fetch_series,
    ingest_series,
    load_sample,
    parse_evds_payload,
)

SPEC = DEFAULT_SERIES["cpi"]
START = date(2020, 1, 1)
END = date(2020, 3, 1)


class FakeResponse:
    """Minimal stand-in for :class:`requests.Response`."""

    def __init__(self, status_code: int, payload: Any = None, *, bad_json: bool = False) -> None:
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self) -> Any:
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Replays a scripted list of responses or exceptions, counting calls."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls = 0

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls += 1
        item = self.script.pop(0) if self.script else self.script
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, FakeResponse)
        return item


def _payload(rows: list[tuple[str, Any]]) -> dict[str, Any]:
    key = SPEC.code.replace(".", "_")
    return {"items": [{"Tarih": period, key: value} for period, value in rows]}


# --------------------------------------------------------------------------
# sample loading
# --------------------------------------------------------------------------


def test_load_sample_returns_the_tidy_schema(settings: Settings) -> None:
    frame = load_sample(SPEC, settings)
    assert list(frame.columns) == list(COLUMNS)
    assert len(frame) == 72
    assert frame["series_code"].unique().tolist() == [SPEC.code]
    assert pd.api.types.is_datetime64_any_dtype(frame["period"])


def test_load_sample_raises_when_the_file_is_absent(settings: Settings, tmp_path: Path) -> None:
    import dataclasses

    broken = dataclasses.replace(settings, sample_dir=tmp_path / "nope")
    with pytest.raises(EcolabError, match="Sample file not found"):
        load_sample(SPEC, broken)


def test_ingest_series_clips_to_the_configured_range(settings: Settings) -> None:
    import dataclasses

    narrow = dataclasses.replace(settings, start=date(2020, 1, 1), end=date(2020, 6, 1))
    frame = ingest_series(SPEC, narrow)
    assert len(frame) == 6
    assert frame["period"].min() == pd.Timestamp("2020-01-01")
    assert frame["period"].max() == pd.Timestamp("2020-06-01")
    assert frame["period"].is_monotonic_increasing


# --------------------------------------------------------------------------
# payload parsing
# --------------------------------------------------------------------------


def test_parse_evds_payload_builds_the_tidy_frame() -> None:
    frame = parse_evds_payload(_payload([("2020-1", "100.5"), ("2020-2", "101.0")]), SPEC)
    assert list(frame.columns) == list(COLUMNS)
    assert frame["period"].tolist() == [pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01")]
    assert frame["value"].tolist() == [100.5, 101.0]


def test_parse_evds_payload_keeps_missing_values_as_nan() -> None:
    frame = parse_evds_payload(_payload([("2020-1", None), ("2020-2", "")]), SPEC)
    assert frame["value"].isna().all()


def test_parse_evds_payload_rejects_an_empty_payload() -> None:
    with pytest.raises(EmptyResponseError):
        parse_evds_payload({"items": []}, SPEC)


def test_parse_evds_payload_rejects_a_row_without_a_date() -> None:
    with pytest.raises(EcolabError, match="Tarih"):
        parse_evds_payload({"items": [{"TP_FG_J0": "1"}]}, SPEC)


# --------------------------------------------------------------------------
# fetching: cache, auth, retry, empty
# --------------------------------------------------------------------------


def test_fetch_series_uses_the_cache_and_performs_no_request(settings: Settings) -> None:
    target = cache_path(settings, SPEC, START, END)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _payload([("2020-1", "100.0")])
    target.write_text(json.dumps(payload), encoding="utf-8")

    session = FakeSession([])
    result = fetch_series(SPEC, START, END, settings, session=session)  # type: ignore[arg-type]

    assert result == payload
    assert session.calls == 0


def test_fetch_series_requires_an_api_key(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EVDS_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="EVDS_API_KEY"):
        fetch_series(SPEC, START, END, settings, session=FakeSession([]))  # type: ignore[arg-type]


def test_fetch_series_raises_authentication_error_on_401(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVDS_API_KEY", "dummy-key-for-tests")
    session = FakeSession([FakeResponse(401)])
    with pytest.raises(AuthenticationError, match="rejected the API key"):
        fetch_series(SPEC, START, END, settings, session=session)  # type: ignore[arg-type]
    assert session.calls == 1  # auth failures are not retried


def test_fetch_series_retries_transient_failures_then_succeeds(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVDS_API_KEY", "dummy-key-for-tests")
    delays: list[float] = []
    session = FakeSession(
        [
            FakeResponse(503),
            requests.Timeout("slow"),
            FakeResponse(200, _payload([("2020-1", "100.0")])),
        ]
    )
    payload = fetch_series(
        SPEC,
        START,
        END,
        settings,
        session=session,  # type: ignore[arg-type]
        sleep=delays.append,
    )
    assert session.calls == 3
    assert len(delays) == 2
    assert payload["items"][0]["TP_FG_J0"] == "100.0"
    # the successful response was cached
    assert cache_path(settings, SPEC, START, END).exists()


def test_fetch_series_gives_up_after_max_retries(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVDS_API_KEY", "dummy-key-for-tests")
    session = FakeSession([FakeResponse(503) for _ in range(settings.max_retries)])
    with pytest.raises(TransientNetworkError, match="Giving up"):
        fetch_series(
            SPEC,
            START,
            END,
            settings,  # type: ignore[arg-type]
            session=session,  # type: ignore[arg-type]
            sleep=lambda _: None,
        )
    assert session.calls == settings.max_retries


def test_fetch_series_raises_on_an_empty_response(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVDS_API_KEY", "dummy-key-for-tests")
    session = FakeSession([FakeResponse(200, {"items": []})])
    with pytest.raises(EmptyResponseError, match="no observations"):
        fetch_series(SPEC, START, END, settings, session=session)  # type: ignore[arg-type]


def test_fetch_series_rejects_non_json_bodies(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EVDS_API_KEY", "dummy-key-for-tests")
    session = FakeSession([FakeResponse(200, bad_json=True)])
    with pytest.raises(EcolabError, match="not valid JSON"):
        fetch_series(SPEC, START, END, settings, session=session)  # type: ignore[arg-type]


def test_cache_path_is_deterministic_and_range_specific(settings: Settings) -> None:
    a = cache_path(settings, SPEC, START, END)
    b = cache_path(settings, SPEC, START, END)
    c = cache_path(settings, SPEC, START, date(2021, 1, 1))
    assert a == b
    assert a != c
    assert "." not in a.stem
