"""One test per validation failure mode, plus the happy path."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pytest

from ecolab.errors import DataValidationError
from ecolab.validate import (
    check_duplicates,
    check_gaps,
    check_monotonic,
    check_parseable,
    check_schema,
    missing_periods,
    validate_series,
)

Factory = Callable[..., pd.DataFrame]


def test_happy_path_returns_report(good_frame: pd.DataFrame) -> None:
    report = validate_series(good_frame, "TEST.CODE")
    assert report.n_rows == 4
    assert report.n_missing == 0
    assert report.date_range == "2020-01..2020-04"


def test_schema_mismatch_is_detected(good_frame: pd.DataFrame) -> None:
    broken = good_frame.rename(columns={"value": "val"})
    assert check_schema(broken)
    with pytest.raises(DataValidationError, match="schema mismatch"):
        validate_series(broken, "TEST.CODE")


def test_unparseable_values_are_detected(good_frame: pd.DataFrame) -> None:
    broken = good_frame.copy()
    broken["value"] = ["a", "b", "c", "d"]
    assert check_parseable(broken)
    with pytest.raises(DataValidationError, match="unparseable"):
        validate_series(broken, "TEST.CODE")


def test_duplicate_periods_are_detected(frame_factory: Factory) -> None:
    frame = frame_factory(
        ["2020-01-01", "2020-02-01", "2020-02-01", "2020-03-01"], [1.0, 2.0, 2.0, 3.0]
    )
    assert check_duplicates(frame)
    with pytest.raises(DataValidationError, match="duplicated"):
        validate_series(frame, "TEST.CODE")


def test_non_monotonic_index_is_detected(frame_factory: Factory) -> None:
    frame = frame_factory(["2020-03-01", "2020-01-01", "2020-02-01"], [3.0, 1.0, 2.0])
    assert check_monotonic(frame)
    with pytest.raises(DataValidationError, match="monotonic"):
        validate_series(frame, "TEST.CODE")


def test_gap_larger_than_one_period_is_detected(frame_factory: Factory) -> None:
    frame = frame_factory(["2020-01-01", "2020-02-01", "2020-05-01"], [1.0, 2.0, 5.0])
    problems = check_gaps(frame)
    assert problems
    with pytest.raises(DataValidationError, match="gap"):
        validate_series(frame, "TEST.CODE")


def test_missing_periods_lists_absent_months(frame_factory: Factory) -> None:
    frame = frame_factory(["2020-01-01", "2020-04-01"], [1.0, 4.0])
    gaps = missing_periods(frame)
    assert [str(pd.Timestamp(ts).date()) for ts in gaps] == ["2020-02-01", "2020-03-01"]


def test_empty_frame_is_rejected(good_frame: pd.DataFrame) -> None:
    with pytest.raises(DataValidationError, match="empty"):
        validate_series(good_frame.iloc[0:0], "TEST.CODE")


def test_missing_values_are_reported_not_filled(frame_factory: Factory) -> None:
    frame = frame_factory(["2020-01-01", "2020-02-01", "2020-03-01"], [1.0, float("nan"), 3.0])
    report = validate_series(frame, "TEST.CODE")
    assert report.n_missing == 1
    # nothing was filled in: the value is still NaN in the caller's frame
    assert pd.isna(frame.loc[1, "value"])


def test_single_row_has_no_gaps(frame_factory: Factory) -> None:
    frame = frame_factory(["2020-01-01"], [1.0])
    assert check_gaps(frame) == []
