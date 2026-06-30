"""Unit tests for :mod:`kproj.services.kicad_project_reader` (wave-2).

Wave-2 swaps the wave-1 self-contained resolver for a jBOM thin-wrap
plus the title-block read sub-slice.  These tests cover both halves:

- ``resolve()`` against directory / project-file / schematic-file /
  basename inputs, plus the SPCoast basename-root fallback.
- ``read()`` against fixture projects asserting per-field metadata
  precedence per ``docs/DESIGN.md`` § *Metadata precedence*.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS_ROOT = Path(__file__).resolve().parents[2]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from _kicad_fixtures import (  # noqa: E402 - path setup above
    TitleBlockSpec,
    make_minimal_project,
)
from kproj.model.project_info import Status  # noqa: E402
from kproj.model.severity import Severity  # noqa: E402
from kproj.services.kicad_project_reader import (  # noqa: E402
    KicadProjectReader,
    ProjectResolutionError,
)


def _reader(projects_root: Path) -> KicadProjectReader:
    """Construct a reader pinned to *projects_root* for basename lookup."""
    return KicadProjectReader(projects_root=projects_root)


# ----- resolve() -----


def test_resolve_directory_input(tmp_path: Path) -> None:
    """A directory path resolves to the project inside."""
    proj_dir = make_minimal_project(tmp_path / "demo", "demo")
    resolved = _reader(tmp_path).resolve(proj_dir)
    assert resolved.project_dir == proj_dir
    assert resolved.project_file == proj_dir / "demo.kicad_pro"
    assert resolved.pcb_file == proj_dir / "demo.kicad_pcb"
    assert resolved.root_schematic == proj_dir / "demo.kicad_sch"
    assert resolved.basename == "demo"
    assert resolved.jbom_resolved is not None


def test_resolve_project_file_input(tmp_path: Path) -> None:
    """A path to ``.kicad_pro`` resolves to its enclosing project."""
    proj_dir = make_minimal_project(tmp_path / "x", "demo")
    resolved = _reader(tmp_path).resolve(proj_dir / "demo.kicad_pro")
    assert resolved.project_dir == proj_dir


def test_resolve_sch_file_input(tmp_path: Path) -> None:
    """A path to ``.kicad_sch`` resolves to its enclosing project."""
    proj_dir = make_minimal_project(tmp_path / "x", "demo")
    resolved = _reader(tmp_path).resolve(proj_dir / "demo.kicad_sch")
    assert resolved.project_dir == proj_dir


def test_resolve_basename_lookup(tmp_path: Path) -> None:
    """A bare basename resolves under the configured projects root."""
    projects_root = tmp_path / "root"
    proj_dir = projects_root / "demo"
    make_minimal_project(proj_dir, "demo")
    resolved = _reader(projects_root).resolve("demo")
    assert resolved.project_dir == proj_dir


def test_resolve_dot_means_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``"."`` resolves to the current working directory."""
    proj_dir = make_minimal_project(tmp_path / "here", "demo")
    monkeypatch.chdir(proj_dir)
    resolved = _reader(tmp_path).resolve(".")
    assert resolved.project_dir == proj_dir


