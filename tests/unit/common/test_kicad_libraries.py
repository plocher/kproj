"""Unit tests for :mod:`kproj.common.kicad_libraries`."""

from __future__ import annotations

from pathlib import Path

from kproj.common.kicad_libraries import enumerate_libraries
from kproj.model.library_ref import LibraryRef


def _make_project(tmp_path: Path, name: str = "demo") -> Path:
    """Create a minimal project-centric KiCad fixture."""
    project = tmp_path / name
    project.mkdir()
    (project / f"{name}.kicad_pro").write_text("{}\n")
    (project / f"{name}.kicad_sch").write_text("(kicad_sch)\n")
    (project / f"{name}.kicad_pcb").write_text("(kicad_pcb)\n")
    return project


def test_empty_project_returns_empty_tuple(tmp_path: Path) -> None:
    """A minimal project with no refs/tables yields ``()``."""
    project = _make_project(tmp_path)
    assert enumerate_libraries(project) == ()


def test_missing_directory_returns_empty_tuple(tmp_path: Path) -> None:
    """A non-existent project dir yields ``()``."""
    assert enumerate_libraries(tmp_path / "no-such") == ()


def test_requires_single_kicad_pro_file(tmp_path: Path) -> None:
    """Ambiguous project roots (multiple ``*.kicad_pro``) are ignored."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "a.kicad_pro").write_text("{}\n")
    (project / "b.kicad_pro").write_text("{}\n")
    assert enumerate_libraries(project) == ()


def test_symbol_and_footprint_are_distinct_entries_even_with_same_name(tmp_path: Path) -> None:
    """Same lib name in symbol+footprint contexts yields two refs."""
    project = _make_project(tmp_path)
    (project / "demo.kicad_sch").write_text('(kicad_sch (lib_id "Shared:Conn_01x02"))\n')
    (project / "demo.kicad_pcb").write_text(
        '(kicad_pcb (footprint "Shared:PinHeader_1x02_P2.54mm_Vertical" (layer "F.Cu")))\n'
    )
    assert enumerate_libraries(project) == (
        LibraryRef(name="Shared", source="ambiguous", kind="footprint", distribution="unknown"),
        LibraryRef(name="Shared", source="ambiguous", kind="symbol", distribution="unknown"),
    )


def test_project_local_table_entries_are_internal_and_added(tmp_path: Path) -> None:
    """``${KIPRJMOD}`` table URIs are internal and added."""
    project = _make_project(tmp_path)
    (project / "sym-lib-table").write_text(
        '(sym_lib_table (lib (name "LocalSym")(type "KiCad")(uri "${KIPRJMOD}/Local.kicad_sym")))\n'
    )
    (project / "fp-lib-table").write_text(
        '(fp_lib_table (lib (name "LocalFp")(type "KiCad")(uri "${KIPRJMOD}/Local.pretty")))\n'
    )
    assert enumerate_libraries(project) == (
        LibraryRef(name="LocalFp", source="internal", kind="footprint", distribution="added"),
        LibraryRef(name="LocalSym", source="internal", kind="symbol", distribution="added"),
    )


def test_kicad_distribution_detected_from_standard_env_uris(tmp_path: Path) -> None:
    """Stock KiCad env vars are tagged ``distribution='kicad'``."""
    project = _make_project(tmp_path)
    (project / "sym-lib-table").write_text(
        '(sym_lib_table (lib (name "power")(type "KiCad")(uri "${KICAD_SYMBOL_DIR}/power.kicad_sym")))\n'
    )
    (project / "fp-lib-table").write_text(
        '(fp_lib_table (lib (name "Connector_PinHeader_2.54mm")(type "KiCad")(uri "${KISYSMOD}/Connector_PinHeader_2.54mm.pretty")))\n'
    )
    assert enumerate_libraries(project) == (
        LibraryRef(
            name="Connector_PinHeader_2.54mm",
            source="external",
            kind="footprint",
            distribution="kicad",
        ),
        LibraryRef(name="power", source="external", kind="symbol", distribution="kicad"),
    )


def test_ambiguous_power_symbol_defaults_to_kicad_distribution(tmp_path: Path) -> None:
    """Without tables, ``power:*`` remains ambiguous but is tagged stock KiCad."""
    project = _make_project(tmp_path)
    (project / "demo.kicad_sch").write_text('(kicad_sch (lib_id "power:+5V"))\n')
    assert enumerate_libraries(project) == (
        LibraryRef(name="power", source="ambiguous", kind="symbol", distribution="kicad"),
    )


def test_footprint_block_multiline_is_detected(tmp_path: Path) -> None:
    """PCB-style multiline footprint blocks are detected."""
    project = _make_project(tmp_path)
    (project / "demo.kicad_pcb").write_text(
        "(kicad_pcb\n"
        '  (footprint "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"\n'
        '    (layer "F.Cu")\n'
        "  )\n"
        ")\n"
    )
    assert enumerate_libraries(project) == (
        LibraryRef(
            name="Connector_PinHeader_2.54mm",
            source="ambiguous",
            kind="footprint",
            distribution="unknown",
        ),
    )


def test_hierarchical_sheet_tree_is_walked(tmp_path: Path) -> None:
    """Child sheets referenced by ``(sheetfile ...)`` are scanned."""
    project = _make_project(tmp_path)
    (project / "child.kicad_sch").write_text('(kicad_sch (lib_id "ChildLib:R"))\n')
    (project / "demo.kicad_sch").write_text(
        '(kicad_sch (sheet (property "Sheetname" "child") (sheetfile "child.kicad_sch")))\n'
    )
    assert enumerate_libraries(project) == (
        LibraryRef(name="ChildLib", source="ambiguous", kind="symbol", distribution="unknown"),
    )


def test_history_backup_and_production_are_ignored(tmp_path: Path) -> None:
    """Refs only under ignored paths do not leak into results."""
    project = _make_project(tmp_path)
    history = project / ".history"
    history.mkdir()
    (history / "demo.kicad_sch").write_text('(kicad_sch (lib_id "HistoryOnly:R"))\n')
    backups = project / "demo-backups"
    backups.mkdir()
    (backups / "old.kicad_sch").write_text('(kicad_sch (lib_id "BackupOnly:R"))\n')
    production = project / "production"
    production.mkdir()
    (production / "snapshot.kicad_sch").write_text('(kicad_sch (lib_id "ProdOnly:R"))\n')
    assert enumerate_libraries(project) == ()


def test_result_is_reproducible_across_runs(tmp_path: Path) -> None:
    """Repeated invocations against the same project are stable."""
    project = _make_project(tmp_path)
    (project / "demo.kicad_sch").write_text(
        '(kicad_sch (lib_id "Zeta:R") (lib_id "Alpha:R") (lib_id "Mid:R"))\n'
    )
    assert enumerate_libraries(project) == enumerate_libraries(project)
