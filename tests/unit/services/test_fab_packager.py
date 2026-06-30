"""Unit tests for :mod:`kproj.services.fab_packager`.

Validates the contract per ``docs/DESIGN.md`` § *FabPackager* + ADR 0003
(jBOM separation):

- Discover the gerber pack as ``<production_dir>/<title>_<rev>.zip``
  when title + rev are supplied. Fall back to the single ``*.zip`` if
  one is present (warn if zero or more than one).
- Read ``bom.csv`` + ``pos.csv`` from ``production_dir`` and add them
  alongside the discovered gerber zip (renamed to ``gerbers.zip``) in
  the produced ``<P>-<R>.fab.zip``.
- ``ExportResult.skipped=True`` when ``production_dir`` is missing or
  empty.
- Warn when production outputs are older than the source PCB's mtime.
"""

from __future__ import annotations

import os
import time
import zipfile
from pathlib import Path

import pytest

from kproj.model.export_result import ExportResult
from kproj.model.severity import Severity
from kproj.services.change_journal import ChangeJournal
from kproj.services.fab_packager import FabPackager
from kproj.services.zip_archiver import ZipArchiver


def _write_production(
    production_dir: Path,
    *,
    title: str = "demo",
    rev: str = "1.0",
    gerber_name: str | None = None,
) -> Path:
    """Create a minimal jBOM-style production directory.

    Returns the path of the produced gerber zip.
    """
    production_dir.mkdir(parents=True, exist_ok=True)
    (production_dir / "bom.csv").write_text("Ref,Value\nR1,10k\n")
    (production_dir / "pos.csv").write_text("Ref,X,Y\nR1,0,0\n")
    gerber_zip = production_dir / (gerber_name or f"{title}_{rev}.zip")
    with zipfile.ZipFile(gerber_zip, "w") as zf:
        zf.writestr("F.Cu.gbr", "G04 fake gerber*\n")
    return gerber_zip


@pytest.fixture
def packager() -> FabPackager:
    """Return a :class:`FabPackager` wired to a fresh :class:`ZipArchiver`."""
    return FabPackager(zip_archiver=ZipArchiver())


# ----- happy path -----


def test_package_assembles_fab_zip_with_three_entries(
    packager: FabPackager, tmp_path: Path
) -> None:
    """``package()`` emits a zip containing ``bom.csv``, ``pos.csv``, ``gerbers.zip``."""
    production = tmp_path / "production"
    _write_production(production)
    output = tmp_path / "demo-1.0.fab.zip"

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")

    result = packager.package(
        production_dir=production,
        output=output,
        title="demo",
        rev="1.0",
        pcb_path=pcb,
    )

    assert isinstance(result, ExportResult)
    assert result.skipped is False
    assert result.path == output
    assert output.exists()
    with zipfile.ZipFile(output) as zf:
        assert sorted(zf.namelist()) == ["bom.csv", "gerbers.zip", "pos.csv"]
        # Gerber zip content is preserved under normalized name.
        with zf.open("gerbers.zip") as g:
            inner_bytes = g.read()
    # Validate the gerber-zip is a real zip carrying our fake gerber entry.
    inner_buf = output.parent / "inner.zip"
    inner_buf.write_bytes(inner_bytes)
    with zipfile.ZipFile(inner_buf) as g:
        assert g.namelist() == ["F.Cu.gbr"]


def test_package_normalizes_gerber_zip_entry_name_regardless_of_source_filename(
    packager: FabPackager, tmp_path: Path
) -> None:
    """The gerber pack is renamed to ``gerbers.zip`` inside the fab.zip."""
    production = tmp_path / "production"
    _write_production(production, gerber_name="demo_1.0.zip")
    output = tmp_path / "out.fab.zip"
    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")

    packager.package(
        production_dir=production,
        output=output,
        title="demo",
        rev="1.0",
        pcb_path=pcb,
    )
    with zipfile.ZipFile(output) as zf:
        assert "gerbers.zip" in zf.namelist()


# ----- discovery rules -----


def test_package_falls_back_to_single_zip_when_titled_not_present(
    packager: FabPackager, tmp_path: Path
) -> None:
    """When ``<title>_<rev>.zip`` is missing but exactly one ``*.zip`` exists, use it."""
    production = tmp_path / "production"
    _write_production(production, gerber_name="something_else.zip")
    output = tmp_path / "out.fab.zip"
    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")

    result = packager.package(
        production_dir=production,
        output=output,
        title="demo",
        rev="1.0",
        pcb_path=pcb,
    )
    assert result.skipped is False
    with zipfile.ZipFile(output) as zf:
        assert "gerbers.zip" in zf.namelist()


