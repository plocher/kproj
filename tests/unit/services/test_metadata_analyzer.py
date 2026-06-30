"""Unit tests for :mod:`kproj.services.metadata_analyzer`.

Exercises each of the 14 rules in ``docs/DESIGN.md`` § *Audit
heuristic list* against synthetic :class:`ProjectInfo` instances and a
``tmp_path``-rooted project directory.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pytest

from kproj.model.finding import Finding
from kproj.model.project_info import ProjectInfo, Status
from kproj.model.raw_title_block import RawTitleBlock
from kproj.model.severity import Severity
from kproj.services.metadata_analyzer import MetadataAnalyzer


def _info(
    *,
    project: str = "demo",
    title: str = "Demo Board",
    company: str = "ACME",
    design_rev: str = "3.0",
    board_rev: str = "3.0B",
    date: str = "2026.04",
    designer: str = "Alice Designer",
    tagline: str = "tagline",
    overview: str = "overview text",
    status: Status = Status.ACTIVE,
    replaced_by_target: str | None = None,
    raw_sch: RawTitleBlock | None = None,
    raw_pcb: RawTitleBlock | None = None,
) -> ProjectInfo:
    """Construct a :class:`ProjectInfo` with sensible defaults."""
    return ProjectInfo(
        project=project,
        title=title,
        company=company,
        design_rev=design_rev,
        board_rev=board_rev,
        date=date,
        designer=designer,
        tagline=tagline,
        overview=overview,
        status=status,
        replaced_by_target=replaced_by_target,
        raw_sch=raw_sch
        or RawTitleBlock(
            title=title,
            company=company,
            revision=design_rev,
            comments={
                1: designer,
                9: status.value if status is not Status.REPLACED_BY else "replaced-by:x",
            },
            present=True,
        ),
        raw_pcb=raw_pcb
        or RawTitleBlock(
            title=title,
            company=company,
            revision=board_rev,
            date=date,
            comments={1: designer},
            present=True,
        ),
    )


def _populated_project(project_dir: Path, project: str = "demo") -> Path:
    """Create a project_dir with adjacent SCH/PCB files so existence rules pass."""
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / f"{project}.kicad_sch").write_text("")
    (project_dir / f"{project}.kicad_pcb").write_text("")
    return project_dir


def _fields(findings: Iterable[Finding]) -> set[str]:
    return {f.field for f in findings}


def _of(findings: Iterable[Finding], field: str) -> list[Finding]:
    return [f for f in findings if f.field == field]


def _analyzer(projects_root: Path) -> MetadataAnalyzer:
    return MetadataAnalyzer(projects_root=projects_root)


def test_clean_project_yields_no_findings(tmp_path: Path) -> None:
    """A well-formed project produces only the production_missing warning."""
    project_dir = _populated_project(tmp_path / "demo")
    info = _info()
    result = _analyzer(tmp_path).analyze(info, project_dir)
    # `production/` does not exist for the synthetic fixture; the rest is clean.
    assert _fields(result.findings) == {"production_missing"}


# ----- rules 1 & 2: file existence -----


def test_kicad_sch_missing_emits_error(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    (project_dir / "demo.kicad_pcb").write_text("")
    result = _analyzer(tmp_path).analyze(_info(), project_dir)
    matches = _of(result.findings, "kicad_sch_missing")
    assert matches and matches[0].severity is Severity.ERROR


def test_kicad_pcb_missing_emits_error(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    (project_dir / "demo.kicad_sch").write_text("")
    result = _analyzer(tmp_path).analyze(_info(), project_dir)
    matches = _of(result.findings, "kicad_pcb_missing")
    assert matches and matches[0].severity is Severity.ERROR


# ----- rule 3: placeholder values -----


@pytest.mark.parametrize(
    "value",
    ["${TITLE}", "DATE", "Fab Date", "Designer Name", "Sheet Title Line 5"],
)
def test_placeholder_value_detected(tmp_path: Path, value: str) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    info = _info(title=value)
    result = _analyzer(tmp_path).analyze(info, project_dir)
    matches = _of(result.findings, "placeholder_value")
    assert matches and matches[0].severity is Severity.ERROR
    assert matches[0].value == value


def test_placeholder_value_ignores_legit_strings(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    info = _info(title="A real-looking title without placeholders")
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "placeholder_value" not in _fields(result.findings)


# ----- rules 4 & 5: comment9 -----


def test_comment9_missing_warning(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    raw_sch = RawTitleBlock(title="X", revision="1.0", comments={1: "Alice X"}, present=True)
    raw_pcb = RawTitleBlock(title="X", revision="1.0", comments={1: "Alice X"}, present=True)
    info = _info(raw_sch=raw_sch, raw_pcb=raw_pcb, design_rev="1.0", board_rev="1.0")
    result = _analyzer(tmp_path).analyze(info, project_dir)
    matches = _of(result.findings, "comment9_missing")
    assert matches and matches[0].severity is Severity.WARNING


def test_comment9_taxonomy_error_for_bad_value(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    raw_sch = RawTitleBlock(
        title="X",
        revision="1.0",
        comments={1: "Alice X", 9: "garbage-status"},
        present=True,
    )
    info = _info(raw_sch=raw_sch, design_rev="1.0", board_rev="1.0")
    result = _analyzer(tmp_path).analyze(info, project_dir)
    matches = _of(result.findings, "comment9_taxonomy")
    assert matches and matches[0].severity is Severity.ERROR


def test_comment9_replaced_by_passes_taxonomy(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    raw_sch = RawTitleBlock(
        title="X",
        revision="1.0",
        comments={1: "Alice X", 9: "replaced-by:Successor"},
        present=True,
    )
    raw_pcb = RawTitleBlock(title="X", revision="1.0", comments={1: "Alice X"}, present=True)
    info = _info(
        raw_sch=raw_sch,
        raw_pcb=raw_pcb,
        design_rev="1.0",
        board_rev="1.0",
        status=Status.REPLACED_BY,
        replaced_by_target="Successor",
    )
    # Create the successor dir so the replaced_by_target_missing rule stays silent.
    (tmp_path / "Successor").mkdir()
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "comment9_taxonomy" not in _fields(result.findings)


# ----- rules 6 & 7: title-block presence -----


def test_sch_titleblock_empty_warning(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    info = _info(raw_sch=RawTitleBlock(present=False))
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "sch_titleblock_empty" in _fields(result.findings)


def test_pcb_titleblock_empty_warning(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    info = _info(raw_pcb=RawTitleBlock(present=False))
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "pcb_titleblock_empty" in _fields(result.findings)


# ----- rule 8: sch_pcb_disagree -----


def test_sch_pcb_disagree_on_title_warning(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    raw_sch = RawTitleBlock(
        title="One",
        company="ACME",
        revision="3.0",
        comments={1: "Alice X", 9: "active"},
        present=True,
    )
    raw_pcb = RawTitleBlock(
        title="Other",
        company="ACME",
        revision="3.0B",
        date="2026.04",
        comments={1: "Alice X"},
        present=True,
    )
    info = _info(title="Other", raw_sch=raw_sch, raw_pcb=raw_pcb)
    result = _analyzer(tmp_path).analyze(info, project_dir)
    matches = _of(result.findings, "sch_pcb_disagree")
    assert matches and matches[0].location_hint == "title"


def test_sch_pcb_disagree_on_designer_warning(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    raw_sch = RawTitleBlock(
        title="X", revision="3.0", comments={1: "Alice X", 9: "active"}, present=True
    )
    raw_pcb = RawTitleBlock(
        title="X", revision="3.0B", date="2026.04", comments={1: "Bob Y"}, present=True
    )
    info = _info(designer="Alice X", raw_sch=raw_sch, raw_pcb=raw_pcb)
    result = _analyzer(tmp_path).analyze(info, project_dir)
    hints = {f.location_hint for f in _of(result.findings, "sch_pcb_disagree")}
    assert "comment1" in hints


# ----- rule 9 & 10: format checks -----


def test_date_format_warning(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    info = _info(date="04/2026")
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "date_format" in _fields(result.findings)


def test_designer_format_warning(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    info = _info(designer="alice")
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "designer_format" in _fields(result.findings)


def test_designer_format_accepts_two_capitalised_words(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    info = _info(designer="Alice Designer")
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "designer_format" not in _fields(result.findings)


# ----- rule 11: rev_relation -----


def test_rev_relation_passes_for_3_0_to_3_0B(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    info = _info(design_rev="3.0", board_rev="3.0B")
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "rev_relation" not in _fields(result.findings)


@pytest.mark.parametrize("board_rev", ["3.0.1", "3.0-beta", "3.1", "3.0b"])
def test_rev_relation_warns_on_non_uppercase_suffix(tmp_path: Path, board_rev: str) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    info = _info(design_rev="3.0", board_rev=board_rev)
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "rev_relation" in _fields(result.findings)


def test_rev_relation_passes_when_revs_equal(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    info = _info(design_rev="3.0", board_rev="3.0")
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "rev_relation" not in _fields(result.findings)


# ----- rule 12: replaced_by_target_missing -----


def test_replaced_by_target_missing_warning(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    info = _info(
        status=Status.REPLACED_BY,
        replaced_by_target="DoesNotExist",
        raw_sch=RawTitleBlock(
            title="Demo Board",
            revision="3.0",
            comments={1: "Alice Designer", 9: "replaced-by:DoesNotExist"},
            present=True,
        ),
    )
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "replaced_by_target_missing" in _fields(result.findings)


def test_replaced_by_target_present_no_finding(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    (tmp_path / "Successor").mkdir()
    info = _info(
        status=Status.REPLACED_BY,
        replaced_by_target="Successor",
        raw_sch=RawTitleBlock(
            title="Demo Board",
            revision="3.0",
            comments={1: "Alice Designer", 9: "replaced-by:Successor"},
            present=True,
        ),
    )
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "replaced_by_target_missing" not in _fields(result.findings)


# ----- rules 13 & 14: production_* -----


def test_production_missing_warning_when_dir_absent(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    info = _info()
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "production_missing" in _fields(result.findings)


def test_production_missing_warning_when_dir_empty(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    (project_dir / "production").mkdir()
    info = _info()
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "production_missing" in _fields(result.findings)


def test_production_stale_warning(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    production = project_dir / "production"
    production.mkdir()
    # Create a stale zip with mtime older than the PCB.
    stale = production / "gerbers.zip"
    stale.write_bytes(b"PK")
    pcb = project_dir / "demo.kicad_pcb"
    # Touch the PCB to bump its mtime forward.
    import os

    os.utime(stale, (1000, 1000))
    os.utime(pcb, (2000, 2000))
    info = _info()
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "production_stale" in _fields(result.findings)


def test_production_fresh_no_stale_finding(tmp_path: Path) -> None:
    project_dir = _populated_project(tmp_path / "demo")
    production = project_dir / "production"
    production.mkdir()
    fresh = production / "gerbers.zip"
    fresh.write_bytes(b"PK")
    pcb = project_dir / "demo.kicad_pcb"
    import os

    os.utime(pcb, (1000, 1000))
    os.utime(fresh, (2000, 2000))
    info = _info()
    result = _analyzer(tmp_path).analyze(info, project_dir)
    assert "production_stale" not in _fields(result.findings)
