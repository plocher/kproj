"""Unit tests for :mod:`kproj.model.library_ref`."""

from __future__ import annotations

import dataclasses

import pytest

from kproj.model.library_ref import LibraryRef


def test_library_ref_is_frozen() -> None:
    """``LibraryRef`` is immutable."""
    ref = LibraryRef(name="SPCoast", source="external", kind="symbol", distribution="added")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.name = "Other"  # type: ignore[misc]


def test_library_ref_is_orderable_by_name_kind_source() -> None:
    """``LibraryRef`` instances sort by dataclass order (name/source/kind)."""
    refs = [
        LibraryRef(name="Shared", source="ambiguous", kind="symbol"),
        LibraryRef(name="Shared", source="ambiguous", kind="footprint"),
        LibraryRef(name="Alpha", source="external", kind="symbol"),
    ]
    assert sorted(refs) == [
        LibraryRef(name="Alpha", source="external", kind="symbol"),
        LibraryRef(name="Shared", source="ambiguous", kind="footprint"),
        LibraryRef(name="Shared", source="ambiguous", kind="symbol"),
    ]


def test_library_ref_equality_is_by_value() -> None:
    """Equality distinguishes symbol-vs-footprint refs with same name/source."""
    assert LibraryRef(name="A", source="internal", kind="symbol") == LibraryRef(
        name="A",
        source="internal",
        kind="symbol",
    )
    assert LibraryRef(name="A", source="internal", kind="symbol") != LibraryRef(
        name="A",
        source="internal",
        kind="footprint",
    )
