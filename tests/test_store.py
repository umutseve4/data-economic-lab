"""Storage tests, including the idempotency guarantee."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd

from ecolab.store import connect, count_rows, init_db, read_series, read_wide, upsert_observations

Factory = Callable[..., pd.DataFrame]


def test_init_db_creates_the_expected_schema(tmp_path: Path) -> None:
    db = tmp_path / "economic.db"
    init_db(db)
    with connect(db) as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(observations)")]
    assert cols == ["series_code", "period", "value", "unit", "source", "ingested_at"]


def test_ingestion_is_idempotent(tmp_path: Path, frame_factory: Factory) -> None:
    db = tmp_path / "economic.db"
    frame = frame_factory(
        ["2020-01-01", "2020-02-01", "2020-03-01"], [1.0, 2.0, 3.0], code="TP.TEST"
    )

    first = upsert_observations(db, frame, unit="index", source="sample")
    after_first = count_rows(db)

    second = upsert_observations(db, frame, unit="index", source="sample")
    after_second = count_rows(db)

    assert first == second == 3
    assert after_first == after_second == 3


def test_upsert_updates_the_value_in_place(tmp_path: Path, frame_factory: Factory) -> None:
    db = tmp_path / "economic.db"
    upsert_observations(
        db, frame_factory(["2020-01-01"], [1.0], code="TP.TEST"), unit="index", source="sample"
    )
    upsert_observations(
        db, frame_factory(["2020-01-01"], [9.0], code="TP.TEST"), unit="index", source="sample"
    )
    stored = read_series(db, "TP.TEST")
    assert len(stored) == 1
    assert stored.loc[0, "value"] == 9.0


def test_missing_values_round_trip_as_null(tmp_path: Path, frame_factory: Factory) -> None:
    db = tmp_path / "economic.db"
    frame = frame_factory(["2020-01-01", "2020-02-01"], [1.0, float("nan")], code="TP.TEST")
    upsert_observations(db, frame, unit="index", source="sample")
    stored = read_series(db, "TP.TEST")
    assert pd.isna(stored.loc[1, "value"])


def test_read_wide_joins_series_on_period(tmp_path: Path, frame_factory: Factory) -> None:
    db = tmp_path / "economic.db"
    upsert_observations(
        db,
        frame_factory(["2020-01-01", "2020-02-01"], [1.0, 2.0], code="TP.A"),
        unit="index",
        source="sample",
    )
    upsert_observations(
        db,
        frame_factory(["2020-02-01", "2020-03-01"], [20.0, 30.0], code="TP.B"),
        unit="index",
        source="sample",
    )
    wide = read_wide(db, {"a": "TP.A", "b": "TP.B"})
    assert list(wide.columns) == ["a", "b"]
    assert len(wide) == 3
    assert wide.loc[pd.Timestamp("2020-02-01"), "a"] == 2.0
    assert wide.loc[pd.Timestamp("2020-02-01"), "b"] == 20.0
    assert pd.isna(wide.loc[pd.Timestamp("2020-03-01"), "a"])


def test_count_rows_can_filter_by_series(tmp_path: Path, frame_factory: Factory) -> None:
    db = tmp_path / "economic.db"
    upsert_observations(
        db, frame_factory(["2020-01-01"], [1.0], code="TP.A"), unit="index", source="sample"
    )
    upsert_observations(
        db,
        frame_factory(["2020-01-01", "2020-02-01"], [1.0, 2.0], code="TP.B"),
        unit="index",
        source="sample",
    )
    assert count_rows(db) == 3
    assert count_rows(db, "TP.A") == 1
    assert count_rows(db, "TP.B") == 2
