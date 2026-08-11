"""Analysis layer: year-over-year change, rolling mean, correlation.

Every computation reports the exact date range it was computed on. Nothing is
imputed; periods with missing inputs simply produce missing outputs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd

__all__ = [
    "AnalysisResult",
    "CorrelationResult",
    "date_range_label",
    "run_analysis",
    "rolling_mean",
    "yoy_change",
]

logger = logging.getLogger(__name__)

#: Number of periods in one year for a monthly series.
MONTHS_PER_YEAR = 12

#: Window length of the rolling mean, in months.
ROLLING_WINDOW = 3


def date_range_label(index: pd.Index) -> str:
    """Human readable ``YYYY-MM..YYYY-MM`` label for a period index."""
    clean = pd.DatetimeIndex(pd.Index(index)).sort_values()
    if len(clean) == 0:
        return "n/a"
    return f"{clean[0]:%Y-%m}..{clean[-1]:%Y-%m}"


def yoy_change(series: pd.Series, periods: int = MONTHS_PER_YEAR) -> pd.Series:
    """Year-over-year percentage change: ``(v_t / v_{t-12} - 1) * 100``.

    The first ``periods`` observations are ``NaN`` by construction. No filling
    is performed, so a missing input yields a missing output.
    """
    shifted = series.shift(periods)
    result = (series / shifted - 1.0) * 100.0
    return result.rename(f"{series.name}_yoy_pct")


def rolling_mean(series: pd.Series, window: int = ROLLING_WINDOW) -> pd.Series:
    """Rolling mean over ``window`` periods, requiring a full window."""
    return (
        series.rolling(window=window, min_periods=window).mean().rename(f"{series.name}_ma{window}")
    )


@dataclass(frozen=True)
class CorrelationResult:
    """Pearson correlation computed on the overlapping, complete-case period."""

    matrix: pd.DataFrame
    n_obs: int
    date_range: str
    columns: list[str]


@dataclass
class AnalysisResult:
    """Everything the analyze stage produces."""

    levels: pd.DataFrame
    yoy: pd.DataFrame
    rolling: pd.DataFrame
    correlation: CorrelationResult
    coverage: dict[str, str] = field(default_factory=dict)
    n_missing: dict[str, int] = field(default_factory=dict)


def _correlation(wide: pd.DataFrame) -> CorrelationResult:
    overlap = wide.dropna(how="any")
    matrix = overlap.corr(method="pearson") if len(overlap) >= 2 else pd.DataFrame()
    return CorrelationResult(
        matrix=matrix,
        n_obs=len(overlap),
        date_range=date_range_label(overlap.index),
        columns=list(wide.columns),
    )


def run_analysis(wide: pd.DataFrame) -> AnalysisResult:
    """Compute YoY, rolling mean and the correlation table for a wide frame."""
    if wide.empty:
        raise ValueError("analysis input is empty; run 'ingest' first")

    wide = wide.sort_index()
    yoy = pd.DataFrame({col: yoy_change(wide[col]) for col in wide.columns})
    roll = pd.DataFrame({col: rolling_mean(wide[col]) for col in wide.columns})
    correlation = _correlation(wide)

    coverage = {col: date_range_label(wide[col].dropna().index) for col in wide.columns}
    n_missing = {col: int(wide[col].isna().sum()) for col in wide.columns}

    for col in wide.columns:
        logger.info(
            "%s: %d observations over %s (%d missing)",
            col,
            int(wide[col].notna().sum()),
            coverage[col],
            n_missing[col],
        )
    logger.info(
        "Correlation computed on %d complete-case observations over %s",
        correlation.n_obs,
        correlation.date_range,
    )

    return AnalysisResult(
        levels=wide,
        yoy=yoy,
        rolling=roll,
        correlation=correlation,
        coverage=coverage,
        n_missing=n_missing,
    )
