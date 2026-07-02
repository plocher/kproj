"""The :class:`SitePublisher` service.

Per ``docs/DESIGN.md`` § *SitePublisher* + § *Site-repo git workflow*,
this service:

1. Renders the per-version markdown page and the per-project section
   index (``<versions_dir>/<P>/_index.md``) - paths selected by the
   caller-supplied :class:`~kproj.config.SiteProfile` - and writes them
   atomically via ``tempfile + os.replace``.
2. Registers every write with the :class:`ChangeJournal` for rollback
   (ADR 0005).
3. Stages the journalled paths and lets **git** decide whether anything
   actually changed: an empty ``git diff --cached`` is a no-op (no
   commit); otherwise it commits and (unless ``no_push``) pushes.

**Change detection is delegated to git**, not re-derived in kproj.
Make-style artifact regeneration upstream (a producer rewrites an asset
only when its KiCad source is newer) keeps unchanged binaries
byte-identical, and the version page's volatile publish ``date`` is
preserved from the on-disk file so a content-identical re-run produces
byte-identical markdown.  git therefore sees no staged change and the
run is a clean no-op.  (The timestamped-artifact caveat - STEP / PDF /
iBOM embed a generation time - is handled by NOT regenerating them when
their source is unchanged.)

**Commit message prefixes** (informational for the site publish log,
derived from what git actually staged):

- ``add: <Project> <board_rev>``       - first-ever publish of a project.
- ``publish: <Project>-<board_rev>``    - brand-new version of an existing project.
- ``republish: <Project>-<board_rev>``  - existing version, assets regenerated.
- ``refresh: <Project>-<board_rev> (metadata updated)`` - existing version, markdown-only.
"""

from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from dataclasses import replace
from pathlib import Path

import yaml

from ..common.subprocess_runner import DEFAULT_GIT_TIMEOUT
from ..common.subprocess_runner import run as subprocess_run
from ..config import SiteProfile
from ..formatters.front_matter_summary_formatter import FrontMatterSummaryFormatter
from ..model.publication import Publication
from ..model.publish_result import PublishResult
from .change_journal import ChangeJournal

_log = logging.getLogger(__name__)

_fm_formatter = FrontMatterSummaryFormatter()


# ──────────────────────────── module-level git helpers ────────────────────────


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


