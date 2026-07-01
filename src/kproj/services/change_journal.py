"""The :class:`ChangeJournal` transactional write tracker.

Per ``docs/adr/0005-writetracker-transactional-site-writes.md`` and
``docs/GLOSSARY.md`` § *ChangeJournal*, this is a context-manager
service that records every file the publish pipeline will create or
modify in the site repo. On any exception (raised in the ``with``
block), :meth:`__exit__` performs a rollback:

- Created files are unlinked.
- Modified files are restored via ``git checkout -- <path>``.
- If ``mark_committed()`` ran but ``mark_pushed()`` did not, the
  commit is undone via ``git reset --hard HEAD^``.

Dry-run mode (``dry_run=True``) records intent but skips git
invocations on rollback so unit tests + ``--dry-run`` runs can exercise
the journal without touching git.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType
from typing import Self

from ..common.subprocess_runner import (
    DEFAULT_GIT_TIMEOUT,
    SubprocessFailedError,
)
from ..common.subprocess_runner import (
    run as subprocess_run,
)

_log = logging.getLogger(__name__)


def _is_inside(path: Path, root: Path) -> bool:
    """Return ``True`` iff *path* is at or beneath *root*."""
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


class ChangeJournal:
    """Transactional write tracker scoped to a single ``site_repo``.

    Attributes:
        site_repo: Local checkout of the SPCoast Jekyll site repo.
        dry_run: When ``True``, rollback records intent only; git is
            not invoked. Useful for ``kproj --dry-run`` invocations.
    """

    def __init__(self, site_repo: Path, *, dry_run: bool = False) -> None:
        """Construct a journal for *site_repo*.

        Args:
            site_repo: Path to the local site repo checkout. All
                tracked paths must lie under this root.
            dry_run: When ``True``, rollback skips git invocations.
        """
        self.site_repo = site_repo
        self.dry_run = dry_run
        self._created: list[Path] = []
        self._modified: list[Path] = []
        self._committed: bool = False
        self._pushed: bool = False

    # ----- context-manager plumbing -----
    def __enter__(self) -> Self:
        """Enter the journal's scope.

        Returns:
            ``self`` so the ``with`` block can call
            ``will_create`` / ``will_modify`` etc.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back on any non-``None`` *exc_type*; otherwise no-op.

        Returns ``None`` (i.e. ``False``) so the exception propagates.
        """
        if exc_type is not None:
            self.rollback()

    # ----- intake methods (validation at the boundary) -----
    def will_create(self, path: Path) -> None:
        """Record intent to create *path*.

        Args:
            path: Absolute path that will be written. Must be under
                :attr:`site_repo`.

        Raises:
            ValueError: When *path* is outside :attr:`site_repo`.
        """
        self._validate_path(path)
        if path not in self._created and path not in self._modified:
            self._created.append(path)

    def will_modify(self, path: Path) -> None:
        """Record intent to modify *path*.

        Args:
            path: Absolute path that will be modified. Must be under
                :attr:`site_repo`.

        Raises:
            ValueError: When *path* is outside :attr:`site_repo`.
        """
        self._validate_path(path)
        if path in self._created:
            # Already tracked as a creation; keep that stronger semantic.
            return
        if path not in self._modified:
            self._modified.append(path)

    def register_output(self, path: Path) -> None:
        """Record an artifact-producer's intent to write *path*.

        Dispatches to :meth:`will_modify` when *path* already exists on
        disk and to :meth:`will_create` otherwise.  This is the
        single-entry seam producers (PcbExporter, SchematicExporter,
        IbomGenerator, FabPackager, SourcePackager) use so that
        rollback restores pre-existing committed assets via
        ``git checkout`` and only unlinks files we genuinely created
        this run (ADR 0005 § *Rollback*).

        The check is performed exactly once, at the moment the
        producer announces the write — BEFORE the atomic tempfile +
        ``os.replace`` sequence — so the original on-disk file is
        still observable when the decision is made.

        Args:
            path: Absolute path the producer is about to write.  Must
                be under :attr:`site_repo`.

        Raises:
            ValueError: When *path* is outside :attr:`site_repo`.
        """
        if path.exists():
            self.will_modify(path)
        else:
            self.will_create(path)

    def mark_committed(self) -> None:
        """Mark the in-flight git commit as complete.

        After this call, rollback will undo the commit via
        ``git reset --hard HEAD^`` (unless :meth:`mark_pushed` is
        called).
        """
        self._committed = True

    def mark_pushed(self) -> None:
        """Mark the in-flight ``git push`` as complete.

        After this call, rollback no longer attempts ``git reset
        --hard HEAD^`` (the commit is now part of the remote history
        and undoing it locally would diverge).
        """
        self._pushed = True

    def all_paths(self) -> Iterator[Path]:
        """Yield every tracked path (creations + modifications, deduplicated)."""
        seen: set[Path] = set()
        for path in (*self._created, *self._modified):
            if path not in seen:
                seen.add(path)
                yield path

    # ----- rollback -----
    def rollback(self) -> None:
        """Roll back any recorded changes per ADR 0005.

        - Unlink each tracked-as-created file (missing-OK).
        - Restore each tracked-as-modified file via ``git checkout``.
        - If a commit happened but a push did not, reset HEAD^.
        - When :attr:`dry_run` is ``True``, the git steps are skipped.
        """
        for path in self._created:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                _log.warning("rollback: failed to unlink %s: %s", path, exc)

        if self._modified and not self.dry_run:
            relative = [str(p.relative_to(self.site_repo)) for p in self._modified]
            self._git("checkout", "--", *relative)

        if self._committed and not self._pushed and not self.dry_run:
            try:
                self._git("reset", "--hard", "HEAD^")
            except SubprocessFailedError as exc:
                _log.error("rollback: git reset --hard HEAD^ failed: %s", exc)

    # ----- helpers -----
    def _validate_path(self, path: Path) -> None:
        """Reject paths outside :attr:`site_repo` at intake."""
        if not _is_inside(path, self.site_repo):
            raise ValueError(f"path {path!r} is outside site_repo {self.site_repo!r}")

    def _git(self, *args: str) -> None:
        """Run ``git -C <site_repo> <args>`` via the shared subprocess runner."""
        command = ["git", "-C", str(self.site_repo), *args]
        try:
            subprocess_run(command, timeout=DEFAULT_GIT_TIMEOUT, check=True)
        except SubprocessFailedError as exc:
            _log.warning(
                "rollback: %s failed (rc=%s): %s", " ".join(command), exc.returncode, exc.stderr
            )