def test_package_warns_on_ambiguous_multiple_zips(packager: FabPackager, tmp_path: Path) -> None:
    """Multiple non-canonical ``*.zip`` files emits a warning Finding."""
    production = tmp_path / "production"
    _write_production(production, gerber_name="alpha.zip")
    # Add a second zip without the canonical title_rev name.
    with zipfile.ZipFile(production / "beta.zip", "w") as zf:
        zf.writestr("F.Cu.gbr", "extra*\n")
    output = tmp_path / "out.fab.zip"
    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")

    result = packager.package(
        production_dir=production,
        output=output,
        title="demo",
        rev="1.0",
        pcb_path=pcb,
    )
    fields = {f.field for f in result.diagnostics}
    assert "fab_gerber_ambiguous" in fields
    assert result.skipped is True  # cannot safely pick one
    assert result.path is None


# ----- skipped semantics -----


def test_package_skipped_when_production_missing(packager: FabPackager, tmp_path: Path) -> None:
    """A missing ``production_dir`` produces ``skipped=True`` + warning."""
    output = tmp_path / "out.fab.zip"
    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")

    result = packager.package(
        production_dir=tmp_path / "no-such",
        output=output,
        title="demo",
        rev="1.0",
        pcb_path=pcb,
    )
    assert result.skipped is True
    assert result.path is None
    assert not output.exists()
    severities = {f.severity for f in result.diagnostics}
    fields = {f.field for f in result.diagnostics}
    assert Severity.WARNING in severities
    assert "production_missing" in fields


def test_package_skipped_when_production_empty(packager: FabPackager, tmp_path: Path) -> None:
    """An empty ``production_dir`` also produces ``skipped=True`` + warning."""
    production = tmp_path / "production"
    production.mkdir()
    output = tmp_path / "out.fab.zip"
    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")

    result = packager.package(
        production_dir=production,
        output=output,
        title="demo",
        rev="1.0",
        pcb_path=pcb,
    )
    assert result.skipped is True
    assert "production_missing" in {f.field for f in result.diagnostics}


def test_package_skipped_when_bom_or_pos_missing(packager: FabPackager, tmp_path: Path) -> None:
    """Missing ``bom.csv`` or ``pos.csv`` produces a warning Finding."""
    production = tmp_path / "production"
    production.mkdir()
    # Only the gerber zip is present.
    with zipfile.ZipFile(production / "demo_1.0.zip", "w") as zf:
        zf.writestr("F.Cu.gbr", "*\n")
    output = tmp_path / "out.fab.zip"
    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")

    result = packager.package(
        production_dir=production,
        output=output,
        title="demo",
        rev="1.0",
        pcb_path=pcb,
    )
    assert result.skipped is True
    fields = {f.field for f in result.diagnostics}
    # bom.csv missing OR pos.csv missing both surface as warnings; either field name acceptable.
    assert {"production_missing"} & fields or {"production_incomplete"} & fields


# ----- staleness warning -----


def test_package_warns_when_production_older_than_pcb(
    packager: FabPackager, tmp_path: Path
) -> None:
    """A production whose youngest file is older than the PCB emits a staleness warning."""
    production = tmp_path / "production"
    _write_production(production)
    # Backdate every file in production.
    old = time.time() - 60 * 60 * 24
    for p in production.iterdir():
        os.utime(p, (old, old))
    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")  # fresh now

    output = tmp_path / "out.fab.zip"
    result = packager.package(
        production_dir=production,
        output=output,
        title="demo",
        rev="1.0",
        pcb_path=pcb,
    )
    assert result.skipped is False
    fields = {f.field for f in result.diagnostics}
    assert "production_stale" in fields


# ----- journal integration -----


def test_package_registers_output_with_change_journal(
    packager: FabPackager, tmp_path: Path
) -> None:
    """The final fab.zip path is registered via :meth:`ChangeJournal.will_create`."""
    site_repo = tmp_path / "site"
    site_repo.mkdir()
    production = site_repo / "production"
    _write_production(production)
    pcb = site_repo / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = site_repo / "demo-1.0.fab.zip"

    with ChangeJournal(site_repo) as journal:
        packager.package(
            production_dir=production,
            output=output,
            title="demo",
            rev="1.0",
            pcb_path=pcb,
            journal=journal,
        )
        assert output in set(journal.all_paths())