def _git_staged_names(site_repo: Path) -> list[str]:
    """Return the repo-relative paths git currently has staged.

    Uses ``git diff --cached --name-only`` with ``check=False`` so a repo
    without commits yet (or a non-repo directory, in unit tests) yields an
    empty list rather than raising.

    Args:
        site_repo: The local site-repo checkout.

    Returns:
        The list of staged path strings (empty when nothing is staged).
    """
    result = subprocess_run(
        ["git", "-C", str(site_repo), "diff", "--cached", "--name-only"],
        timeout=DEFAULT_GIT_TIMEOUT,
        check=False,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


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
    ``project`` (so the project renders as a Hugo section) plus the
    discovered ``datasheets`` filenames as a YAML list. The datasheets are
    front-matter *data*, not body prose, so the site layer decides how to
    present them (e.g. a collapsible list or a download bundle) rather than
    the presentation being baked into the page.

    The body is the project *description*: ``README.md``
    (:attr:`Publication.readme_md`) then the optional ``DESCRIPTION`` prose
    (:attr:`Publication.description`), each separated by a blank line and
    omitted when empty. A project with no README/DESCRIPTION and no
    datasheets yields a bare front-matter page (empty body).
    """
    project = publication.project_info.project
    front_matter: list[str] = [f"title: {project}", f"project: {project}"]
    if publication.datasheets:
        front_matter.append("datasheets:")
        front_matter.extend(f"- {name}" for name in publication.datasheets)
    sections: list[str] = []
    if publication.readme_md.strip():
        sections.append(publication.readme_md.strip("\n"))
    if publication.description.strip():
        sections.append(publication.description.strip("\n"))
    body = "\n\n".join(sections)
    return "---\n" + "\n".join(front_matter) + "\n---\n" + body + "\n"


# ──────────────────────────── SitePublisher ──────────────────────────────────


class SitePublisher:
    """Writes a :class:`Publication` into the local site repo + commits.

    The journal is injected via the constructor.  All writes go through
    :meth:`ChangeJournal.register_output` so the workflow's rollback
    covers them on any mid-pipeline exception.
    """

    def __init__(self, change_journal: ChangeJournal) -> None:
        """Construct a site publisher.

        Args:
            change_journal: The open :class:`ChangeJournal` scoping this
                publish's transactional writes.
        """
        self._journal = change_journal

    def publish(
        self,
        publication: Publication,
        site_repo: Path,
        no_push: bool,
        dry_run: bool,
        site_profile: SiteProfile,
    ) -> PublishResult:
        """Publish *publication* to the local site repo + commit + push.

        Writes the version page + project section index, stages the
        journalled paths, and lets git decide whether to commit: an empty
        ``git diff --cached`` means nothing changed, so the run is a
        no-op.  The version page's publish ``date`` is preserved from the
        on-disk file so a content-identical re-run is byte-identical (and
        thus a git no-op).

        Args:
            publication: The assembled :class:`Publication` to emit.
            site_repo: Local checkout of the SPCoast site repo.
            no_push: When ``True``, skip ``git push`` (batch-friendly).
            dry_run: When ``True``, analyse and report but make no writes.
            site_profile: :class:`SiteProfile` selecting per-version and
                per-project paths inside *site_repo*.

        Returns:
            A :class:`PublishResult` whose ``outcome`` is one of
            ``"published"``, ``"refreshed"``, or ``"noop"``.
        """
        P = publication.project_info.project
        R = publication.project_info.board_rev
        PR = f"{P}-{R}"
        findings = publication.analysis_info.findings

        version_file = site_profile.version_page_path(site_repo, P, R)
        project_index_file = site_profile.project_index_path(site_repo, P)

        if dry_run:
            _log.info(
                "dry-run: would write %s + %s",
                version_file,
                project_index_file,
            )
            return PublishResult.build(
                "published",
                message=f"kproj: --dry-run; would publish {PR}.",
                findings=findings,
            )

        # File existence BEFORE writing decides the commit-prefix verb.
        project_is_new = not project_index_file.exists()
        version_is_new = not version_file.exists()

        # Preserve the on-disk publish date so an otherwise-identical
        # re-run reproduces byte-identical markdown; git then sees no
        # change and skips the commit.  A brand-new page keeps the fresh
        # timestamp the workflow computed.
        preserved_date = _existing_date(version_file)
        render_pub = (
            replace(publication, published_at=preserved_date)
            if preserved_date is not None
            else publication
        )

        version_content = _build_version_content(render_pub, site_profile)
        project_index_content = _build_project_index_content(render_pub)

        # ── write version file atomically ──
        version_file.parent.mkdir(parents=True, exist_ok=True)
        self._journal.register_output(version_file)
        _atomic_write(version_file, version_content)

        # ── write project section index atomically ──
        project_index_file.parent.mkdir(parents=True, exist_ok=True)
        self._journal.register_output(project_index_file)
        _atomic_write(project_index_file, project_index_content)

        # ── stage every journalled path + let git detect changes ──
        touched_paths = self._collect_paths_to_stage(
            site_repo=site_repo,
            version_file=version_file,
            project_index_file=project_index_file,
        )
        _git_run(["add", *touched_paths], site_repo=site_repo)

        staged = _git_staged_names(site_repo)
        if not staged:
            return PublishResult.build(
                "noop",
                message=f"kproj: {PR} unchanged - nothing to publish.",
                findings=findings,
            )

        commit_msg = _commit_message(
            P,
            R,
            project_is_new=project_is_new,
            version_is_new=version_is_new,
            staged=staged,
            site_profile=site_profile,
        )
        _git_run(["commit", "-m", commit_msg], site_repo=site_repo)
        self._journal.mark_committed()

        if not no_push:
            _git_run(["push"], site_repo=site_repo)
            self._journal.mark_pushed()

        if commit_msg.startswith("refresh:"):
            return PublishResult.build(
                "refreshed",
                message=f"kproj: refreshed {PR}.",
                findings=findings,
            )
        return PublishResult.build(
            "published",
            message=f"kproj: published {PR}.",
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

        Includes every path registered with :class:`ChangeJournal` (the
        authoritative tracked publish set per ADR 0005) plus the version
        page and project index written by this publisher.  Paths outside
        *site_repo* are skipped defensively.

        Args:
            site_repo: Local site-repo checkout.
            version_file: The version page just written.
            project_index_file: The project section index just written.

        Returns:
            A list of repo-relative path strings in insertion order, with
            duplicates removed.
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


# ──────────────────────────── helpers ─────────────────────────────────────────


def _existing_date(version_file: Path) -> str | None:
    """Return the ``date:`` value from an existing version page, or ``None``.

    Reads the YAML front-matter of *version_file* (if it exists) and
    returns its ``date`` value as a string so the caller can re-emit a
    byte-identical page on an unchanged run.  Returns ``None`` when the
    file is absent, has no front-matter, or carries no ``date`` key.

    Args:
        version_file: The on-disk version page path.

    Returns:
        The preserved date string, or ``None``.
    """
    if not version_file.exists():
        return None
    try:
        text = version_file.read_text(encoding="utf-8")
    except OSError:
        return None
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return None
    try:
        front_matter = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    if not isinstance(front_matter, dict):
        return None
    date = front_matter.get("date")
    if date is None:
        return None
    # PyYAML may parse an unquoted ISO timestamp into a datetime; the
    # workflow supplies RFC3339 strings, so normalise back to isoformat.
    isoformat = getattr(date, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(date)


def _commit_message(
    project: str,
    board_rev: str,
    *,
    project_is_new: bool,
    version_is_new: bool,
    staged: list[str],
    site_profile: SiteProfile,
) -> str:
    """Derive the site-commit message prefix from what git staged.

    Args:
        project: Project basename (``<P>``).
        board_rev: Board revision (``<R>``).
        project_is_new: Whether the project section index did not exist.
        version_is_new: Whether the version page did not exist.
        staged: The repo-relative paths git has staged this run.
        site_profile: Profile providing ``assets_dir`` so asset changes
            can be told apart from markdown-only changes.

    Returns:
        The commit message string.
    """
    PR = f"{project}-{board_rev}"
    if project_is_new:
        return f"add: {project} {board_rev}"
    if version_is_new:
        return f"publish: {PR}"
    assets_prefix = f"{site_profile.assets_dir}/{project}/{board_rev}/"
    if any(name.startswith(assets_prefix) for name in staged):
        return f"republish: {PR}"
    return f"refresh: {PR} (metadata updated)"


def _atomic_write(path: Path, content: str) -> None:
    """Write *content* to *path* atomically via a sibling tempfile.

    Uses :func:`os.replace` for rename-into-place so partial writes never
    appear in ``git status`` (ADR 0005 § *Atomic per-file writes*).

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
