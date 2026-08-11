"""Report tests. All output goes to tmp_path; nothing touches the repo."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ecolab.analyze import run_analysis
from ecolab.config import DEFAULT_SERIES
from ecolab.report import render_charts, render_markdown, write_report


def _wide() -> pd.DataFrame:
    index = pd.date_range("2020-01-01", periods=24, freq="MS", name="period")
    return pd.DataFrame(
        {
            "cpi": [100.0 + i for i in range(24)],
            "usdtry": [5.0 + 0.1 * i for i in range(24)],
            "policy_rate": [10.0 + 0.5 * i for i in range(24)],
        },
        index=index,
    )


def test_render_charts_writes_one_png_per_series_plus_a_comparison(tmp_path: Path) -> None:
    result = run_analysis(_wide())
    figures = render_charts(result, DEFAULT_SERIES, tmp_path / "figures", "sample")
    names = sorted(p.name for p in figures)
    assert names == [
        "cpi_level.png",
        "policy_rate_level.png",
        "usdtry_level.png",
        "yoy_comparison.png",
    ]
    for path in figures:
        assert path.exists()
        assert path.stat().st_size > 0


def test_render_markdown_contains_the_required_sections(tmp_path: Path) -> None:
    result = run_analysis(_wide())
    body = render_markdown(result, DEFAULT_SERIES, "sample", [], tmp_path)
    for heading in (
        "## 1. Series and coverage",
        "## 2. Year-over-year change (%)",
        "## 3. Rolling 3-month mean (levels)",
        "## 4. Correlation (levels, overlapping period only)",
        "## 5. Figures",
    ):
        assert heading in body
    assert "Correlation is not causation." in body
    # every series code appears, so the reader can check what was measured
    for spec in DEFAULT_SERIES.values():
        assert spec.code in body


def test_render_markdown_reports_the_observation_count(tmp_path: Path) -> None:
    result = run_analysis(_wide())
    body = render_markdown(result, DEFAULT_SERIES, "sample", [], tmp_path)
    assert f"n = {result.correlation.n_obs}" in body
    assert result.correlation.date_range in body


def test_write_report_creates_report_md_and_figures(tmp_path: Path) -> None:
    result = run_analysis(_wide())
    path = write_report(result, DEFAULT_SERIES, tmp_path / "reports", "sample")
    assert path == tmp_path / "reports" / "report.md"
    assert path.exists()
    assert len(list((tmp_path / "reports" / "figures").glob("*.png"))) == 4
    body = path.read_text(encoding="utf-8")
    assert "figures/cpi_level.png" in body
