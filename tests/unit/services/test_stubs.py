"""Smoke tests confirming all wave-3 services are fully implemented.

Wave-4 (kproj#4) implements ``SitePublisher``; the previous
``NotImplementedError`` stub is replaced by a real implementation.
This module is now a simple smoke test that the service is importable
and its primary method is callable.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from kproj.config import GENERIC_SITE_PROFILE
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


def test_site_publisher_is_implemented(tmp_path: Path) -> None:
    """``SitePublisher.publish`` is now fully implemented (kproj#4)."""
    publication = Publication(
        project_info=_project_info(),
        analysis_info=AnalysisInfo(findings=()),
        body_md="",
        readme_md="",
    )
    with ChangeJournal(tmp_path, dry_run=True) as journal:
        publisher = SitePublisher(change_journal=journal)
        with patch("kproj.services.site_publisher._git_run"):
            result = publisher.publish(
                publication,
                tmp_path,
                no_push=True,
                dry_run=True,
                site_profile=GENERIC_SITE_PROFILE,
            )
    # dry_run=True returns without writing files
    assert result.outcome in ("published", "refreshed", "noop")
