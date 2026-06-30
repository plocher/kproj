"""Unit tests for :mod:`kproj.model.library_ref`."""

from __future__ import annotations

import dataclasses

import pytest

from kproj.model.library_ref import LibraryRef


def test_library_ref_is_frozen() -> None:
    """``LibraryRef`` is immutable."""
    ref = LibraryRef(name="SPCoast", source="external")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.name = "Other"  # type: ignore[misc]


def test_library_ref_is_orderable_by_name(tmp_path_factory: pytest.TempPathFactory) -> None:
    """``LibraryRef`` instances sort by ``(name, source)`` lexicographically."""
    refs = [
        LibraryRef(name="Zeta", source="ambiguous"),
        LibraryRef(name="Alpha", source="external"),
        LibraryRef(name="Mid", source="internal"),
    ]
    assert sorted(refs) == [
        LibraryRef(name="Alpha", source="external"),
        LibraryRef(name="Mid", source="internal"),
        LibraryRef(name="Zeta", source="ambiguous"),
    ]


def test_library_ref_equality_is_by_value() -> None:
    """Two refs with the same name+source are equal."""
    assert LibraryRef(name="A", source="internal") == LibraryRef(name="A", source="internal")
    assert LibraryRef(name="A", source="internal") != LibraryRef(name="A", source="external")
