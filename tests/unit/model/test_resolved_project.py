"""Unit tests for :mod:`kproj.model.resolved_project`."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from kproj.model.resolved_project import ResolvedProject


def _resolved(tmp_path: Path) -> ResolvedProject:
    pro = tmp_path / "demo.kicad_pro"
    pcb = tmp_path / "demo.kicad_pcb"
    sch = tmp_path / "demo.kicad_sch"
    for p in (pro, pcb, sch):
        p.write_text("")
    return ResolvedProject(
        project_file=pro,
        project_dir=tmp_path,
        pcb_file=pcb,
        root_schematic=sch,
        hierarchical_schematics=(sch,),
    )


def test_resolved_project_is_frozen(tmp_path: Path) -> None:
    """``ResolvedProject`` is immutable."""
    resolved = _resolved(tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        resolved.project_file = tmp_path  # type: ignore[misc]


def test_resolved_project_defaults_for_optional_fields(tmp_path: Path) -> None:
    """``jbom_resolved`` and ``diagnostics`` default to None / empty tuple."""
    resolved = _resolved(tmp_path)
    assert resolved.jbom_resolved is None
    assert resolved.diagnostics == ()


def test_resolved_project_basename_returns_project_stem(tmp_path: Path) -> None:
    """``ResolvedProject.basename`` returns the ``.kicad_pro`` filename stem."""
    resolved = _resolved(tmp_path)
    assert resolved.basename == "demo"
