"""Shared fixtures. Everything here is offline and deterministic."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from ecolab.config import Settings
from ecolab.ingest import COLUMNS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = PROJECT_ROOT / "data" / "sample"


@pytest.fixture
def sample_dir() -> Path:
    """Path to the committed synthetic sample data."""
    return SAMPLE_DIR


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Offline settings pointing at the committed sample data and a temp DB."""
    return Settings(
        source="sample",
        data_dir=tmp_path / "data",
        raw_dir=tmp_path / "data" / "raw",
        sample_dir=SAMPLE_DIR,
        db_path=tmp_path / "data" / "economic.db",
        report_dir=tmp_path / "reports",
        start=date(2019, 1, 1),
        end=date(2024, 12, 1),
        log_level="WARNING",
        http_timeout=5,
        max_retries=3,
        backoff_base=0.0,
        evds_base_url="https://evds2.tcmb.gov.tr/service/evds",
    )


def make_frame(periods: list[str], values: list[float], code: str = "TEST.CODE") -> pd.DataFrame:
    """Build a tidy frame from hand-written month labels and values."""
    return pd.DataFrame(
        {
            "series_code": code,
            "period": pd.to_datetime(periods),
            "value": values,
        },
        columns=list(COLUMNS),
    )


@pytest.fixture
def frame_factory() -> Callable[..., pd.DataFrame]:
    """Expose :func:`make_frame` as a fixture so tests need no cross-module import."""
    return make_frame


@pytest.fixture
def good_frame() -> pd.DataFrame:
    """A small, valid, gap-free monthly frame."""
    periods = ["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"]
    return make_frame(periods, [100.0, 101.0, 102.5, 103.0])
