"""Typed error hierarchy for ecolab.

Every failure mode the pipeline can produce has an explicit type so that the
CLI can map it to a readable message and a non-zero exit code.
"""

from __future__ import annotations

__all__ = [
    "AuthenticationError",
    "ConfigError",
    "DataValidationError",
    "EcolabError",
    "EmptyResponseError",
    "TransientNetworkError",
]


class EcolabError(Exception):
    """Base class for all errors raised by ecolab."""


class ConfigError(EcolabError):
    """Configuration is missing or invalid (e.g. missing API key)."""


class AuthenticationError(EcolabError):
    """The data source rejected the credentials (HTTP 401/403 or API message)."""


class EmptyResponseError(EcolabError):
    """The data source returned a syntactically valid but empty result set."""


class TransientNetworkError(EcolabError):
    """A retryable network or server-side failure (timeouts, 5xx, connection resets)."""


class DataValidationError(EcolabError):
    """The downloaded data violated at least one validation rule."""

    def __init__(self, series_code: str, problems: list[str]) -> None:
        self.series_code = series_code
        self.problems = problems
        detail = "\n".join(f"  - {p}" for p in problems)
        super().__init__(f"Validation failed for series '{series_code}':\n{detail}")
