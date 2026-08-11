"""Analysis tests against hand-written fixtures with known answers."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from ecolab.analyze import (
    ROLLING_WINDOW,
    date_range_label,
    rolling_mean,
    run_analysis,
    yoy_change,
)


def _monthly(values: list[float], start: str = "2020-01-01") -> pd.Series:
    index = pd.date_range(start, periods=len(values), freq="MS", name="period")
    return pd.Series(values, index=index, name="x")


def test_yoy_is_computed_correctly_on_a_hand_written_fixture() -> None:
    # 13 months. Month 13 is exactly 10% above month 1 -> YoY must be 10.0.
    values = [100.0] * 12 + [110.0]
    result = yoy_change(_monthly(values))

    # First 12 observations are NaN by construction.
    assert result.iloc[:12].isna().all()
    assert result.iloc[12] == pytest.approx(10.0)
    assert result.name == "x_yoy_pct"


def test_yoy_handles_a_decline_and_a_second_year() -> None:
    values = [200.0] * 12 + [150.0] + [300.0] * 11 + [225.0]
    result = yoy_change(_monthly(values))
    assert result.iloc[12] == pytest.approx(-25.0)  # 150 / 200 - 1
    assert result.iloc[24] == pytest.approx(50.0)  # 225 / 150 - 1


def test_yoy_does_not_fill_missing_inputs() -> None:
    values = [100.0] * 12 + [110.0]
    series = _monthly(values)
    series.iloc[0] = float("nan")
    result = yoy_change(series)
    assert math.isnan(result.iloc[12])


def test_rolling_mean_requires_a_full_window() -> None:
    result = rolling_mean(_monthly([1.0, 2.0, 3.0, 4.0]))
    assert result.iloc[0:2].isna().all()
    assert result.iloc[2] == pytest.approx(2.0)  # (1+2+3)/3
    assert result.iloc[3] == pytest.approx(3.0)  # (2+3+4)/3
    assert result.name == f"x_ma{ROLLING_WINDOW}"


def test_date_range_label() -> None:
    index = pd.date_range("2021-03-01", periods=4, freq="MS")
    assert date_range_label(index) == "2021-03..2021-06"
    assert date_range_label(pd.DatetimeIndex([])) == "n/a"


def test_correlation_uses_the_overlapping_period_only() -> None:
    index = pd.date_range("2020-01-01", periods=6, freq="MS", name="period")
    wide = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            # first two periods are missing -> overlap is 4 observations
            "b": [float("nan"), float("nan"), 3.0, 4.0, 5.0, 6.0],
        },
        index=index,
    )
    result = run_analysis(wide)
    assert result.correlation.n_obs == 4
    assert result.correlation.date_range == "2020-03..2020-06"
    assert result.correlation.matrix.loc["a", "b"] == pytest.approx(1.0)
    assert result.n_missing == {"a": 0, "b": 2}


def test_run_analysis_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="empty"):
        run_analysis(pd.DataFrame())
