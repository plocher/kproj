"""Unit tests for :mod:`kproj.services.kicad_project_reader`."""

from __future__ import annotations

from pathlib import Path

import pytest

from kproj.services.kicad_project_reader import (
    KicadProjectReader,
    ProjectResolutionError,
)


def _make_project(root: Path, name: str = "demo") -> Path:
    """Create a minimal KiCad project tree under *root*.

    *root* is created if missing. Returns the project directory.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.kicad_pro").write_text("")
    (root / f"{name}.kicad_pcb").write_text("")
    (root / f"{name}.kicad_sch").write_text("")
    return root


def _reader(projects_root: Path) -> KicadProjectReader:
    return KicadProjectReader(projects_root=projects_root)


def test_resolve_directory_input(tmp_path: Path) -> None:
    """A directory path resolves to the project inside."""
    proj_dir = _make_project(tmp_path / "demo")
    resolved = _reader(tmp_path).resolve(proj_dir)
    assert resolved.project_dir == proj_dir
    assert resolved.project_file == proj_dir / "demo.kicad_pro"
    assert resolved.pcb_file == proj_dir / "demo.kicad_pcb"
    assert resolved.root_schematic == proj_dir / "demo.kicad_sch"
    assert resolved.basename == "demo"


def test_resolve_project_file_input(tmp_path: Path) -> None:
    """A path to ``.kicad_pro`` resolves to its enclosing project."""
    proj_dir = tmp_path / "x"
    proj_dir.mkdir()
    _make_project(proj_dir)
    resolved = _reader(tmp_path).resolve(proj_dir / "demo.kicad_pro")
    assert resolved.project_dir == proj_dir


def test_resolve_sch_file_input(tmp_path: Path) -> None:
    """A path to ``.kicad_sch`` resolves to its enclosing project."""
    proj_dir = tmp_path / "x"
    proj_dir.mkdir()
    _make_project(proj_dir)
    resolved = _reader(tmp_path).resolve(proj_dir / "demo.kicad_sch")
    assert resolved.project_dir == proj_dir


def test_resolve_basename_lookup(tmp_path: Path) -> None:
    """A bare basename resolves under the configured projects root."""
    projects_root = tmp_path / "root"
    proj_dir = projects_root / "demo"
    proj_dir.mkdir(parents=True)
    _make_project(proj_dir)
    resolved = _reader(projects_root).resolve("demo")
    assert resolved.project_dir == proj_dir


def test_resolve_dot_means_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``"."`` resolves to the current working directory."""
    proj_dir = tmp_path / "here"
    proj_dir.mkdir()
    _make_project(proj_dir)
    monkeypatch.chdir(proj_dir)
    resolved = _reader(tmp_path).resolve(".")
    assert resolved.project_dir == proj_dir


def test_resolve_rejects_missing_project_file(tmp_path: Path) -> None:
    """A directory without a ``.kicad_pro`` raises ProjectResolutionError."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ProjectResolutionError, match=r"no \.kicad_pro found"):
        _reader(tmp_path).resolve(empty)


def test_resolve_rejects_ambiguous_project_files(tmp_path: Path) -> None:
    """Multiple ``.kicad_pro`` candidates raise ProjectResolutionError."""
    proj_dir = tmp_path / "x"
    proj_dir.mkdir()
    (proj_dir / "a.kicad_pro").write_text("")
    (proj_dir / "b.kicad_pro").write_text("")
    (proj_dir / "a.kicad_pcb").write_text("")
    (proj_dir / "a.kicad_sch").write_text("")
    with pytest.raises(ProjectResolutionError, match=r"multiple \.kicad_pro candidates"):
        _reader(tmp_path).resolve(proj_dir)


def test_resolve_rejects_missing_pcb(tmp_path: Path) -> None:
    """A project missing its ``.kicad_pcb`` raises ProjectResolutionError."""
    proj_dir = tmp_path / "x"
    proj_dir.mkdir()
    (proj_dir / "demo.kicad_pro").write_text("")
    (proj_dir / "demo.kicad_sch").write_text("")
    with pytest.raises(ProjectResolutionError, match="expected adjacent PCB"):
        _reader(tmp_path).resolve(proj_dir)


def test_resolve_rejects_missing_root_schematic(tmp_path: Path) -> None:
    """A project missing its root ``.kicad_sch`` raises ProjectResolutionError."""
    proj_dir = tmp_path / "x"
    proj_dir.mkdir()
    (proj_dir / "demo.kicad_pro").write_text("")
    (proj_dir / "demo.kicad_pcb").write_text("")
    with pytest.raises(ProjectResolutionError, match="expected root schematic"):
        _reader(tmp_path).resolve(proj_dir)


def test_resolve_rejects_unresolvable_input(tmp_path: Path) -> None:
    """A wholly unresolvable input raises ProjectResolutionError."""
    with pytest.raises(ProjectResolutionError, match="unable to resolve"):
        _reader(tmp_path).resolve("/no/such/path/here")


def test_resolve_includes_hierarchical_schematics(tmp_path: Path) -> None:
    """All ``.kicad_sch`` files in the project dir surface in ``hierarchical_schematics``."""
    proj_dir = tmp_path / "x"
    proj_dir.mkdir()
    _make_project(proj_dir, "demo")
    extra = proj_dir / "subsheet.kicad_sch"
    extra.write_text("")
    resolved = _reader(tmp_path).resolve(proj_dir)
    assert extra in resolved.hierarchical_schematics


def test_read_raises_not_implemented(tmp_path: Path) -> None:
    """The metadata reader stub raises until a future slice implements it."""
    proj_dir = tmp_path / "x"
    proj_dir.mkdir()
    _make_project(proj_dir)
    resolved = _reader(tmp_path).resolve(proj_dir)
    with pytest.raises(NotImplementedError):
        _reader(tmp_path).read(resolved)
