"""Unit tests for :mod:`kproj.common.kicad_libraries`.

Validates that :func:`enumerate_libraries`:

- Tags ``${KIPRJMOD}``-rooted lib-table URIs as ``internal``.
- Tags ``${KIPRJMOD}/../...`` (escaping) URIs and absolute /
  ``${KISYSMOD}`` / URL URIs as ``external``.
- Tags ``(lib_id "lib:name")`` references whose ``<lib>`` has no
  lib-table entry as ``ambiguous``.
- Lets a lib-table entry win over a bare ``(lib_id ...)`` reference
  for the same library name.
- Returns a stable-sorted, deduplicated tuple - reproducible for the
  same input.
"""

from __future__ import annotations

from pathlib import Path

from kproj.common.kicad_libraries import enumerate_libraries
from kproj.model.library_ref import LibraryRef


def _names_by_source(refs: tuple[LibraryRef, ...]) -> dict[str, str]:
    """Helper: collapse a ``tuple[LibraryRef, ...]`` to a ``{name: source}`` dict."""
    return {r.name: r.source for r in refs}


def test_empty_project_returns_empty_tuple(tmp_path: Path) -> None:
    """A directory with no lib-tables or KiCad files yields ``()``."""
    project = tmp_path / "empty"
    project.mkdir()
    assert enumerate_libraries(project) == ()


def test_missing_directory_returns_empty_tuple(tmp_path: Path) -> None:
    """A non-existent ``project_dir`` yields ``()`` (defensive)."""
    assert enumerate_libraries(tmp_path / "no-such") == ()


# ----- internal -----


def test_kiprjmod_local_fp_lib_table_entry_is_internal(tmp_path: Path) -> None:
    """``${KIPRJMOD}/local.pretty`` lib-table URI is classified internal."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "fp-lib-table").write_text(
        "(fp_lib_table\n"
        '  (lib (name "LocalLib")(type "KiCad")(uri "${KIPRJMOD}/local.pretty")'
        '(options "")(descr ""))\n'
        ")\n"
    )
    refs = enumerate_libraries(project)
    assert refs == (LibraryRef(name="LocalLib", source="internal"),)


def test_kiprjmod_local_sym_lib_table_entry_is_internal(tmp_path: Path) -> None:
    """``${KIPRJMOD}/foo.kicad_sym`` in sym-lib-table is classified internal."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "sym-lib-table").write_text(
        "(sym_lib_table\n"
        '  (lib (name "LocalSyms")(type "KiCad")(uri "${KIPRJMOD}/LocalSyms.kicad_sym")'
        '(options "")(descr ""))\n'
        ")\n"
    )
    assert enumerate_libraries(project) == (LibraryRef(name="LocalSyms", source="internal"),)


# ----- external -----


def test_kiprjmod_escape_fp_lib_table_entry_is_external(tmp_path: Path) -> None:
    """``${KIPRJMOD}/../shared.pretty`` (escapes the project) is external."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "fp-lib-table").write_text(
        "(fp_lib_table\n"
        '  (lib (name "SPCoast")(type "KiCad")(uri "${KIPRJMOD}/../../shared/SPCoast.pretty")'
        '(options "")(descr ""))\n'
        ")\n"
    )
    assert enumerate_libraries(project) == (LibraryRef(name="SPCoast", source="external"),)


def test_absolute_path_lib_table_entry_is_external(tmp_path: Path) -> None:
    """An absolute-path URI in sym-lib-table is external."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "sym-lib-table").write_text(
        "(sym_lib_table\n"
        '  (lib (name "BundledSyms")(type "KiCad")(uri "/usr/share/kicad/syms")'
        '(options "")(descr ""))\n'
        ")\n"
    )
    assert enumerate_libraries(project) == (LibraryRef(name="BundledSyms", source="external"),)


def test_kisysmod_lib_table_entry_is_external(tmp_path: Path) -> None:
    """A ``${KISYSMOD}``-rooted URI is external (KiCad install context)."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "fp-lib-table").write_text(
        "(fp_lib_table\n"
        '  (lib (name "KiCadStock")(type "KiCad")(uri "${KISYSMOD}/Resistor_SMD.pretty")'
        '(options "")(descr ""))\n'
        ")\n"
    )
    assert enumerate_libraries(project) == (LibraryRef(name="KiCadStock", source="external"),)


# ----- ambiguous -----


def test_lib_id_ref_without_lib_table_entry_is_ambiguous(tmp_path: Path) -> None:
    """A ``(lib_id "lib:name")`` ref with no matching lib-table entry is ambiguous."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "demo.kicad_sch").write_text(
        '(kicad_sch (lib_id "MysteryLib:R_0805") (uuid "deadbeef"))\n'
    )
    assert enumerate_libraries(project) == (LibraryRef(name="MysteryLib", source="ambiguous"),)


