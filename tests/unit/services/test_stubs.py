"""Smoke tests for the foundation-slice service stubs.

Each downstream service's primary method must raise
:class:`NotImplementedError` per the issue #1 acceptance criteria.
These tests pin the contract so a future slice cannot silently
remove the stub.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kproj.model.analysis_info import AnalysisInfo
from kproj.model.project_info import ProjectInfo, Status
from kproj.model.publication import Publication
from kproj.services.change_journal import ChangeJournal
from kproj.services.design_analyzer import DesignAnalyzer
from kproj.services.fab_packager import FabPackager
from kproj.services.ibom_generator import IbomGenerator
from kproj.services.metadata_analyzer import MetadataAnalyzer
from kproj.services.pcb_exporter import PcbExporter
from kproj.services.schematic_exporter import SchematicExporter
from kproj.services.site_publisher import SitePublisher
from kproj.services.source_packager import SourcePackager
from kproj.services.zip_archiver import ZipArchiver


def _project_info() -> ProjectInfo:
    return ProjectInfo(
        project="demo",
        title="demo",
        company="MRCS",
        design_rev="1.0",
        board_rev="1.0B",
        date="2026.06",
        designer="John Plocher",
        tagline="t",
        overview="o",
        status=Status.ACTIVE,
    )


def test_metadata_analyzer_stub_raises(tmp_path: Path) -> None:
    """``MetadataAnalyzer.analyze`` is unimplemented in the foundation slice."""
    with pytest.raises(NotImplementedError):
        MetadataAnalyzer().analyze(_project_info(), tmp_path)


def test_design_analyzer_stub_raises(tmp_path: Path) -> None:
    """``DesignAnalyzer.analyze`` is unimplemented in the foundation slice."""
    with pytest.raises(NotImplementedError):
        DesignAnalyzer(kicad_cli=tmp_path / "kicad-cli").analyze(
            resolved=None  # type: ignore[arg-type]
        )


def test_pcb_exporter_stub_raises(tmp_path: Path) -> None:
    """``PcbExporter`` methods are unimplemented in the foundation slice."""
    exporter = PcbExporter(kicad_cli=tmp_path / "kicad-cli")
    with pytest.raises(NotImplementedError):
        exporter.export_render(tmp_path / "x.kicad_pcb", "top", tmp_path / "out.png")
    with pytest.raises(NotImplementedError):
        exporter.export_step(tmp_path / "x.kicad_pcb", tmp_path / "out.step")


def test_schematic_exporter_stub_raises(tmp_path: Path) -> None:
    """``SchematicExporter`` methods are unimplemented in the foundation slice."""
    exporter = SchematicExporter(kicad_cli=tmp_path / "kicad-cli")
    with pytest.raises(NotImplementedError):
        exporter.export_svg(tmp_path / "x.kicad_sch", tmp_path / "out.svg")
    with pytest.raises(NotImplementedError):
        exporter.export_pdf(tmp_path / "x.kicad_sch", tmp_path / "out.pdf")


def test_ibom_generator_stub_raises(tmp_path: Path) -> None:
    """``IbomGenerator.generate`` is unimplemented in the foundation slice."""
    with pytest.raises(NotImplementedError):
        IbomGenerator(ibom_script=tmp_path / "ibom.py").generate(
            pcb_path=tmp_path / "x.kicad_pcb",
            output_dir=tmp_path,
            name_format="demo",
        )


def test_fab_packager_stub_raises(tmp_path: Path) -> None:
    """``FabPackager.package`` is unimplemented in the foundation slice."""
    with pytest.raises(NotImplementedError):
        FabPackager(zip_archiver=ZipArchiver()).package(
            production_dir=tmp_path, output=tmp_path / "out.zip"
        )


def test_source_packager_stub_raises(tmp_path: Path) -> None:
    """``SourcePackager.package`` is unimplemented in the foundation slice."""
    with pytest.raises(NotImplementedError):
        SourcePackager(zip_archiver=ZipArchiver()).package(
            project_dir=tmp_path, output=tmp_path / "out.zip"
        )


def test_site_publisher_stub_raises(tmp_path: Path) -> None:
    """``SitePublisher.publish`` is unimplemented in the foundation slice."""
    publication = Publication(
        project_info=_project_info(),
        analysis_info=AnalysisInfo(findings=()),
        body_md="",
    )
    with ChangeJournal(tmp_path) as journal:
        publisher = SitePublisher(change_journal=journal)
        with pytest.raises(NotImplementedError):
            publisher.publish(publication, tmp_path, no_push=True, dry_run=True)
