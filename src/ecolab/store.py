"""SQLite storage layer.

Schema::

    observations(
        series_code TEXT NOT NULL,
        period      DATE NOT NULL,
        value       REAL,
        unit        TEXT NOT NULL,
        source      TEXT NOT NULL,
        ingested_at TIMESTAMP NOT NULL,
        PRIMARY KEY (series_code, period)
    )

Writes use ``INSERT ... ON CONFLICT DO UPDATE`` so that re-running ingestion is
idempotent: the row count never changes for the same input.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

__all__ = [
    "SCHEMA_SQL",
    "connect",
    "count_rows",
    "init_db",
    "read_series",
    "read_wide",
    "upsert_observations",
]

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS observations (
    series_code TEXT      NOT NULL,
    period      DATE      NOT NULL,
    value       REAL,
    unit        TEXT      NOT NULL,
    source      TEXT      NOT NULL,
    ingested_at TIMESTAMP NOT NULL,
    PRIMARY KEY (series_code, period)
);
CREATE INDEX IF NOT EXISTS idx_observations_period ON observations(period);
"""


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection with foreign keys on, committing on success."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    """Create the schema if it does not exist."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
    logger.info("Initialised database at %s", db_path)


def upsert_observations(
    db_path: Path,
    frame: pd.DataFrame,
    *,
    unit: str,
    source: str,
    ingested_at: datetime | None = None,
) -> int:
    """Insert or update the observations of one series. Returns rows written."""
    init_db(db_path)
    stamp = (ingested_at or datetime.now(UTC)).isoformat(timespec="seconds")
    rows = [
        (
            str(record.series_code),
            pd.Timestamp(record.period).date().isoformat(),
            None if pd.isna(record.value) else float(record.value),
            unit,
            source,
            stamp,
        )
        for record in frame.itertuples(index=False)
    ]
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO observations (series_code, period, value, unit, source, ingested_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(series_code, period) DO UPDATE SET
                value       = excluded.value,
                unit        = excluded.unit,
                source      = excluded.source,
                ingested_at = excluded.ingested_at
            """,
            rows,
        )
    logger.info("Upserted %d rows into %s", len(rows), db_path)
    return len(rows)


def count_rows(db_path: Path, series_code: str | None = None) -> int:
    """Count stored observations, optionally for a single series."""
    with connect(db_path) as conn:
        if series_code is None:
            cursor = conn.execute("SELECT COUNT(*) FROM observations")
        else:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM observations WHERE series_code = ?", (series_code,)
            )
        return int(cursor.fetchone()[0])


def read_series(db_path: Path, series_code: str) -> pd.DataFrame:
    """Read one series back as a tidy frame ordered by period."""
    with connect(db_path) as conn:
        frame = pd.read_sql_query(
            "SELECT series_code, period, value, unit, source, ingested_at "
            "FROM observations WHERE series_code = ? ORDER BY period",
            conn,
            params=(series_code,),
        )
    frame["period"] = pd.to_datetime(frame["period"])
    return frame


def read_wide(db_path: Path, codes: dict[str, str]) -> pd.DataFrame:
    """Return a wide frame indexed by period with one column per logical name.

    Args:
        codes: mapping of logical name -> series_code.
    """
    columns: dict[str, pd.Series] = {}
    for name, code in codes.items():
        series = read_series(db_path, code)
        columns[name] = series.set_index("period")["value"].rename(name)
    if not columns:
        return pd.DataFrame()
    wide = pd.concat(columns.values(), axis=1).sort_index()
    wide.index.name = "period"
    return wide