def test_footprint_ref_without_lib_table_entry_is_ambiguous(tmp_path: Path) -> None:
    """A ``(footprint "lib:name")`` ref in a PCB with no lib-table is ambiguous."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "demo.kicad_pcb").write_text(
        '(kicad_pcb (footprint "Resistor_SMD:R_0805_2012Metric") (uuid "feed"))\n'
    )
    assert enumerate_libraries(project) == (LibraryRef(name="Resistor_SMD", source="ambiguous"),)


# ----- precedence: lib-table wins over lib_id ref -----


def test_lib_table_entry_wins_over_lib_id_ref(tmp_path: Path) -> None:
    """When the same lib name appears in lib-table and a lib_id ref, lib-table classifies."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "fp-lib-table").write_text(
        "(fp_lib_table\n"
        '  (lib (name "SPCoast")(type "KiCad")(uri "${KIPRJMOD}/../shared/SPCoast.pretty")'
        '(options "")(descr ""))\n'
        ")\n"
    )
    (project / "demo.kicad_sch").write_text('(kicad_sch (lib_id "SPCoast:R_0805"))\n')
    refs = enumerate_libraries(project)
    assert _names_by_source(refs) == {"SPCoast": "external"}


def test_internal_lib_table_entry_wins_over_lib_id_ref(tmp_path: Path) -> None:
    """A project-local lib-table entry tags the lib internal even when also referenced."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "fp-lib-table").write_text(
        "(fp_lib_table\n"
        '  (lib (name "LocalLib")(type "KiCad")(uri "${KIPRJMOD}/local.pretty")'
        '(options "")(descr ""))\n'
        ")\n"
    )
    (project / "demo.kicad_pcb").write_text(
        '(kicad_pcb (footprint "LocalLib:R_0805_2012Metric"))\n'
    )
    refs = enumerate_libraries(project)
    assert _names_by_source(refs) == {"LocalLib": "internal"}


# ----- merging across all three sources -----


def test_combined_sources_yield_a_three_bucket_set(tmp_path: Path) -> None:
    """A project with internal + external + ambiguous libs surfaces all three."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "fp-lib-table").write_text(
        "(fp_lib_table\n"
        '  (lib (name "LocalLib")(type "KiCad")(uri "${KIPRJMOD}/local.pretty")'
        '(options "")(descr ""))\n'
        '  (lib (name "SPCoast")(type "KiCad")(uri "${KIPRJMOD}/../shared/SPCoast.pretty")'
        '(options "")(descr ""))\n'
        ")\n"
    )
    (project / "demo.kicad_sch").write_text('(kicad_sch (lib_id "MysteryLib:R"))\n')
    refs = enumerate_libraries(project)
    assert _names_by_source(refs) == {
        "LocalLib": "internal",
        "MysteryLib": "ambiguous",
        "SPCoast": "external",
    }


def test_result_is_stable_sorted_by_name(tmp_path: Path) -> None:
    """Output is alphabetically stable-sorted by ``LibraryRef.name``."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "demo.kicad_sch").write_text(
        '(kicad_sch (lib_id "ZetaLib:R") (lib_id "AlphaLib:R") (lib_id "MidLib:R"))\n'
    )
    refs = enumerate_libraries(project)
    assert [r.name for r in refs] == ["AlphaLib", "MidLib", "ZetaLib"]
    # All three are ambiguous (no lib-table entry).
    assert {r.source for r in refs} == {"ambiguous"}


def test_result_is_reproducible_across_runs(tmp_path: Path) -> None:
    """Repeated invocations against the same project return identical tuples."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "fp-lib-table").write_text(
        "(fp_lib_table\n"
        '  (lib (name "B")(type "KiCad")(uri "/abs/path"))\n'
        '  (lib (name "A")(type "KiCad")(uri "/abs/path"))\n'
        ")\n"
    )
    assert enumerate_libraries(project) == enumerate_libraries(project)


def test_kicad_sym_file_is_scanned(tmp_path: Path) -> None:
    """``.kicad_sym`` files also contribute ``(lib_id ...)`` references."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "demo.kicad_sym").write_text('(kicad_symbol_lib (lib_id "Embedded:R_0805"))\n')
    refs = enumerate_libraries(project)
    assert refs == (LibraryRef(name="Embedded", source="ambiguous"),)
