"""Tests for configuration loading and the typed error hierarchy."""

from __future__ import annotations

from datetime import date

import pytest

from ecolab.config import (
    DEFAULT_SERIES,
    configure_logging,
    get_series_specs,
    load_settings,
    require_api_key,
)
from ecolab.errors import (
    AuthenticationError,
    ConfigError,
    DataValidationError,
    EcolabError,
    EmptyResponseError,
    TransientNetworkError,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every ECOLAB_* / EVDS_* variable so defaults are observable."""
    import os

    for key in list(os.environ):
        if key.startswith(("ECOLAB_", "EVDS_")):
            monkeypatch.delenv(key, raising=False)


def test_defaults_are_documented_and_stable() -> None:
    settings = load_settings()
    assert settings.source == "sample"
    assert settings.start == date(2019, 1, 1)
    assert settings.end == date(2024, 12, 1)
    assert settings.max_retries == 3
    assert settings.raw_dir == settings.data_dir / "raw"
    assert settings.sample_dir == settings.data_dir / "sample"


def test_environment_overrides_are_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ECOLAB_SOURCE", "EVDS")
    monkeypatch.setenv("ECOLAB_START", "2020-03-01")
    monkeypatch.setenv("ECOLAB_MAX_RETRIES", "7")
    settings = load_settings()
    assert settings.source == "evds"
    assert settings.start == date(2020, 3, 1)
    assert settings.max_retries == 7


def test_unknown_source_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ECOLAB_SOURCE", "kaggle")
    with pytest.raises(ConfigError, match="ECOLAB_SOURCE"):
        load_settings()


def test_bad_date_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ECOLAB_START", "01/2020")
    with pytest.raises(ConfigError, match="ISO date"):
        load_settings()


def test_start_after_end_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ECOLAB_START", "2024-01-01")
    monkeypatch.setenv("ECOLAB_END", "2020-01-01")
    with pytest.raises(ConfigError, match="is after"):
        load_settings()


def test_series_registry_has_the_three_required_series() -> None:
    specs = get_series_specs()
    assert set(specs) == {"cpi", "usdtry", "policy_rate"}
    for name, spec in specs.items():
        assert spec.code == DEFAULT_SERIES[name].code
        assert spec.unit


def test_series_code_can_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ECOLAB_SERIES_CPI", "TP.FG.J01")
    specs = get_series_specs()
    assert specs["cpi"].code == "TP.FG.J01"
    # only the code changes; the rest of the spec is preserved
    assert specs["cpi"].unit == DEFAULT_SERIES["cpi"].unit
    assert specs["cpi"].name == DEFAULT_SERIES["cpi"].name


def test_require_api_key_raises_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVDS_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="EVDS_API_KEY"):
        require_api_key()


def test_require_api_key_returns_the_value_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVDS_API_KEY", "  abc123  ")
    assert require_api_key() == "abc123"


def test_configure_logging_accepts_a_level() -> None:
    configure_logging("WARNING")  # must not raise
    configure_logging("NOT_A_LEVEL")  # falls back to INFO, must not raise


def test_every_error_derives_from_the_base_error() -> None:
    for exc in (
        ConfigError,
        AuthenticationError,
        EmptyResponseError,
        TransientNetworkError,
        DataValidationError,
    ):
        assert issubclass(exc, EcolabError)


def test_data_validation_error_lists_every_problem() -> None:
    exc = DataValidationError("TP.FG.J0", ["duplicated periods (1): 2020-01", "gap larger"])
    assert exc.series_code == "TP.FG.J0"
    assert len(exc.problems) == 2
    assert "duplicated periods" in str(exc)
    assert "gap larger" in str(exc)
