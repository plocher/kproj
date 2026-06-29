"""Unit tests for :mod:`kproj.model.export_result`."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from kproj.model.export_result import ExportResult


def test_export_result_is_frozen() -> None:
    """``ExportResult`` is immutable."""
    result = ExportResult(path=Path("/tmp/out.png"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.elapsed_seconds = 1.5  # type: ignore[misc]


def test_export_result_defaults_are_explicit() -> None:
    """Default values match the DESIGN contract."""
    result = ExportResult(path=Path("/tmp/out.png"))
    assert result.diagnostics == ()
    assert result.command is None
    assert result.elapsed_seconds == 0.0
    assert result.skipped is False


def test_export_result_skipped_flag_pairs_with_none_path() -> None:
    """When skipped, ``path`` may be ``None`` and the caller must check ``skipped``."""
    result = ExportResult(path=None, skipped=True)
    assert result.path is None
    assert result.skipped is True


def test_export_result_command_is_a_tuple() -> None:
    """Subprocess services record their argv as a tuple (frozen-friendly)."""
    result = ExportResult(
        path=Path("/tmp/out.png"),
        command=("kicad-cli", "pcb", "render", "--side", "top"),
    )
    assert isinstance(result.command, tuple)
