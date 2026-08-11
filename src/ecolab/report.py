"""Report layer: Markdown summary plus PNG charts.

Charts always carry a title, axis labels with units and a source line.
The matplotlib Agg backend is used so that rendering works headless in CI.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402  (must follow backend selection)
import pandas as pd  # noqa: E402

from .analyze import ROLLING_WINDOW, AnalysisResult  # noqa: E402
from .config import SeriesSpec  # noqa: E402

__all__ = ["render_charts", "render_markdown", "write_report"]

logger = logging.getLogger(__name__)


def _source_line(specs: dict[str, SeriesSpec], source: str) -> str:
    codes = ", ".join(f"{name}={spec.code}" for name, spec in specs.items())
    return f"Source: {source} | series: {codes}"


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    logger.info("Wrote figure %s", path)
    return path


def render_charts(
    result: AnalysisResult,
    specs: dict[str, SeriesSpec],
    figures_dir: Path,
    source: str,
) -> list[Path]:
    """Render one levels chart per series plus a combined YoY chart."""
    figures_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    footer = _source_line(specs, source)

    for name, spec in specs.items():
        if name not in result.levels.columns:
            continue
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.plot(result.levels.index, result.levels[name], label=f"{spec.label} (level)")
        if name in result.rolling.columns:
            ax.plot(
                result.rolling.index,
                result.rolling[name],
                linestyle="--",
                label=f"{ROLLING_WINDOW}-month rolling mean",
            )
        ax.set_title(f"{spec.label} — {result.coverage.get(name, 'n/a')}")
        ax.set_xlabel("Period (monthly)")
        ax.set_ylabel(f"{spec.label} [{spec.unit}]")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best", fontsize=8)
        fig.text(0.01, 0.01, footer, fontsize=7, alpha=0.7)
        written.append(_save(fig, figures_dir / f"{name}_level.png"))

    fig, ax = plt.subplots(figsize=(9, 4.5))
    for name in result.yoy.columns:
        ax.plot(result.yoy.index, result.yoy[name], label=f"{name} YoY")
    ax.axhline(0.0, color="black", linewidth=0.8)
    ax.set_title(f"Year-over-year change — {result.correlation.date_range}")
    ax.set_xlabel("Period (monthly)")
    ax.set_ylabel("Year-over-year change [%]")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8)
    fig.text(0.01, 0.01, footer, fontsize=7, alpha=0.7)
    written.append(_save(fig, figures_dir / "yoy_comparison.png"))
    return written


def _table(frame: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    """Render a small DataFrame as a GitHub-flavoured Markdown table."""
    header = "| | " + " | ".join(str(c) for c in frame.columns) + " |"
    divider = "|---" * (len(frame.columns) + 1) + "|"
    lines = [header, divider]
    for idx, row in frame.iterrows():
        cells = [
            "n/a" if pd.isna(v) else (floatfmt.format(v) if isinstance(v, float) else str(v))
            for v in row
        ]
        label = f"{idx:%Y-%m}" if isinstance(idx, pd.Timestamp) else str(idx)
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_markdown(
    result: AnalysisResult,
    specs: dict[str, SeriesSpec],
    source: str,
    figures: list[Path],
    report_dir: Path,
) -> str:
    """Build the Markdown report body."""
    generated = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = [
        "# data-economic-lab — Milestone 1 report",
        "",
        f"Generated: {generated}",
        f"Data source: **{source}**",
        "",
        "## 1. Series and coverage",
        "",
        "| name | series code | unit | date range | observations | missing |",
        "|---|---|---|---|---|---|",
    ]
    for name, spec in specs.items():
        if name not in result.levels.columns:
            continue
        column = result.levels[name]
        lines.append(
            f"| {name} | `{spec.code}` | {spec.unit} | {result.coverage.get(name, 'n/a')} "
            f"| {int(column.notna().sum())} | {result.n_missing.get(name, 0)} |"
        )

    lines += [
        "",
        "## 2. Year-over-year change (%)",
        "",
        f"Computed as `(v_t / v_(t-12) - 1) * 100`. Date range of the input: "
        f"{result.correlation.date_range if result.correlation.n_obs else 'n/a'}.",
        "",
        "Last 6 available rows:",
        "",
        _table(result.yoy.dropna(how="all").tail(6)),
        "",
        f"## 3. Rolling {ROLLING_WINDOW}-month mean (levels)",
        "",
        "Last 6 available rows:",
        "",
        _table(result.rolling.dropna(how="all").tail(6)),
        "",
        "## 4. Correlation (levels, overlapping period only)",
        "",
        f"- Overlapping period: **{result.correlation.date_range}**",
        f"- Complete-case observations: **n = {result.correlation.n_obs}**",
        "",
    ]
    if result.correlation.matrix.empty:
        lines.append("Not enough overlapping observations to compute a correlation table.")
    else:
        lines.append(_table(result.correlation.matrix))
    lines += [
        "",
        "> Correlation is not causation. These coefficients describe co-movement over a short",
        "> sample and are not evidence of a causal mechanism.",
        "",
        "## 5. Figures",
        "",
    ]
    for figure in figures:
        rel = figure.relative_to(report_dir) if figure.is_relative_to(report_dir) else figure
        lines.append(f"![{figure.stem}]({rel.as_posix()})")
    lines += ["", _source_line(specs, source), ""]
    return "\n".join(lines)


def write_report(
    result: AnalysisResult,
    specs: dict[str, SeriesSpec],
    report_dir: Path,
    source: str,
) -> Path:
    """Write ``reports/report.md`` and the figures. Returns the report path."""
    figures_dir = report_dir / "figures"
    figures = render_charts(result, specs, figures_dir, source)
    body = render_markdown(result, specs, source, figures, report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "report.md"
    path.write_text(body, encoding="utf-8")
    logger.info("Wrote report %s (%d figures)", path, len(figures))
    return path
