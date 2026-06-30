"""Unit tests for :meth:`PublishWorkflow.build_publication`.

Validates that DESIGN step 8 (build Publication) threads the per-project
library enumeration onto :attr:`Publication.libraries`, with each entry
tagged ``internal`` / ``external`` / ``ambiguous`` per
:func:`kproj.common.kicad_libraries.enumerate_libraries`.

The SitePublisher consumer of the field lands with kproj#4; these tests
pin the workflow-side population contract today.
"""

from __future__ import annotations

import sys
from pathlib import Path

from kproj.application.publish_workflow import PublishWorkflow
from kproj.model.analysis_info import AnalysisInfo
from kproj.model.library_ref import LibraryRef
from kproj.model.project_info import ProjectInfo, Status
from kproj.model.publication import Publication
from kproj.model.resolved_project import ResolvedProject

_TESTS_ROOT = Path(__file__).resolve().parents[2]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from _kicad_fixtures import make_minimal_project  # noqa: E402 - path setup above


def _project_info(basename: str = "demo") -> ProjectInfo:
    """Return a populated :class:`ProjectInfo` for fixture use."""
    return ProjectInfo(
        project=basename,
        title=basename,
        company="MRCS",
        design_rev="1.0",
        board_rev="1.0",
        date="2026.06",
        designer="Alice Designer",
        tagline="t",
        overview="o",
        status=Status.ACTIVE,
    )


def _resolved(project_dir: Path, basename: str = "demo") -> ResolvedProject:
    """Build a :class:`ResolvedProject` referencing the fixture under *project_dir*."""
    return ResolvedProject(
        project_file=project_dir / f"{basename}.kicad_pro",
        project_dir=project_dir,
        pcb_file=project_dir / f"{basename}.kicad_pcb",
        root_schematic=project_dir / f"{basename}.kicad_sch",
        hierarchical_schematics=(project_dir / f"{basename}.kicad_sch",),
    )


def test_build_publication_returns_a_publication(tmp_path: Path) -> None:
    """``build_publication`` returns a :class:`Publication` instance."""
    project = make_minimal_project(tmp_path / "demo", "demo")
    publication = PublishWorkflow.build_publication(
        _resolved(project),
        _project_info(),
        AnalysisInfo(findings=()),
    )
    assert isinstance(publication, Publication)


def test_build_publication_populates_external_lib_from_fp_lib_table(tmp_path: Path) -> None:
    """An ``fp-lib-table`` entry escaping ``${KIPRJMOD}`` lands as external on Publication."""
    project = make_minimal_project(tmp_path / "demo", "demo")
    (project / "fp-lib-table").write_text(
        "(fp_lib_table\n"
        '  (lib (name "SPCoast")(type "KiCad")(uri "${KIPRJMOD}/../shared/SPCoast.pretty")'
        '(options "")(descr ""))\n'
        ")\n"
    )
    publication = PublishWorkflow.build_publication(
        _resolved(project),
        _project_info(),
        AnalysisInfo(findings=()),
    )
    assert publication.libraries == (LibraryRef(name="SPCoast", source="external"),)


def test_build_publication_populates_internal_lib_from_fp_lib_table(tmp_path: Path) -> None:
    """A project-local ``fp-lib-table`` entry lands as internal on Publication."""
    project = make_minimal_project(tmp_path / "demo", "demo")
    (project / "fp-lib-table").write_text(
        "(fp_lib_table\n"
        '  (lib (name "LocalLib")(type "KiCad")(uri "${KIPRJMOD}/local.pretty")'
        '(options "")(descr ""))\n'
        ")\n"
    )
    publication = PublishWorkflow.build_publication(
        _resolved(project),
        _project_info(),
        AnalysisInfo(findings=()),
    )
    assert publication.libraries == (LibraryRef(name="LocalLib", source="internal"),)


def test_build_publication_populates_ambiguous_lib_from_lib_id_ref(tmp_path: Path) -> None:
    """A ``(lib_id ...)`` ref with no lib-table entry lands as ambiguous."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "demo.kicad_pro").write_text("{}\n")
    (project / "demo.kicad_pcb").write_text("(kicad_pcb)\n")
    (project / "demo.kicad_sch").write_text('(kicad_sch (lib_id "SPCoast_KiCad_Library:R_0805"))\n')
    publication = PublishWorkflow.build_publication(
        _resolved(project),
        _project_info(),
        AnalysisInfo(findings=()),
    )
    assert publication.libraries == (LibraryRef(name="SPCoast_KiCad_Library", source="ambiguous"),)


def test_build_publication_libraries_defaults_to_empty(tmp_path: Path) -> None:
    """A bare project with no lib-tables or lib_id refs yields an empty tuple."""
    project = make_minimal_project(tmp_path / "demo", "demo")
    publication = PublishWorkflow.build_publication(
        _resolved(project),
        _project_info(),
        AnalysisInfo(findings=()),
    )
    assert publication.libraries == ()


def test_build_publication_preserves_other_fields(tmp_path: Path) -> None:
    """``project_info`` / ``analysis_info`` / ``body_md`` flow through unchanged."""
    project = make_minimal_project(tmp_path / "demo", "demo")
    project_info = _project_info()
    analysis_info = AnalysisInfo(findings=())
    publication = PublishWorkflow.build_publication(
        _resolved(project),
        project_info,
        analysis_info,
        body_md="hello",
    )
    assert publication.project_info is project_info
    assert publication.analysis_info is analysis_info
    assert publication.body_md == "hello"
