"""Regenerate data/sample/*.csv deterministically.

The sample files are SYNTHETIC. They exist so that `pytest` and CI can run with
no network access and no API key. They are not TCMB or TUIK statistics and must
never be used for economic inference.

Every value is a closed-form function of the month index, so this script is
byte-reproducible: running it must leave `git status` clean.

Usage:
    python scripts/gen_sample.py
    python scripts/gen_sample.py --check   # verify files match, do not write
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "sample"

START_YEAR = 2019
END_YEAR = 2024
MONTHS: list[tuple[int, int]] = [
    (y, m) for y in range(START_YEAR, END_YEAR + 1) for m in range(1, 13)
]

HEADER = (
    "# SYNTHETIC SAMPLE DATA -- NOT REAL TCMB/TUIK STATISTICS.\n"
    "# Generated deterministically for offline tests and CI. See data/sample/README.md.\n"
)


def render(values: list[float], digits: int) -> str:
    """Render a series as the exact CSV text stored in data/sample/."""
    parts = [HEADER, "period,value\n"]
    for (year, month), value in zip(MONTHS, values, strict=True):
        parts.append(f"{year}-{month:02d},{value:.{digits}f}\n")
    return "".join(parts)


def cpi_series() -> list[float]:
    """Consumer price index level, compounding at a rising monthly rate."""
    out: list[float] = []
    level = 400.0
    for i in range(len(MONTHS)):
        rate = 0.012 + 0.010 * (i / 71.0) + 0.003 * math.sin(2 * math.pi * (i % 12) / 12.0)
        level *= 1.0 + rate
        out.append(level)
    return out


def usdtry_series() -> list[float]:
    """USD/TRY monthly average, exponential trend with mild curvature."""
    return [5.50 * math.exp(0.0225 * i + 0.00012 * i * i) for i in range(len(MONTHS))]


def policy_rate_series() -> list[float]:
    """Policy rate in percent per annum, piecewise linear plateaus."""
    out: list[float] = []
    for i in range(len(MONTHS)):
        if i < 12:
            value = 22.0 - 0.9 * i
        elif i < 24:
            value = 11.0 + 0.25 * (i - 12)
        elif i < 36:
            value = 14.0 + 0.05 * (i - 24)
        elif i < 48:
            value = 14.5 - 0.20 * (i - 36)
        elif i < 60:
            value = 12.0 + 2.6 * (i - 48)
        else:
            value = 43.0 + 0.55 * (i - 60)
        out.append(value)
    return out


def build() -> dict[str, str]:
    """Return {filename: csv text} for every sample series."""
    return {
        "cpi.csv": render(cpi_series(), 2),
        "usdtry.csv": render(usdtry_series(), 4),
        "policy_rate.csv": render(policy_rate_series(), 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Regenerate the synthetic sample CSVs.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the files on disk match the generator, without writing",
    )
    args = parser.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    files = build()
    mismatched: list[str] = []

    for name, text in files.items():
        path = OUT_DIR / name
        if args.check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != text:
                mismatched.append(name)
            status = "ok" if current == text else "MISMATCH"
            print(f"{status:9s} {path.relative_to(REPO_ROOT)}")
        else:
            path.write_text(text, encoding="utf-8")
            print(f"wrote     {path.relative_to(REPO_ROOT)} ({len(text)} bytes)")

    if mismatched:
        print(f"\n{len(mismatched)} file(s) differ from the generator: {', '.join(mismatched)}")
        return 1
    print(f"\n{len(files)} sample files, {len(MONTHS)} monthly observations each.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
