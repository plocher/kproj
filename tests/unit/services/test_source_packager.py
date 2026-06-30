"""Unit tests for :mod:`kproj.services.source_packager`.

Validates the contract per ``docs/DESIGN.md`` § *SourcePackager*:

- Walks ``project_dir`` per the documented Include/Exclude rules.
- Assembles the matching files into ``<P>-<R>.source.zip`` via an
  atomic sibling-tempfile + ``os.replace``.
- Optional ChangeJournal injection registers the produced zip for
  ADR-0005 rollback.

There is intentionally no SOURCE_README / external-library manifest
in v1 - KiCad's own UI surfaces missing libraries when the project
is opened, so the archive captures project artifacts only.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from kproj.model.export_result import ExportResult
from kproj.services.change_journal import ChangeJournal
from kproj.services.source_packager import SourcePackager
from kproj.services.zip_archiver import ZipArchiver


@pytest.fixture
def packager() -> SourcePackager:
    """Return a :class:`SourcePackager` wired to a fresh :class:`ZipArchiver`."""
    return SourcePackager(zip_archiver=ZipArchiver())


def _make_project(
    project_dir: Path,
    *,
    title: str = "demo",
) -> None:
    """Create a small representative KiCad project under *project_dir*."""
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / f"{title}.kicad_pro").write_text("{}\n")
    (project_dir / f"{title}.kicad_sch").write_text(
        '(kicad_sch (lib_id "SPCoast_KiCad_Library:R_0805") (uuid "deadbeef"))\n'
    )
    (project_dir / f"{title}.kicad_pcb").write_text(
        '(kicad_pcb (footprint "Resistor_SMD:R_0805_2012Metric") (uuid "feed"))\n'
    )
    (project_dir / "README.md").write_text("# demo\n")
    (project_dir / "LICENSE").write_text("MIT\n")


# ----- include / exclude rules -----


def test_package_includes_kicad_project_files(packager: SourcePackager, tmp_path: Path) -> None:
    """The produced zip carries the *.kicad_pro/sch/pcb + README + LICENSE."""
    project = tmp_path / "demo"
    _make_project(project)
    output = tmp_path / "demo-1.0.source.zip"

    result = packager.package(project_dir=project, output=output, title="demo", rev="1.0")
    assert isinstance(result, ExportResult)
    assert result.skipped is False
    assert result.path == output
    with zipfile.ZipFile(output) as zf:
        names = set(zf.namelist())
    assert {"demo.kicad_pro", "demo.kicad_sch", "demo.kicad_pcb", "README.md", "LICENSE"} <= names


def test_package_excludes_derived_artifacts(packager: SourcePackager, tmp_path: Path) -> None:
    """Excluded suffixes (.kicad_prl, .step, .ibom.html) are not added."""
    project = tmp_path / "demo"
    _make_project(project)
    # Add representative excluded artifacts.
    (project / "demo.kicad_prl").write_text("{}")
    (project / "demo.step").write_text("ISO-10303-21;")
    (project / "demo.ibom.html").write_text("<html/>")
    (project / "demo-bak").write_text("backup")
    (project / "production").mkdir()
    (project / "production" / "bom.csv").write_text("noop")
    (project / ".git").mkdir()
    (project / ".git" / "config").write_text("noop")

    output = tmp_path / "out.source.zip"
    packager.package(project_dir=project, output=output, title="demo", rev="1.0")
    with zipfile.ZipFile(output) as zf:
        names = list(zf.namelist())
    assert "demo.kicad_prl" not in names
    assert "demo.step" not in names
    assert "demo.ibom.html" not in names
    assert "demo-bak" not in names
    assert not any(n.startswith("production/") for n in names)
    assert not any(n.startswith(".git/") for n in names)


def test_package_does_not_emit_source_readme(packager: SourcePackager, tmp_path: Path) -> None:
    """v1 source.zip explicitly does NOT contain a SOURCE_README.md manifest."""
    project = tmp_path / "demo"
    _make_project(project)
    output = tmp_path / "out.source.zip"
    packager.package(project_dir=project, output=output, title="demo", rev="1.0")
    with zipfile.ZipFile(output) as zf:
        assert "SOURCE_README.md" not in zf.namelist()


# ----- journal + atomicity -----


def test_package_registers_with_change_journal(packager: SourcePackager, tmp_path: Path) -> None:
    """The final source.zip is registered via :meth:`ChangeJournal.will_create`."""
    site_repo = tmp_path / "site"
    site_repo.mkdir()
    project = site_repo / "project"
    _make_project(project)
    output = site_repo / "demo-1.0.source.zip"
    with ChangeJournal(site_repo) as journal:
        packager.package(
            project_dir=project, output=output, title="demo", rev="1.0", journal=journal
        )
        assert output in set(journal.all_paths())
