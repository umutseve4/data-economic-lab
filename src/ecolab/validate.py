"""Validation rules.

Every rule is a small pure function returning a list of human readable problems.
``validate_series`` aggregates them and raises :class:`DataValidationError` when
anything is wrong, so the CLI can exit non-zero with a readable message.

Missing values are *reported*, never filled.
"""

from __future__ import annotations

import logging

import pandas as pd

from .errors import DataValidationError
from .ingest import COLUMNS

__all__ = [
    "ValidationReport",
    "check_duplicates",
    "check_gaps",
    "check_monotonic",
    "check_parseable",
    "check_schema",
    "missing_periods",
    "validate_series",
]

logger = logging.getLogger(__name__)


class ValidationReport:
    """Outcome of validating one series."""

    def __init__(
        self,
        series_code: str,
        n_rows: int,
        n_missing: int,
        missing: list[str],
        date_range: str = "n/a",
    ) -> None:
        self.series_code = series_code
        self.n_rows = n_rows
        self.n_missing = n_missing
        self.missing = missing
        self.date_range = date_range

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"ValidationReport(series_code={self.series_code!r}, n_rows={self.n_rows}, "
            f"n_missing={self.n_missing})"
        )


def check_schema(frame: pd.DataFrame) -> list[str]:
    """Rule 1: the frame must expose exactly the expected columns."""
    actual = list(frame.columns)
    if actual != list(COLUMNS):
        return [f"schema mismatch: expected columns {list(COLUMNS)}, got {actual}"]
    return []


def check_parseable(frame: pd.DataFrame) -> list[str]:
    """Rule 2: periods must be datetimes and values must be numeric."""
    problems: list[str] = []
    if not pd.api.types.is_datetime64_any_dtype(frame["period"]):
        problems.append(f"unparseable period column: dtype is {frame['period'].dtype}")
    if not pd.api.types.is_numeric_dtype(frame["value"]):
        problems.append(f"unparseable value column: dtype is {frame['value'].dtype}")
    return problems


def check_duplicates(frame: pd.DataFrame) -> list[str]:
    """Rule 3: no duplicated periods."""
    duplicated = frame["period"][frame["period"].duplicated()]
    if len(duplicated) == 0:
        return []
    shown = ", ".join(str(pd.Timestamp(d).date()) for d in duplicated.unique()[:5])
    return [f"duplicated periods ({len(duplicated)}): {shown}"]


def check_monotonic(frame: pd.DataFrame) -> list[str]:
    """Rule 4: the date index must be strictly increasing."""
    periods = frame["period"]
    if periods.is_monotonic_increasing and not periods.duplicated().any():
        return []
    if periods.is_monotonic_increasing:
        return []  # duplicates are reported by check_duplicates
    return ["non-monotonic date index: periods are not sorted in increasing order"]


def missing_periods(frame: pd.DataFrame) -> list[pd.Timestamp]:
    """Return the month starts that are absent between the first and last period."""
    if frame.empty:
        return []
    expected = pd.date_range(frame["period"].min(), frame["period"].max(), freq="MS")
    present = set(pd.DatetimeIndex(frame["period"]))
    return [ts for ts in expected if ts not in present]


def check_gaps(frame: pd.DataFrame) -> list[str]:
    """Rule 5: no gap larger than one period (one month) in the date index."""
    if len(frame) < 2:
        return []
    gaps = missing_periods(frame)
    if not gaps:
        return []
    shown = ", ".join(str(ts.date()) for ts in gaps[:5])
    return [f"gap larger than one period: {len(gaps)} month(s) missing from the index ({shown})"]


def validate_series(frame: pd.DataFrame, series_code: str) -> ValidationReport:
    """Run every rule. Raise :class:`DataValidationError` if any rule fails."""
    problems = check_schema(frame)
    if problems:
        raise DataValidationError(series_code, problems)

    if frame.empty:
        raise DataValidationError(series_code, ["empty result set: zero observations"])

    problems += check_parseable(frame)
    if problems:
        raise DataValidationError(series_code, problems)

    problems += check_duplicates(frame)
    problems += check_monotonic(frame)
    problems += check_gaps(frame)
    if problems:
        raise DataValidationError(series_code, problems)

    missing_mask = frame["value"].isna()
    missing_labels = [str(pd.Timestamp(p).date()) for p in frame.loc[missing_mask, "period"]]
    if missing_labels:
        logger.warning(
            "%s: %d missing value(s) reported and NOT filled: %s",
            series_code,
            len(missing_labels),
            ", ".join(missing_labels[:12]),
        )
    else:
        logger.info("%s: %d rows validated, no missing values", series_code, len(frame))

    first = pd.Timestamp(frame["period"].min())
    last = pd.Timestamp(frame["period"].max())
    return ValidationReport(
        series_code=series_code,
        n_rows=len(frame),
        n_missing=len(missing_labels),
        missing=missing_labels,
        date_range=f"{first:%Y-%m}..{last:%Y-%m}",
    )
