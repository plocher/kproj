"""Unit tests for :mod:`kproj.model.project_info`."""

from __future__ import annotations

import dataclasses

import pytest

from kproj.model.project_info import ProjectInfo, Status


def _info(**overrides: object) -> ProjectInfo:
    """Return a populated ProjectInfo with optional field overrides."""
    base: dict[str, object] = {
        "project": "cpNode-Xiao-68x90",
        "title": "cpNode-Xiao-68x90",
        "company": "MRCS",
        "design_rev": "1.0",
        "board_rev": "1.0B",
        "date": "2026.06",
        "designer": "John Plocher",
        "tagline": "MRCS cpNode controller",
        "overview": "MRCS cpNode controller for layout automation.",
        "status": Status.ACTIVE,
    }
    base.update(overrides)
    return ProjectInfo(**base)  # type: ignore[arg-type]


def test_status_enum_has_six_v1_values() -> None:
    """The v1 taxonomy: experimental, active, retired, broken, replaced-by, private."""
    expected = {"experimental", "active", "retired", "broken", "replaced-by", "private"}
    assert {member.value for member in Status} == expected


def test_project_info_is_frozen() -> None:
    """``ProjectInfo`` must be immutable."""
    info = _info()
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.title = "other"  # type: ignore[misc]


def test_project_info_optional_fields_have_defaults() -> None:
    """Optional fields default to empty / None / empty tuple."""
    info = _info()
    assert info.fab_date == ""
    assert info.fabricated is False
    assert info.replaced_by_target is None
    assert info.tags == ()


def test_project_info_replaced_by_carries_target() -> None:
    """Status REPLACED_BY pairs with a non-None target directory name."""
    info = _info(status=Status.REPLACED_BY, replaced_by_target="cpNode-Xiao-68x90-v2")
    assert info.status is Status.REPLACED_BY
    assert info.replaced_by_target == "cpNode-Xiao-68x90-v2"


def test_project_info_tags_are_a_tuple() -> None:
    """Tags is a tuple (hashable / immutable) per frozen-dataclass discipline."""
    info = _info(tags=("MRCS", "kicad"))
    assert isinstance(info.tags, tuple)
