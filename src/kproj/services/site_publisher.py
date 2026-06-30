"""Stub :class:`SitePublisher` (docs/DESIGN.md § SitePublisher).

The ``PublishResult`` return type lives in :mod:`kproj.model.publish_result`
so this service can import it directly without the circular dependency
that existed when the dataclass lived in ``application/``.  See the
wave-2 carry-forward note in ``docs/CHANGELOG.md``.
"""

from __future__ import annotations

from pathlib import Path

from ..model.publication import Publication
from ..model.publish_result import PublishResult
from .change_journal import ChangeJournal


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
