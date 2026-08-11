"""Command line interface: ``python -m ecolab <command>``.

This is the only module allowed to call :func:`print`. Every failure path exits
with a non-zero status code and a readable message.

Exit codes
----------
0  success
1  unexpected error
2  configuration error (bad env var, missing API key)
3  validation failure
4  ingestion failure (auth, empty response, network exhausted)
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from collections.abc import Sequence

import pandas as pd

from .analyze import AnalysisResult, run_analysis
from .config import SeriesSpec, Settings, configure_logging, get_series_specs, load_settings
from .errors import (
    AuthenticationError,
    ConfigError,
    DataValidationError,
    EcolabError,
    EmptyResponseError,
    TransientNetworkError,
)
from .ingest import ingest_series
from .report import write_report
from .store import count_rows, read_wide, upsert_observations
from .validate import ValidationReport, validate_series

__all__ = ["build_parser", "main"]

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG = 2
EXIT_VALIDATION = 3
EXIT_INGEST = 4


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the four subcommands."""
    parser = argparse.ArgumentParser(
        prog="ecolab",
        description="Reproducible ingest/validate/store/analyze/report pipeline "
        "for Turkish macroeconomic time series.",
    )
    parser.add_argument(
        "--source",
        choices=("sample", "evds"),
        default=None,
        help="Override ECOLAB_SOURCE for this run.",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="Override ECOLAB_LOG_LEVEL (DEBUG, INFO, WARNING, ERROR).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("ingest", help="Fetch, validate and store every configured series.")
    sub.add_parser("validate", help="Validate the configured source without writing to the DB.")
    sub.add_parser("analyze", help="Print YoY, rolling mean and correlation from the DB.")
    sub.add_parser("report", help="Write reports/report.md and reports/figures/*.png.")
    return parser


def _resolve_settings(args: argparse.Namespace) -> Settings:
    settings = load_settings()
    if args.source is not None:
        settings = dataclasses.replace(settings, source=args.source)
    if args.log_level is not None:
        settings = dataclasses.replace(settings, log_level=args.log_level.upper())
    configure_logging(settings.log_level)
    return settings


def _collect(
    settings: Settings, specs: dict[str, SeriesSpec]
) -> list[tuple[SeriesSpec, pd.DataFrame, ValidationReport]]:
    """Ingest and validate every series. Raises on the first validation failure."""
    collected: list[tuple[SeriesSpec, pd.DataFrame, ValidationReport]] = []
    for name, spec in specs.items():
        logger.info("Ingesting %s (%s) from source=%s", name, spec.code, settings.source)
        frame = ingest_series(spec, settings)
        report = validate_series(frame, spec.code)
        collected.append((spec, frame, report))
    return collected


def _cmd_ingest(settings: Settings, specs: dict[str, SeriesSpec]) -> int:
    settings.ensure_dirs()
    total = 0
    for spec, frame, report in _collect(settings, specs):
        written = upsert_observations(
            settings.db_path, frame, unit=spec.unit, source=settings.source
        )
        total += written
        print(
            f"{spec.name:<12} code={spec.code:<20} rows={written:>4} "
            f"missing={report.n_missing} range={report.date_range}"
        )
    print(f"Database: {settings.db_path}")
    print(f"Rows written this run: {total}")
    print(f"Total rows in database: {count_rows(settings.db_path)}")
    return EXIT_OK


def _cmd_validate(settings: Settings, specs: dict[str, SeriesSpec]) -> int:
    for spec, _frame, report in _collect(settings, specs):
        print(
            f"OK {spec.name:<12} code={spec.code:<20} rows={report.n_rows:>4} "
            f"missing={report.n_missing} range={report.date_range}"
        )
    print("Validation passed for all series.")
    return EXIT_OK


def _load_analysis(settings: Settings, specs: dict[str, SeriesSpec]) -> AnalysisResult:
    wide = read_wide(settings.db_path, {name: spec.code for name, spec in specs.items()})
    return run_analysis(wide)


def _cmd_analyze(settings: Settings, specs: dict[str, SeriesSpec]) -> int:
    result = _load_analysis(settings, specs)
    print("== Coverage (levels) ==")
    for name, rng in result.coverage.items():
        print(
            f"{name:<12} range={rng} n={int(result.levels[name].notna().sum())} "
            f"missing={result.n_missing[name]}"
        )
    print("\n== Year-over-year change (%), last 6 rows ==")
    print(result.yoy.dropna(how="all").tail(6).round(3).to_string())
    print("\n== Rolling 3-month mean (levels), last 6 rows ==")
    print(result.rolling.dropna(how="all").tail(6).round(3).to_string())
    print("\n== Correlation (levels, overlapping period only) ==")
    print(f"overlap range = {result.correlation.date_range}, n_obs = {result.correlation.n_obs}")
    if result.correlation.matrix.empty:
        print("Not enough overlapping observations to compute correlations.")
    else:
        print(result.correlation.matrix.round(4).to_string())
    print("\nCorrelation is not causation.")
    return EXIT_OK


def _cmd_report(settings: Settings, specs: dict[str, SeriesSpec]) -> int:
    result = _load_analysis(settings, specs)
    path = write_report(result, specs, settings.report_dir, settings.source)
    print(f"Wrote {path}")
    print(f"Figures in {settings.report_dir / 'figures'}")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = _resolve_settings(args)
        specs = get_series_specs()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    handlers = {
        "ingest": _cmd_ingest,
        "validate": _cmd_validate,
        "analyze": _cmd_analyze,
        "report": _cmd_report,
    }
    try:
        return handlers[args.command](settings, specs)
    except DataValidationError as exc:
        print(f"validation failed:\n{exc}", file=sys.stderr)
        return EXIT_VALIDATION
    except (AuthenticationError, EmptyResponseError, TransientNetworkError) as exc:
        print(f"ingestion failed: {exc}", file=sys.stderr)
        return EXIT_INGEST
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    except (EcolabError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
