"""Configuration and the series registry.

All configuration comes from environment variables with documented defaults.
No secret is ever stored in code; ``EVDS_API_KEY`` is read lazily and is never
logged or written to disk.
"""

from __future__ import annotations

import dataclasses
import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .errors import ConfigError

__all__ = [
    "DEFAULT_SERIES",
    "Settings",
    "SeriesSpec",
    "configure_logging",
    "get_series_specs",
    "load_settings",
    "require_api_key",
]

logger = logging.getLogger(__name__)

#: Canonical names used everywhere in the pipeline (DB, reports, tests).
CPI = "cpi"
USDTRY = "usdtry"
POLICY_RATE = "policy_rate"


@dataclass(frozen=True)
class SeriesSpec:
    """Static metadata describing one time series."""

    name: str
    code: str
    unit: str
    label: str
    aggregation: str  # EVDS monthly aggregation: "avg" or "last"
    source: str = "TCMB EVDS"

    @property
    def sample_filename(self) -> str:
        """Filename of the offline sample CSV for this series."""
        return f"{self.name}.csv"


#: Default EVDS series codes. Override per series with ECOLAB_SERIES_<NAME>.
DEFAULT_SERIES: dict[str, SeriesSpec] = {
    CPI: SeriesSpec(
        name=CPI,
        code="TP.FG.J0",
        unit="index (2003=100)",
        label="Consumer Price Index",
        aggregation="last",
    ),
    USDTRY: SeriesSpec(
        name=USDTRY,
        code="TP.DK.USD.A.YTL",
        unit="TRY per USD",
        label="USD/TRY exchange rate (monthly average)",
        aggregation="avg",
    ),
    POLICY_RATE: SeriesSpec(
        name=POLICY_RATE,
        code="TP.APIFON4",
        unit="percent per annum",
        label="CBRT policy / funding rate",
        aggregation="avg",
    ),
}


def _env_str(key: str, default: str) -> str:
    value = os.environ.get(key, "").strip()
    return value or default


def _env_int(key: str, default: int) -> int:
    raw = _env_str(key, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


def _env_float(key: str, default: float) -> float:
    raw = _env_str(key, str(default))
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number, got {raw!r}") from exc


def _env_date(key: str, default: str) -> date:
    raw = _env_str(key, default)
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an ISO date (YYYY-MM-DD), got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    """Resolved runtime configuration."""

    data_dir: Path
    raw_dir: Path
    sample_dir: Path
    db_path: Path
    report_dir: Path
    start: date
    end: date
    source: str
    log_level: str
    http_timeout: int
    max_retries: int
    backoff_base: float
    evds_base_url: str

    def ensure_dirs(self) -> None:
        """Create the directories the pipeline writes to."""
        for directory in (self.raw_dir, self.db_path.parent, self.report_dir):
            directory.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """Build :class:`Settings` from environment variables and defaults."""
    data_dir = Path(_env_str("ECOLAB_DATA_DIR", "data"))
    source = _env_str("ECOLAB_SOURCE", "sample").lower()
    if source not in {"sample", "evds"}:
        raise ConfigError(f"ECOLAB_SOURCE must be 'sample' or 'evds', got {source!r}")

    settings = Settings(
        data_dir=data_dir,
        raw_dir=data_dir / "raw",
        sample_dir=data_dir / "sample",
        db_path=Path(_env_str("ECOLAB_DB_PATH", str(data_dir / "economic.db"))),
        report_dir=Path(_env_str("ECOLAB_REPORT_DIR", "reports")),
        start=_env_date("ECOLAB_START", "2019-01-01"),
        end=_env_date("ECOLAB_END", "2024-12-01"),
        source=source,
        log_level=_env_str("ECOLAB_LOG_LEVEL", "INFO").upper(),
        http_timeout=_env_int("ECOLAB_HTTP_TIMEOUT", 30),
        max_retries=_env_int("ECOLAB_MAX_RETRIES", 3),
        backoff_base=_env_float("ECOLAB_BACKOFF_BASE", 1.0),
        evds_base_url=_env_str("ECOLAB_EVDS_BASE_URL", "https://evds2.tcmb.gov.tr/service/evds"),
    )
    if settings.start > settings.end:
        raise ConfigError(f"ECOLAB_START ({settings.start}) is after ECOLAB_END ({settings.end})")
    return settings


def get_series_specs() -> dict[str, SeriesSpec]:
    """Return the series registry with per-series code overrides applied."""
    specs: dict[str, SeriesSpec] = {}
    for name, spec in DEFAULT_SERIES.items():
        override = _env_str(f"ECOLAB_SERIES_{name.upper()}", spec.code)
        if override == spec.code:
            specs[name] = spec
        else:
            specs[name] = dataclasses.replace(spec, code=override)
    return specs


def require_api_key() -> str:
    """Return the EVDS API key or raise :class:`ConfigError`.

    The value is never logged. Only its presence is reported.
    """
    key = os.environ.get("EVDS_API_KEY", "").strip()
    if not key:
        raise ConfigError(
            "EVDS_API_KEY is not set. Export it (see .env.example) or run with --source sample."
        )
    logger.debug("EVDS_API_KEY found (length=%d, value redacted)", len(key))
    return key


def configure_logging(level: str) -> None:
    """Configure stdlib logging for the whole application."""
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        force=True,
    )
