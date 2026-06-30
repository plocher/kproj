"""Smoke tests for the still-stubbed downstream services.

Wave-2 retires the ``MetadataAnalyzer`` / ``DesignAnalyzer`` /
``KicadProjectReader`` stub assertions - those services are
implemented now and have their own test modules.  Wave-3 (this
slice) retires the ``PcbExporter`` stub.  The remaining services
(schematic exporter, iBOM generator, fab + source packagers, site
publisher) stay wave-1 stubs until later slices wire them in;
their NotImplementedError contract is still pinned here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kproj.model.analysis_info import AnalysisInfo
from kproj.model.project_info import ProjectInfo, Status
from kproj.model.publication import Publication
from kproj.services.change_journal import ChangeJournal
from kproj.services.site_publisher import SitePublisher


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
