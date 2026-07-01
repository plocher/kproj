"""The :class:`SitePublisher` service.

Per ``docs/DESIGN.md`` § *SitePublisher* + § *Site-repo git workflow*,
this service:

1. Determines the publish outcome (``"noop"`` / ``"refresh"`` /
   ``"published"``) by comparing the current publication to the
   on-disk site state (§ *New-release detection*).
2. Writes ``_versions/<P>/<R>.md`` and ``pages/<P>.md`` atomically via
   ``tempfile + os.replace``.
3. Registers every write with the :class:`ChangeJournal` for rollback
   (ADR 0005).
4. Runs ``git add``, ``git commit``, and (unless ``no_push``) ``git push``
   in the site repo.

**Commit message patterns** (per DESIGN § *Per-service contracts*):

- ``add: <Project> <board_rev>``    — first-ever publish for a project.
- ``publish: <Project>-<board_rev>`` — new version for an existing project.
- ``refresh: <Project>-<board_rev> (<reason>)`` — metadata-only update.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path
from typing import Literal

from ..common.subprocess_runner import DEFAULT_GIT_TIMEOUT
from ..common.subprocess_runner import run as subprocess_run
from ..formatters.front_matter_summary_formatter import FrontMatterSummaryFormatter
from ..model.publication import Publication
from ..model.publish_result import PublishResult
from .change_journal import ChangeJournal

_log = logging.getLogger(__name__)

_fm_formatter = FrontMatterSummaryFormatter()

# ──────────────────────────── type aliases ────────────────────────────────────

_Outcome = Literal["noop", "refresh", "publish"]


# ──────────────────────────── module-level git helper ─────────────────────────


def _git_run(
    cmd: list[str],
    *,
    site_repo: Path,
    check: bool = True,
) -> None:
    """Run a git sub-command against *site_repo*.

    Args:
        cmd: The git sub-command and its arguments (e.g. ``["add", "-A"]``).
        site_repo: The local site-repo checkout.
        check: When ``True`` (default), a non-zero exit raises
            :exc:`~kproj.common.subprocess_runner.SubprocessFailedError`.
    """
    subprocess_run(
        ["git", "-C", str(site_repo), *cmd],
        timeout=DEFAULT_GIT_TIMEOUT,
        check=check,
    )


# ──────────────────────────── content builders ─────────────────────────────────


def _build_version_content(publication: Publication) -> str:
    """Build the full markdown content for ``_versions/<P>/<R>.md``."""
    yaml_block = _fm_formatter.render(publication)
    body = publication.body_md
    return f"---\n{yaml_block}---\n{body}\n"


def _build_pages_content(publication: Publication) -> str:
    """Build the content for ``pages/<P>.md``."""
    project = publication.project_info.project
    readme = publication.readme_md
    return f"---\nproject: {project}\n---\n{readme}\n"


# ──────────────────────────── SitePublisher ──────────────────────────────────


class SitePublisher:
    """Writes a :class:`Publication` into the local site repo + commits.

    The journal is injected via the constructor.  All writes go through
    :meth:`ChangeJournal.will_create` so the workflow's rollback covers
    them on any mid-pipeline exception.
    """

    def __init__(self, change_journal: ChangeJournal) -> None:
        """Construct a site publisher.

        Args:
            change_journal: The open :class:`ChangeJournal` scoping
                this publish's transactional writes.
        """
        self._journal = change_journal

    # ----- primary method -----

    def publish(
        self,
        publication: Publication,
        site_repo: Path,
        no_push: bool,
        dry_run: bool,
        *,
        force_outcome: _Outcome | None = None,
    ) -> PublishResult:
        """Publish *publication* to the local site repo + commit + push.

        Performs full new-release detection (§ *New-release detection*)
        and returns early with ``outcome="noop"`` when nothing changed.

        Args:
            publication: The assembled :class:`Publication` to emit.
            site_repo: Local checkout of the SPCoast Jekyll site repo.
            no_push: When ``True``, skip ``git push`` (batch-friendly).
            dry_run: When ``True``, analyse and report but make no writes.
            force_outcome: Optional pre-computed outcome from the
                caller (wave-3 M1 fix-up).  When set, this publisher
                skips its internal :meth:`detect_outcome` call —
                required for the workflow's asset-freshness escalation
                where post-generation asset mtimes would otherwise
                convince ``detect_outcome`` to noop the run.

        Returns:
            A :class:`PublishResult` whose ``outcome`` is one of
            ``"published"``, ``"refreshed"``, or ``"noop"``.  Findings
            from the publication are threaded through into the result.
        """
        P = publication.project_info.project
        R = publication.project_info.board_rev
        PR = f"{P}-{R}"
        findings = publication.analysis_info.findings

        version_file = site_repo / "_versions" / P / f"{R}.md"
        pages_file = site_repo / "pages" / f"{P}.md"

        # ── new-release detection ──
        outcome = (
            force_outcome
            if force_outcome is not None
            else self.detect_outcome(publication, site_repo)
        )

        if outcome == "noop":
            return PublishResult.build(
                "noop",
                message=f"kproj: {PR} unchanged — nothing to publish.",
                findings=findings,
            )

        if dry_run:
            _log.info(
                "dry-run: would write %s + %s (outcome=%s)",
                version_file,
                pages_file,
                outcome,
            )
            return PublishResult.build(
                "published" if outcome == "publish" else "refreshed",
                message=f"kproj: --dry-run; would {outcome} {PR}.",
                findings=findings,
            )

        # ── determine commit message prefix ──
        project_is_new = not pages_file.exists()
        version_is_new = not version_file.exists()

        if project_is_new:
            commit_msg = f"add: {P} {R}"
        elif version_is_new:
            commit_msg = f"publish: {PR}"
        else:
            commit_msg = f"refresh: {PR} (metadata updated)"

        would_be_version = _build_version_content(publication)
        would_be_pages = _build_pages_content(publication)

        # ── write version file atomically ──
        version_file.parent.mkdir(parents=True, exist_ok=True)
        if version_file.exists():
            self._journal.will_modify(version_file)
        else:
            self._journal.will_create(version_file)
        _atomic_write(version_file, would_be_version)

        # ── write pages file atomically ──
        pages_file.parent.mkdir(parents=True, exist_ok=True)
        if pages_file.exists():
            self._journal.will_modify(pages_file)
        else:
            self._journal.will_create(pages_file)
        _atomic_write(pages_file, would_be_pages)

        # ── git add + commit + push ──
        # BLOCKER 2 fix: stage EVERY path the journal knows about (assets
        # written by upstream producers + the two markdown files we just
        # wrote).  Pre-fix the publisher staged only the markdown, leaving
        # generated renders/STEP/iBOM/fab/source archives untracked while
        # the committed markdown linked to them - violating PRD Story 1's
        # "standard asset set" commit/push expectation and ADR 0005's
        # guarantee that ``journal.all_paths()`` is the tracked publish set.
        touched_paths = self._collect_paths_to_stage(
            site_repo=site_repo,
            version_file=version_file,
            pages_file=pages_file,
        )
        _git_run(["add", *touched_paths], site_repo=site_repo)
        _git_run(["commit", "-m", commit_msg], site_repo=site_repo)
        self._journal.mark_committed()

        if not no_push:
            _git_run(["push"], site_repo=site_repo)
            self._journal.mark_pushed()

        if outcome == "publish":
            return PublishResult.build(
                "published",
                message=f"kproj: published {PR}.",
                findings=findings,
            )
        return PublishResult.build(
            "refreshed",
            message=f"kproj: refreshed {PR}.",
            findings=findings,
        )

    def _collect_paths_to_stage(
        self,
        *,
        site_repo: Path,
        version_file: Path,
        pages_file: Path,
    ) -> list[str]:
        """Return the deduplicated set of paths (relative to *site_repo*) to ``git add``.

        Includes:

        - Every path registered with :class:`ChangeJournal` (created or
          modified) via :meth:`ChangeJournal.all_paths`. This is the
          authoritative tracked publish set per ADR 0005.
        - The version-page and project-page markdown files written by
          this publisher (defensively included even though they are
          already journalled - belt-and-braces against a future change
          that registers them after staging).

        Paths outside *site_repo* are skipped defensively; the journal
        validates at intake but the safety net keeps a stray test path
        from generating a confusing ``git add`` error.

        Args:
            site_repo: Local site-repo checkout.
            version_file: ``_versions/<P>/<R>.md`` path just written.
            pages_file: ``pages/<P>.md`` path just written.

        Returns:
            A list of repo-relative path strings in insertion order,
            with duplicates removed.
        """
        ordered: list[str] = []
        seen: set[str] = set()
        for absolute in (
            *self._journal.all_paths(),
            version_file,
            pages_file,
        ):
            try:
                rel = str(absolute.relative_to(site_repo))
            except ValueError:
                continue
            if rel not in seen:
                seen.add(rel)
                ordered.append(rel)
        return ordered

    # ----- static detection helper -----

    @staticmethod
    def detect_outcome(
        publication: Publication,
        site_repo: Path,
    ) -> _Outcome:
        """Determine whether publishing is a no-op, refresh, or full publish.

        Implements ``docs/DESIGN.md`` § *New-release detection*:

        1. ``_versions/<P>/<R>.md`` absent → ``"publish"``.
        2. Any referenced asset missing in the site repo → ``"publish"``.
        3. Would-be version content differs from on-disk → ``"refresh"``.
        4. Pages file body differs from ``publication.readme_md`` → ``"refresh"``.
        5. All checks pass → ``"noop"``.

        Args:
            publication: The assembled publication to compare against.
            site_repo: Local site-repo checkout.

        Returns:
            One of ``"noop"``, ``"refresh"``, or ``"publish"``.
        """
        P = publication.project_info.project
        R = publication.project_info.board_rev

        version_file = site_repo / "_versions" / P / f"{R}.md"
        pages_file = site_repo / "pages" / f"{P}.md"

        # Step 1: version file must exist.
        if not version_file.exists():
            return "publish"

        # Step 2: every referenced asset must exist in the site repo.
        for ref in (*publication.images, *publication.artifacts):
            asset_path = site_repo / ref.path.lstrip("/")
            if not asset_path.exists():
                return "publish"

        # Step 3: compare rendered content to on-disk content.
        would_be_version = _build_version_content(publication)
        existing_version = version_file.read_text(encoding="utf-8")
        if _normalize(existing_version) != _normalize(would_be_version):
            return "refresh"

        # Step 4: compare pages/<P>.md to publication.readme_md.
        if pages_file.exists():
            existing_pages = pages_file.read_text(encoding="utf-8")
            would_be_pages = _build_pages_content(publication)
            if _normalize(existing_pages) != _normalize(would_be_pages):
                return "refresh"
        else:
            # Pages file missing — create it during the refresh.
            return "refresh"

        return "noop"


# ──────────────────────────── helpers ─────────────────────────────────────────


def _atomic_write(path: Path, content: str) -> None:
    """Write *content* to *path* atomically via a sibling tempfile.

    Uses :func:`os.replace` for rename-into-place so partial writes
    never appear in ``git status`` (ADR 0005 § *Atomic per-file writes*).

    Args:
        path: Target file path.  Parent directory must already exist.
        content: Text content to write (UTF-8).
    """
    suffix = path.suffix or ".tmp"
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.stem}.",
        suffix=suffix,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _normalize(text: str) -> str:
    """Normalise whitespace for content comparison.

    Strips trailing whitespace from each line and removes leading/trailing
    blank lines so trivial whitespace differences don't force a re-publish.

    Args:
        text: Raw file content.

    Returns:
        Normalised string.
    """
    lines = [ln.rstrip() for ln in text.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)
