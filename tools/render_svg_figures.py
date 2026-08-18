"""Render compact SVG figures for the README from the sample dataset.

Usage (from the repository root):

    PYTHONPATH=src ECOLAB_SOURCE=sample python tools/render_svg_figures.py

Writes four hand-rolled (dependency-light) SVG line charts to docs/figures/:
cpi_level.svg, usdtry_level.svg, policy_rate_level.svg, yoy_comparison.svg.

The charts are intentionally minimal SVG (a few KB each) so they can live in
git without bloating the repository, unlike the PNG output of `ecolab report`
which is meant for local/ad-hoc use and is not committed.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ecolab.analyze import run_analysis
from ecolab.config import get_series_specs, load_settings
from ecolab.ingest import ingest_series
from ecolab.validate import validate_series

W, H = 720, 340
ML, MR, MT, MB = 62, 16, 34, 46  # margins
PW, PH = W - ML - MR, H - MT - MB  # plot area
COLORS = ["#1f77b4", "#ff7f0e", "#2ca02c"]
FONT = "font-family='Segoe UI, Helvetica, Arial, sans-serif'"


def _scale(values: pd.Series, lo: float, hi: float, out_lo: float, out_hi: float) -> pd.Series:
    span = (hi - lo) or 1.0
    return out_lo + (values - lo) / span * (out_hi - out_lo)


def _nice_ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    import math

    span = (hi - lo) or 1.0
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min(s for s in (1 * mag, 2 * mag, 5 * mag, 10 * mag) if s >= raw)
    start = math.ceil(lo / step) * step
    ticks = []
    t = start
    while t <= hi + 1e-9:
        ticks.append(round(t, 10))
        t += step
    return ticks


def _polyline(x: pd.Series, y: pd.Series, color: str, dash: str = "") -> str:
    pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in zip(x, y) if pd.notna(b))
    dash_attr = f" stroke-dasharray='{dash}'" if dash else ""
    return (
        f"<polyline points='{pts}' fill='none' stroke='{color}' "
        f"stroke-width='1.8' stroke-linejoin='round'{dash_attr}/>"
    )


def render_chart(
    frame: pd.DataFrame,
    series: list[tuple[str, str, str]],  # (column, label, dash)
    title: str,
    ylabel: str,
    out_path: Path,
    zero_line: bool = False,
) -> None:
    idx = frame.index
    x = _scale(pd.Series(range(len(idx)), index=idx), 0, len(idx) - 1, ML, ML + PW)
    lo = min(frame[c].min() for c, _, _ in series)
    hi = max(frame[c].max() for c, _, _ in series)
    pad = (hi - lo) * 0.05 or 1.0
    lo, hi = lo - pad, hi + pad

    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{W}' height='{H}' "
        f"viewBox='0 0 {W} {H}'>",
        f"<rect width='{W}' height='{H}' fill='white'/>",
        f"<text x='{ML + PW / 2:.0f}' y='20' text-anchor='middle' font-size='14' "
        f"font-weight='bold' {FONT}>{title}</text>",
    ]
    # y grid + labels
    for t in _nice_ticks(lo, hi):
        yy = _scale(pd.Series([t]), lo, hi, MT + PH, MT).iloc[0]
        parts.append(
            f"<line x1='{ML}' y1='{yy:.1f}' x2='{ML + PW}' y2='{yy:.1f}' "
            f"stroke='#dddddd' stroke-width='0.7'/>"
        )
        label = f"{t:g}"
        parts.append(
            f"<text x='{ML - 6}' y='{yy + 3.5:.1f}' text-anchor='end' font-size='10' "
            f"{FONT}>{label}</text>"
        )
    # x labels: January of each year
    for i, period in enumerate(idx):
        if period.month == 1:
            xx = x.iloc[i]
            parts.append(
                f"<line x1='{xx:.1f}' y1='{MT}' x2='{xx:.1f}' y2='{MT + PH}' "
                f"stroke='#eeeeee' stroke-width='0.7'/>"
            )
            parts.append(
                f"<text x='{xx:.1f}' y='{MT + PH + 16}' text-anchor='middle' "
                f"font-size='10' {FONT}>{period.year}</text>"
            )
    if zero_line:
        y0 = _scale(pd.Series([0.0]), lo, hi, MT + PH, MT).iloc[0]
        parts.append(
            f"<line x1='{ML}' y1='{y0:.1f}' x2='{ML + PW}' y2='{y0:.1f}' "
            f"stroke='#888888' stroke-width='0.9'/>"
        )
    # series
    for (col, _label, dash), color in zip(series, COLORS):
        yvals = _scale(frame[col], lo, hi, MT + PH, MT)
        parts.append(_polyline(x, yvals, color, dash))
    # legend
    lx = ML + 10
    for (col, label, dash), color in zip(series, COLORS):
        dash_attr = f" stroke-dasharray='{dash}'" if dash else ""
        parts.append(
            f"<line x1='{lx}' y1='{MT + 12}' x2='{lx + 22}' y2='{MT + 12}' "
            f"stroke='{color}' stroke-width='1.8'{dash_attr}/>"
        )
        parts.append(
            f"<text x='{lx + 27}' y='{MT + 16}' font-size='10' {FONT}>{label}</text>"
        )
        lx += 27 + 7 * len(label) + 18
    # axes + footer
    parts.append(
        f"<rect x='{ML}' y='{MT}' width='{PW}' height='{PH}' fill='none' "
        f"stroke='#333333' stroke-width='0.9'/>"
    )
    parts.append(
        f"<text x='16' y='{MT + PH / 2:.0f}' text-anchor='middle' font-size='10' {FONT} "
        f"transform='rotate(-90 16 {MT + PH / 2:.0f})'>{ylabel}</text>"
    )
    parts.append(
        f"<text x='{ML}' y='{H - 8}' font-size='9' fill='#666666' {FONT}>"
        f"Source: sample dataset | generated by tools/render_svg_figures.py</text>"
    )
    parts.append("</svg>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    settings = load_settings()
    specs = get_series_specs()
    frames: dict[str, pd.DataFrame] = {}
    for name, spec in specs.items():
        frame = ingest_series(spec, settings)
        validate_series(frame, spec.code)
        frames[name] = frame
    wide = pd.DataFrame(
        {name: frame.set_index("period")["value"] for name, frame in frames.items()}
    ).sort_index()
    result = run_analysis(wide)

    out_dir = Path("docs/figures")
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, spec in specs.items():
        df = pd.DataFrame(
            {"level": wide[name], "roll3": result.rolling[name]}
        ).dropna(subset=["level"])
        render_chart(
            df,
            [("level", f"{name} (level)", ""), ("roll3", "3-month rolling mean", "5,3")],
            f"{spec.label} \u2014 {df.index.min():%Y-%m}..{df.index.max():%Y-%m}",
            spec.unit,
            out_dir / f"{name}_level.svg",
        )

    yoy = result.yoy.dropna(how="all")
    render_chart(
        yoy,
        [(c, f"{c} YoY", "") for c in yoy.columns],
        f"Year-over-year change (%) \u2014 {yoy.index.min():%Y-%m}..{yoy.index.max():%Y-%m}",
        "percent",
        out_dir / "yoy_comparison.svg",
        zero_line=True,
    )

    print("===== OTOMATIK KONTROL =====")
    for p in sorted(out_dir.glob("*.svg")):
        print(f"PASS {p.name} bytes={p.stat().st_size}")


if __name__ == "__main__":
    main()
