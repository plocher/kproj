"""The :class:`SitePublisher` service.

Per ``docs/DESIGN.md`` § *SitePublisher* + § *Site-repo git workflow*,
this service:

1. Determines the publish outcome (``"noop"`` / ``"refresh"`` /
   ``"published"``) by comparing the current publication to the
   on-disk site state (§ *New-release detection*).
2. Writes the per-version markdown page and the per-project section
   index (``<versions_dir>/<P>/_index.md``) — paths selected by the
   caller-supplied :class:`~kproj.config.SiteProfile` — atomically via
   ``tempfile + os.replace``.
3. Registers every write with the :class:`ChangeJournal` for rollback
   (ADR 0005).
4. Runs ``git add``, ``git commit``, and (unless ``no_push``) ``git push``
   in the site repo.

**Commit message patterns** (per DESIGN § *Per-service contracts*).
The four states are distinguished from ``project_is_new`` /
``version_is_new`` (file existence) plus the resolved ``outcome``
(``publish`` = artifacts written, ``refresh`` = metadata-only):

- ``add: <Project> <board_rev>``       — first-ever publish of a project.
- ``publish: <Project>-<board_rev>``    — brand-new version of an existing project.
- ``republish: <Project>-<board_rev>``  — existing version, artifacts regenerated (source changed).
- ``refresh: <Project>-<board_rev> (metadata updated)`` — existing version, metadata-only change.
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
from ..config import SiteProfile
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


def _build_version_content(
    publication: Publication,
    site_profile: SiteProfile,
) -> str:
    """Render the version-page markdown body (front-matter + tables)."""
    yaml_block = _fm_formatter.render(publication, site_profile)
    body = publication.body_md
    return f"---\n{yaml_block}---\n{body}\n"


def _build_project_index_content(publication: Publication) -> str:
    """Build the project section-index page (``<versions_dir>/<P>/_index.md``).

    One project-global page per project, rewritten each publish to reflect
    the most-recent-publish state. Front-matter carries ``title`` +
    ``project`` so the project renders as a Hugo section. The body stacks
    the project-global content model, each part separated by a blank line
    and omitted when empty:

    1. ``README.md`` (:attr:`Publication.readme_md`).
    2. ``DESCRIPTION`` prose (:attr:`Publication.description`).
    3. A ``## Datasheets`` bullet list of discovered PDF filenames
       (:attr:`Publication.datasheets`).  Name-only for now; linking or
       copying the PDFs to the site is a deferred follow-up.

    A project with no README, DESCRIPTION, or datasheets yields a bare
    front-matter page (empty body) that matches the prior README-only
    output after whitespace normalisation, so no-op detection
    (:meth:`SitePublisher.detect_outcome`) is unaffected.
    """
    project = publication.project_info.project
    sections: list[str] = []
    if publication.readme_md.strip():
        sections.append(publication.readme_md.strip("\n"))
    if publication.description.strip():
        sections.append(publication.description.strip("\n"))
    if publication.datasheets:
        datasheet_lines = [
            "## Datasheets",
            "",
            *(f"- {name}" for name in publication.datasheets),
        ]
        sections.append("\n".join(datasheet_lines))
    body = "\n\n".join(sections)
    return f"---\ntitle: {project}\nproject: {project}\n---\n{body}\n"


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
        site_profile: SiteProfile,
        *,
        force_outcome: _Outcome | None = None,
    ) -> PublishResult:
        """Publish *publication* to the local site repo + commit + push.

        Performs full new-release detection (§ *New-release detection*)
        and returns early with ``outcome="noop"`` when nothing changed.

        Args:
            publication: The assembled :class:`Publication` to emit.
            site_repo: Local checkout of the SPCoast site repo.
            no_push: When ``True``, skip ``git push`` (batch-friendly).
            dry_run: When ``True``, analyse and report but make no writes.
            force_outcome: Optional pre-computed outcome from the
                caller (wave-3 M1 fix-up).  When set, this publisher
                skips its internal :meth:`detect_outcome` call —
                required for the workflow's asset-freshness escalation
                where post-generation asset mtimes would otherwise
                convince ``detect_outcome`` to noop the run.
            site_profile: :class:`SiteProfile` selecting per-version
                and per-project paths inside *site_repo*.

        Returns:
            A :class:`PublishResult` whose ``outcome`` is one of
            ``"published"``, ``"refreshed"``, or ``"noop"``.  Findings
            from the publication are threaded through into the result.
        """
        P = publication.project_info.project
        R = publication.project_info.board_rev
        PR = f"{P}-{R}"
        findings = publication.analysis_info.findings

        version_file = site_profile.version_page_path(site_repo, P, R)
        project_index_file = site_profile.project_index_path(site_repo, P)

        # ── new-release detection ──
        outcome = (
            force_outcome
            if force_outcome is not None
            else self.detect_outcome(publication, site_repo, site_profile=site_profile)
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
                project_index_file,
                outcome,
            )
            return PublishResult.build(
                "published" if outcome == "publish" else "refreshed",
                message=f"kproj: --dry-run; would {outcome} {PR}.",
                findings=findings,
            )

        # ── determine commit message prefix ──
        # Four distinct site-publish states, each meaningful in the
        # site repo's publish log.  File existence separates new
        # project / new version from a re-touch of an existing version;
        # the resolved ``outcome`` separates a full artifact regen
        # (publish) from a metadata-only rewrite (refresh):
        #   add       - first-ever publish of this project
        #   publish   - brand-new version of an existing project
        #   republish - existing version, artifacts regenerated (source changed)
        #   refresh   - existing version, metadata-only change
        project_is_new = not project_index_file.exists()
        version_is_new = not version_file.exists()

        if project_is_new:
            commit_msg = f"add: {P} {R}"
        elif version_is_new:
            commit_msg = f"publish: {PR}"
        elif outcome == "publish":
            commit_msg = f"republish: {PR}"
        else:  # outcome == "refresh"
            commit_msg = f"refresh: {PR} (metadata updated)"

        would_be_version = _build_version_content(publication, site_profile)
        would_be_project_index = _build_project_index_content(publication)

        # ── write version file atomically ──
        version_file.parent.mkdir(parents=True, exist_ok=True)
        if version_file.exists():
            self._journal.will_modify(version_file)
        else:
            self._journal.will_create(version_file)
        _atomic_write(version_file, would_be_version)

        # ── write project section index atomically ──
        project_index_file.parent.mkdir(parents=True, exist_ok=True)
        if project_index_file.exists():
            self._journal.will_modify(project_index_file)
        else:
            self._journal.will_create(project_index_file)
        _atomic_write(project_index_file, would_be_project_index)

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
            project_index_file=project_index_file,
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
        project_index_file: Path,
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
            project_index_file,
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
        site_profile: SiteProfile,
    ) -> _Outcome:
        """Determine whether publishing is a no-op, refresh, or full publish.

        Implements ``docs/DESIGN.md`` § *New-release detection*:

        1. ``<site_profile.versions_dir>/<P>/<R>.md`` absent → ``"publish"``.
        2. Any referenced asset missing in the site repo → ``"publish"``.
        3. Would-be version content differs from on-disk → ``"refresh"``.
        4. Pages file body differs from ``publication.readme_md`` → ``"refresh"``.
        5. All checks pass → ``"noop"``.

        Args:
            publication: The assembled publication to compare against.
            site_repo: Local site-repo checkout.
            site_profile: :class:`SiteProfile` selecting per-version
                and per-project paths inside *site_repo*.

        Returns:
            One of ``"noop"``, ``"refresh"``, or ``"publish"``.
        """
        P = publication.project_info.project
        R = publication.project_info.board_rev

        version_file = site_profile.version_page_path(site_repo, P, R)
        project_index_file = site_profile.project_index_path(site_repo, P)

        # Step 1: version file must exist.
        if not version_file.exists():
            return "publish"

        # Step 2: every referenced asset must exist in the site repo.
        # Assets are referenced by their public URL (/versions/...) but
        # physically live under the profile's assets_dir (Hugo:
        # static/versions/...), so map the URL to disk via the profile.
        for ref in (*publication.images, *publication.artifacts):
            asset_path = site_profile.asset_disk_path(site_repo, ref.path)
            if not asset_path.exists():
                return "publish"

        # Step 3: compare rendered content to on-disk content.  Hugo's
        # reserved ``date`` field (the publish timestamp) is volatile —
        # a plain re-run would otherwise always differ — so it is
        # ignored here.  No-op detection is a performance optimisation,
        # not a correctness gate, so this accommodation is safe.
        would_be_version = _build_version_content(publication, site_profile)
        existing_version = version_file.read_text(encoding="utf-8")
        if _normalize(_strip_volatile(existing_version)) != _normalize(
            _strip_volatile(would_be_version)
        ):
            return "refresh"

        # Step 4: compare the project section index to what we'd emit.
        if project_index_file.exists():
            existing_index = project_index_file.read_text(encoding="utf-8")
            would_be_index = _build_project_index_content(publication)
            if _normalize(existing_index) != _normalize(would_be_index):
                return "refresh"
        else:
            # Section index missing — create it during the refresh.
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


def _strip_volatile(text: str) -> str:
    """Drop volatile front-matter lines (Hugo's publish ``date:``) for comparison.

    The publish timestamp changes on every run; excluding it keeps a
    content-identical re-run a no-op, per the new-release-detection
    contract's "ignores volatile keys" rule. Only a line beginning
    exactly with ``date:`` is dropped (``issue_date:`` / ``fab_date:``
    are preserved).
    """
    return "\n".join(line for line in text.splitlines() if not line.startswith("date:"))


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
