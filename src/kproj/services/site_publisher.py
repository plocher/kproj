"""Stub :class:`SitePublisher` (docs/DESIGN.md § SitePublisher).

The ``publish`` method's declared return type is
:class:`kproj.application.publish_workflow.PublishResult`; the import
is done lazily under ``TYPE_CHECKING`` to avoid a circular import
(``application`` imports from ``services`` for the project reader).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..model.publication import Publication
from .change_journal import ChangeJournal

if TYPE_CHECKING:
    from ..application.publish_workflow import PublishResult


class SitePublisher:
    """Writes a :class:`Publication` into the local site repo (stub)."""

    def __init__(self, change_journal: ChangeJournal) -> None:
        """Construct a site publisher.

        Args:
            change_journal: The open :class:`ChangeJournal` scoping
                this publish's transactional writes.
        """
        self._journal = change_journal

    def publish(
        self,
        publication: Publication,
        site_repo: Path,
        no_push: bool,
        dry_run: bool,
    ) -> PublishResult:
        """Publish *publication* to the local site repo + push.

        Raises:
            NotImplementedError: Always, in the foundation slice.
        """
        raise NotImplementedError(
            "SitePublisher.publish is not implemented in the foundation slice; "
            "see docs/DESIGN.md § SitePublisher."
        )
