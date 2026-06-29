"""Unit tests for :mod:`kproj.model.finding`."""

from __future__ import annotations

import dataclasses

import pytest

from kproj.model.finding import Finding
from kproj.model.severity import Severity


def _sample_finding(**overrides: object) -> Finding:
    """Return a populated Finding, overriding fields per kwargs."""
    base: dict[str, object] = {
        "severity": Severity.WARNING,
        "field": "comment9",
        "value": "",
        "reason": "comment9 empty; defaulting to status: active",
    }
    base.update(overrides)
    return Finding(**base)  # type: ignore[arg-type]


def test_finding_is_frozen() -> None:
    """``Finding`` must be a frozen dataclass — assignment fails."""
    finding = _sample_finding()
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.field = "tag"  # type: ignore[misc]


def test_finding_optional_metadata_defaults_to_empty() -> None:
    """Project + location_hint are optional and default to empty strings."""
    finding = _sample_finding()
    assert finding.project == ""
    assert finding.location_hint == ""


def test_finding_carries_kicad_drc_location() -> None:
    """A DRC Finding can record severity, type, location, and message."""
    finding = Finding(
        severity=Severity.ERROR,
        field="silk_overlap",
        value="(150.5, 80.0)",
        reason="Silkscreen overlaps pad",
        project="cpNode-Xiao-68x90",
        location_hint="F.SilkS",
    )
    assert finding.severity is Severity.ERROR
    assert finding.project == "cpNode-Xiao-68x90"


def test_finding_equality_is_value_based() -> None:
    """Two Findings with identical fields compare equal (dataclass default)."""
    one = _sample_finding()
    other = _sample_finding()
    assert one == other
    assert hash(one) == hash(other)
