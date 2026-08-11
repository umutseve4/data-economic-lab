"""End-to-end CLI tests. Offline only: source=sample, no API key, no network."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ecolab.cli import EXIT_CONFIG, EXIT_OK, build_parser, main
from ecolab.store import count_rows

REPO_SAMPLE_DIR = Path(__file__).resolve().parents[1] / "data" / "sample"


@pytest.fixture
def offline_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every writable path at tmp_path and remove any credential."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO_SAMPLE_DIR, data_dir / "sample")

    monkeypatch.setenv("ECOLAB_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ECOLAB_DB_PATH", str(data_dir / "economic.db"))
    monkeypatch.setenv("ECOLAB_REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setenv("ECOLAB_SOURCE", "sample")
    monkeypatch.setenv("ECOLAB_LOG_LEVEL", "WARNING")
    monkeypatch.delenv("EVDS_API_KEY", raising=False)
    return tmp_path


def test_parser_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_parser_accepts_the_four_commands() -> None:
    parser = build_parser()
    for command in ("ingest", "validate", "analyze", "report"):
        assert parser.parse_args([command]).command == command


def test_validate_command_passes_on_the_sample_data(offline_env: Path) -> None:
    assert main(["validate"]) == EXIT_OK


def test_ingest_is_idempotent_end_to_end(offline_env: Path) -> None:
    db = offline_env / "data" / "economic.db"
    assert main(["ingest"]) == EXIT_OK
    first = count_rows(db)
    assert main(["ingest"]) == EXIT_OK
    second = count_rows(db)
    assert first == second == 216


def test_analyze_runs_after_ingest(offline_env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ingest"]) == EXIT_OK
    capsys.readouterr()
    assert main(["analyze"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "== Correlation (levels, overlapping period only) ==" in out
    assert "n_obs =" in out
    assert "Correlation is not causation." in out


def test_report_writes_markdown_and_figures(offline_env: Path) -> None:
    assert main(["ingest"]) == EXIT_OK
    assert main(["report"]) == EXIT_OK
    report = offline_env / "reports" / "report.md"
    assert report.exists()
    figures = sorted(p.name for p in (offline_env / "reports" / "figures").glob("*.png"))
    assert figures == [
        "cpi_level.png",
        "policy_rate_level.png",
        "usdtry_level.png",
        "yoy_comparison.png",
    ]


def test_bad_source_is_a_configuration_error(
    offline_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ECOLAB_SOURCE", "nonsense")
    assert main(["validate"]) == EXIT_CONFIG


def test_evds_without_a_key_is_a_configuration_error(offline_env: Path) -> None:
    # --source evds with no EVDS_API_KEY must fail loudly, not silently.
    assert main(["--source", "evds", "ingest"]) == EXIT_CONFIG