def test_resolve_rejects_missing_project_file(tmp_path: Path) -> None:
    """An empty directory raises :class:`ProjectResolutionError`."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ProjectResolutionError):
        _reader(tmp_path).resolve(empty)


def test_resolve_rejects_unresolvable_input(tmp_path: Path) -> None:
    """A wholly unresolvable input raises ProjectResolutionError."""
    with pytest.raises(ProjectResolutionError):
        _reader(tmp_path).resolve("/no/such/path/here")


def test_resolve_includes_hierarchical_schematics(tmp_path: Path) -> None:
    """The root schematic always appears in ``hierarchical_schematics``."""
    proj_dir = make_minimal_project(tmp_path / "x", "demo")
    resolved = _reader(tmp_path).resolve(proj_dir)
    assert resolved.root_schematic in resolved.hierarchical_schematics


def test_resolve_exposes_text_variables(tmp_path: Path) -> None:
    """jBOM 7.3.0 ``text_variables`` are surfaced on :class:`ResolvedProject`."""
    project_json = '{\n  "text_variables": {\n    "FOO": "bar",\n    "VERSION": "1.0"\n  }\n}\n'
    proj_dir = make_minimal_project(tmp_path / "x", "demo", project_json=project_json)
    resolved = _reader(tmp_path).resolve(proj_dir)
    assert dict(resolved.text_variables) == {"FOO": "bar", "VERSION": "1.0"}


def test_resolve_empty_text_variables_when_pro_lacks_field(tmp_path: Path) -> None:
    """A project without ``text_variables`` JSON keys exposes an empty mapping."""
    proj_dir = make_minimal_project(tmp_path / "x", "demo")
    resolved = _reader(tmp_path).resolve(proj_dir)
    assert dict(resolved.text_variables) == {}


# ----- read(): per-field metadata precedence -----


def _populated_project(tmp_path: Path) -> Path:
    """A common fixture: SCH + PCB title-blocks populated 'normally'.

    SCH carries the design rev + the SPCoast-convention comment fields;
    PCB carries the board rev (``<design>B``) + fab date.
    """
    return make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(
            title="Hello Board",
            company="ACME",
            revision="3.0",
            date="2026.04",
            comments={
                1: "Alice Designer",
                2: "Tagline goes here",
                3: "Continuation of overview",
                9: "active",
            },
        ),
        pcb_title_block=TitleBlockSpec(
            title="Hello Board",
            company="ACME",
            revision="3.0B",
            date="2026.05",
            comments={1: "Alice Designer"},
        ),
    )


def test_read_pcb_canonical_fields(tmp_path: Path) -> None:
    """PCB-canonical fields win when populated on both sides."""
    proj_dir = _populated_project(tmp_path)
    reader = _reader(tmp_path)
    resolved = reader.resolve(proj_dir)
    info, findings = reader.read(resolved)
    assert info.title == "Hello Board"
    assert info.company == "ACME"
    assert info.board_rev == "3.0B"
    assert info.design_rev == "3.0"
    assert info.date == "2026.05"  # PCB date wins
    assert info.fab_date == "2026.05"
    assert info.fabricated is True
    assert findings == ()


def test_read_falls_back_to_sch_when_pcb_blank(tmp_path: Path) -> None:
    """Empty PCB fields fall through to SCH per the locked precedence."""
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(
            title="Hello",
            company="ACME",
            revision="2.0",
            date="2026.03",
            comments={1: "Alice"},
        ),
        pcb_title_block=TitleBlockSpec(comments={1: "Alice"}),
    )
    reader = _reader(tmp_path)
    info, _ = reader.read(reader.resolve(proj_dir))
    assert info.title == "Hello"
    assert info.company == "ACME"
    assert info.board_rev == "2.0"
    assert info.design_rev == "2.0"
    assert info.date == "2026.03"
    assert info.fabricated is False  # PCB lacks date


def test_read_sch_canonical_comments(tmp_path: Path) -> None:
    """COMMENT2/3/9 are SCH-canonical even when PCB also has them."""
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(
            title="X",
            revision="1.0",
            comments={2: "SCH tagline", 3: "SCH overview", 9: "experimental"},
        ),
        pcb_title_block=TitleBlockSpec(
            title="X",
            revision="1.0",
            comments={2: "PCB tagline", 3: "PCB overview", 9: "active"},
        ),
    )
    reader = _reader(tmp_path)
    info, _ = reader.read(reader.resolve(proj_dir))
    assert info.tagline == "SCH tagline"
    assert info.overview == "SCH tagline SCH overview"
    assert info.status is Status.EXPERIMENTAL


def test_read_designer_first_non_empty(tmp_path: Path) -> None:
    """COMMENT1 (designer) takes the first non-empty source (SCH first)."""
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(revision="1.0"),  # no COMMENT1
        pcb_title_block=TitleBlockSpec(revision="1.0", comments={1: "Only-on-PCB Designer"}),
    )
    reader = _reader(tmp_path)
    info, _ = reader.read(reader.resolve(proj_dir))
    assert info.designer == "Only-on-PCB Designer"


def test_read_status_defaults_to_active_when_comment9_missing(tmp_path: Path) -> None:
    """Missing COMMENT9 defaults to :attr:`Status.ACTIVE` (warning is audit's job)."""
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(revision="1.0"),
        pcb_title_block=TitleBlockSpec(revision="1.0"),
    )
    reader = _reader(tmp_path)
    info, _ = reader.read(reader.resolve(proj_dir))
    assert info.status is Status.ACTIVE
    assert info.replaced_by_target is None


def test_read_status_private_round_trip(tmp_path: Path) -> None:
    """``${COMMENT9} = private`` parses to :attr:`Status.PRIVATE`."""
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(revision="1.0", comments={9: "private"}),
        pcb_title_block=TitleBlockSpec(revision="1.0"),
    )
    reader = _reader(tmp_path)
    info, _ = reader.read(reader.resolve(proj_dir))
    assert info.status is Status.PRIVATE


def test_read_status_replaced_by_extracts_target(tmp_path: Path) -> None:
    """``replaced-by:Successor`` parses to :attr:`Status.REPLACED_BY` + target."""
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(revision="1.0", comments={9: "replaced-by:NewBoard"}),
        pcb_title_block=TitleBlockSpec(revision="1.0"),
    )
    reader = _reader(tmp_path)
    info, _ = reader.read(reader.resolve(proj_dir))
    assert info.status is Status.REPLACED_BY
    assert info.replaced_by_target == "NewBoard"


def test_read_status_unknown_defaults_to_active(tmp_path: Path) -> None:
    """An unknown COMMENT9 taxonomy value falls through to ACTIVE."""
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(revision="1.0", comments={9: "in-progress"}),
        pcb_title_block=TitleBlockSpec(revision="1.0"),
    )
    reader = _reader(tmp_path)
    info, _ = reader.read(reader.resolve(proj_dir))
    assert info.status is Status.ACTIVE


def test_read_surfaces_titleblock_unreadable_warning(tmp_path: Path) -> None:
    """A malformed file surfaces as a warning :class:`Finding`."""
    proj_dir = make_minimal_project(tmp_path / "demo", "demo")
    # Corrupt the schematic: unbalanced parens are unparsable.
    (proj_dir / "demo.kicad_sch").write_text("(((\n", encoding="utf-8")
    reader = _reader(tmp_path)
    resolved = reader.resolve(proj_dir)
    _, findings = reader.read(resolved)
    assert any(
        f.severity is Severity.WARNING and f.field == "schematic_titleblock_unreadable"
        for f in findings
    )
