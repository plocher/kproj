"""Unit tests for :mod:`kproj.model.severity`."""

from __future__ import annotations

import pytest

from kproj.model.severity import Severity


def test_severity_has_four_levels() -> None:
    """The closed taxonomy includes exit-neutral ``info``."""
    assert {member.value for member in Severity} == {"error", "warning", "exclusion", "info"}


def test_severity_ordering_error_more_severe_than_warning() -> None:
    """Higher severity must compare greater than lower severity."""
    assert Severity.ERROR > Severity.WARNING
    assert Severity.WARNING > Severity.EXCLUSION
    assert Severity.EXCLUSION > Severity.INFO


def test_severity_from_string_round_trips() -> None:
    """``Severity(value)`` constructs the canonical member from its string."""
    for member in Severity:
        assert Severity(member.value) is member


def test_severity_rejects_unknown_value() -> None:
    """An unknown severity string raises ``ValueError`` (per dataclass discipline)."""
    with pytest.raises(ValueError):
        Severity("critical")
