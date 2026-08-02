"""Site-management workflow for project listing and delete operations."""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path

from ..common.subprocess_runner import (
    DEFAULT_GIT_TIMEOUT,
    SubprocessFailedError,
    SubprocessTimeoutError,
)
from ..common.subprocess_runner import run as subprocess_run
from ..config import KprojConfig, SiteProfile
from ..model.site_management import (
    DeleteOutcome,
    DeleteRequest,
    DeleteResult,
    ProjectListResult,
    PublishedProject,
)
from ..services.change_journal import ChangeJournal

_EMPTY_VERSIONS_SECTION_INDEX = """---
title: KiCad Projects
---
No published projects found.
"""


def _git_run(
    cmd: list[str],
    *,
    site_repo: Path,
    check: bool = True,
) -> None:
    """Run a git sub-command against *site_repo*."""
    subprocess_run(
        ["git", "-C", str(site_repo), *cmd],
        timeout=DEFAULT_GIT_TIMEOUT,
        check=check,
    )


def _git_staged_names(site_repo: Path) -> list[str]:
    """Return the repo-relative paths currently staged in git."""
    result = subprocess_run(
        ["git", "-C", str(site_repo), "diff", "--cached", "--name-only"],
        timeout=DEFAULT_GIT_TIMEOUT,
        check=False,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _git_pending_push_count(site_repo: Path) -> int | None:
    """Return commit count ahead of upstream, or ``None`` when unknown."""
    try:
        result = subprocess_run(
            ["git", "-C", str(site_repo), "rev-list", "--count", "@{u}..HEAD"],
            timeout=DEFAULT_GIT_TIMEOUT,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


class SiteManagementWorkflow:
    """List and delete published project content in the configured site repository."""

    def list_projects(
        self, config: KprojConfig, *, project: str | None = None
    ) -> ProjectListResult:
        """Return published project/version shape from the site repo.

        Args:
            config: Effective runtime configuration.
            project: Optional project identifier to scope listing to one project.
                When omitted, all published projects are listed.
        """
        projects = _discover_published_projects(config.site_repo, config.site_profile)
        if not projects:
            return ProjectListResult(exit_code=0, message="No published projects found.")
        if project is not None:
            selected = _resolve_project(projects, project)
            if selected is None:
                return ProjectListResult(
                    exit_code=2,
                    message=f"Error: project {project!r} was not found in published site content.",
                )
            projects = (selected,)
        blocks = [_render_project_line(published) for published in projects]
        return ProjectListResult(exit_code=0, message="\n".join(blocks))

    def delete(self, request: DeleteRequest) -> DeleteResult:
        """Delete published content according to the request semantics."""
        projects = _discover_published_projects(
            request.config.site_repo, request.config.site_profile
        )
        published = _resolve_project(projects, request.project)
        if published is None:
            return DeleteResult(
                outcome="failed",
                exit_code=2,
                message=f"Error: project {request.project!r} was not found in published site content.",
            )
        if request.version is not None:
            return self._delete_version(request, published)
        return self._delete_project(request, published)

    def _delete_version(self, request: DeleteRequest, published: PublishedProject) -> DeleteResult:
        """Delete one version from a project, with last-version force escalation."""
        version = request.version
        assert version is not None  # guarded by caller
        if version not in published.versions:
            return DeleteResult(
                outcome="failed",
                exit_code=2,
                message=(
                    f"Error: version {version!r} was not found for project {published.project!r}. "
                    f"Available versions: {_format_versions(published.versions)}"
                ),
            )
        if len(published.versions) == 1:
            if not request.force:
                return DeleteResult(
                    outcome="failed",
                    exit_code=2,
                    message=(
                        f"Error: {published.project!r} has one published version ({version}). "
                        "Use --force to delete the full project."
                    ),
                    deleted_versions=(version,),
                )
            return self._delete_project(request, published)
        site_repo = request.config.site_repo
        profile = request.config.site_profile
        version_file = profile.version_page_path(site_repo, published.project, version)
        asset_dir = site_repo / profile.assets_dir / published.project / version
        targets = _existing_paths((version_file, asset_dir))
        if not targets:
            return DeleteResult(
                outcome="failed",
                exit_code=2,
                message=(
                    f"Error: no deletable files found for {published.project!r} version {version!r}. "
                    "The site state may already be pruned."
                ),
            )
        if request.dry_run:
            return DeleteResult(
                outcome="preview",
                exit_code=0,
                message=_dry_run_message(
                    f"Would delete version {published.project}-{version}.",
                    targets,
                    site_repo,
                ),
                deleted_versions=(version,),
            )
        return self._execute_delete(
            request=request,
            targets=targets,
            commit_message=f"delete version {version}",
            success_message=f"Info: Deleted version {published.project}-{version}.",
            outcome="deleted-version",
            deleted_versions=(version,),
        )

    def _delete_project(self, request: DeleteRequest, published: PublishedProject) -> DeleteResult:
        """Delete all published content for a project (force-gated)."""
        site_repo = request.config.site_repo
        profile = request.config.site_profile
        versions_dir = site_repo / profile.versions_dir / published.project
        assets_dir = site_repo / profile.assets_dir / published.project
        targets = _existing_paths((versions_dir, assets_dir))
        if not targets:
            return DeleteResult(
                outcome="failed",
                exit_code=2,
                message=f"Error: no published content found for project {published.project!r}.",
            )
        versions_summary = _format_versions(published.versions)
        if not request.force:
            return DeleteResult(
                outcome="failed",
                exit_code=2,
                message="\n".join(
                    [
                        f"Error: refusing to delete project {published.project!r} without --force.",
                        f"Would delete versions: {versions_summary}",
                        _would_remove_lines(targets, site_repo),
                    ]
                ),
                deleted_versions=published.versions,
            )
        if request.dry_run:
            return DeleteResult(
                outcome="preview",
                exit_code=0,
                message=_dry_run_message(
                    f"Would delete project {published.project} (versions: {versions_summary}).",
                    targets,
                    site_repo,
                ),
                deleted_versions=published.versions,
            )
        return self._execute_delete(
            request=request,
            targets=targets,
            commit_message=f"delete project {versions_summary}",
            success_message=(
                f"Info: Deleted project {published.project} (versions: {versions_summary})."
            ),
            outcome="deleted-project",
            deleted_versions=published.versions,
        )

    def _execute_delete(
        self,
        *,
        request: DeleteRequest,
        targets: tuple[Path, ...],
        commit_message: str,
        success_message: str,
        outcome: DeleteOutcome,
        deleted_versions: tuple[str, ...],
    ) -> DeleteResult:
        """Apply deletions, commit them, and optionally push the site repo."""
        site_repo = request.config.site_repo
        try:
            with ChangeJournal(site_repo, dry_run=False) as journal:
                _register_paths_for_delete(journal, targets)
                _delete_paths(targets)
                section_index = _ensure_versions_section_index_if_empty(
                    site_repo, request.config.site_profile
                )
                if section_index is not None:
                    journal.will_modify(section_index)
                stage_targets = targets if section_index is None else (*targets, section_index)
                staged = _stage_paths_for_delete(site_repo, stage_targets)
                if not staged:
                    return DeleteResult(
                        outcome="failed",
                        exit_code=2,
                        message="Error: delete operation produced no staged git changes.",
                    )
                _git_run(["commit", "-m", commit_message], site_repo=site_repo)
                journal.mark_committed()
                debt_note = ""
                pending = _git_pending_push_count(site_repo)
                if pending and not request.config.no_push:
                    _git_run(["push"], site_repo=site_repo)
                    journal.mark_pushed()
                elif pending:
                    debt_note = f"\nNote: site repo has {pending} unpushed commit(s) (--no-push)."
                return DeleteResult(
                    outcome=outcome,
                    exit_code=0,
                    message=f"{success_message}{debt_note}",
                    deleted_versions=deleted_versions,
                )
        except (OSError, SubprocessFailedError, SubprocessTimeoutError) as exc:
            return DeleteResult(
                outcome="failed",
                exit_code=2,
                message=f"Error: delete operation failed: {exc}",
                deleted_versions=deleted_versions,
            )


def _discover_published_projects(
    site_repo: Path, site_profile: SiteProfile
) -> tuple[PublishedProject, ...]:
    """Discover published projects from version-page and asset directory roots."""
    versions_root = site_repo / site_profile.versions_dir
    assets_root = site_repo / site_profile.assets_dir
    project_names: set[str] = set()
    if versions_root.is_dir():
        project_names.update(path.name for path in versions_root.iterdir() if path.is_dir())
    if assets_root.is_dir():
        project_names.update(path.name for path in assets_root.iterdir() if path.is_dir())
    projects: list[PublishedProject] = []
    for project_name in sorted(project_names, key=_natural_sort_key):
        project_versions_dir = versions_root / project_name
        versions: tuple[str, ...] = ()
        if project_versions_dir.is_dir():
            versions = tuple(
                sorted(
                    [
                        path.stem
                        for path in project_versions_dir.glob("*.md")
                        if path.is_file() and path.stem != "_index"
                    ],
                    key=_natural_sort_key,
                )
            )
        projects.append(PublishedProject(project=project_name, versions=versions))
    return tuple(projects)


def _resolve_project(projects: Sequence[PublishedProject], project: str) -> PublishedProject | None:
    """Resolve *project* by exact match, then unique case-insensitive match."""
    for published in projects:
        if published.project == project:
            return published
    folded = [
        published for published in projects if published.project.casefold() == project.casefold()
    ]
    if len(folded) == 1:
        return folded[0]
    return None


def _existing_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    """Return existing paths, deduplicated in first-seen order."""
    ordered: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if not path.exists() or path in seen:
            continue
        seen.add(path)
        ordered.append(path)
    return tuple(ordered)


def _register_paths_for_delete(journal: ChangeJournal, paths: Sequence[Path]) -> None:
    """Record all existing files under *paths* as modifications."""
    for path in _sorted_paths_for_deletion(paths):
        if path.is_file():
            journal.will_modify(path)
            continue
        if path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    journal.will_modify(child)


def _delete_paths(paths: Sequence[Path]) -> None:
    """Delete each path in descending-length order so children go first."""
    for path in _sorted_paths_for_deletion(paths):
        if path.is_file():
            path.unlink(missing_ok=True)
            continue
        if path.is_dir():
            shutil.rmtree(path)


def _sorted_paths_for_deletion(paths: Sequence[Path]) -> tuple[Path, ...]:
    """Return deduplicated paths sorted deepest-first for safe removal."""
    deduped: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return tuple(sorted(deduped, key=lambda path: len(path.parts), reverse=True))


def _ensure_versions_section_index_if_empty(
    site_repo: Path, site_profile: SiteProfile
) -> Path | None:
    """Create a root section index when no published projects remain."""
    if _discover_published_projects(site_repo, site_profile):
        return None
    section_index = site_repo / site_profile.versions_dir / "_index.md"
    if section_index.exists():
        return None
    section_index.parent.mkdir(parents=True, exist_ok=True)
    section_index.write_text(_EMPTY_VERSIONS_SECTION_INDEX, encoding="utf-8")
    return section_index


def _stage_paths_for_delete(site_repo: Path, paths: Sequence[Path]) -> list[str]:
    """Stage deleted paths via ``git add -A`` and return staged file names."""
    rel_paths: list[str] = []
    seen: set[str] = set()
    for path in paths:
        try:
            rel = str(path.relative_to(site_repo))
        except ValueError:
            continue
        if rel in seen:
            continue
        seen.add(rel)
        rel_paths.append(rel)
    if not rel_paths:
        return []
    _git_run(["add", "-A", *rel_paths], site_repo=site_repo)
    return _git_staged_names(site_repo)


def _dry_run_message(summary: str, paths: Sequence[Path], site_repo: Path) -> str:
    """Return a dry-run summary plus the list of paths that would be removed."""
    return "\n".join([f"Note: --dry-run only. {summary}", _would_remove_lines(paths, site_repo)])


def _would_remove_lines(paths: Sequence[Path], site_repo: Path) -> str:
    """Format a bullet list of delete targets relative to the site repo root."""
    lines = ["Would remove:"]
    for path in paths:
        try:
            rendered = str(path.relative_to(site_repo))
        except ValueError:
            rendered = str(path)
        lines.append(f"- {rendered}")
    return "\n".join(lines)


def _format_versions(versions: Sequence[str]) -> str:
    """Render version identifiers for user-facing status and commit text."""
    if not versions:
        return "<none>"
    return ", ".join(versions)


_NATURAL_PARTS_RE = re.compile(r"(\d+)")
"""Split strings into text/number chunks for natural ordering."""


def _natural_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """Return a case-insensitive natural sort key for *value*.

    Each chunk is tagged so same-index elements stay comparable across mixed
    version schemas (e.g. ``1.0A`` vs ``A``). Numeric chunks sort before text
    chunks at the same position: ``(0, int)`` then ``(1, str)``.
    """
    parts = _NATURAL_PARTS_RE.split(value.casefold())
    key: list[tuple[int, int | str]] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part))
    return tuple(key)


def _render_project_line(project: PublishedProject) -> str:
    """Render a one-line project summary: ``<project> [v1, v2]``."""
    versions = ", ".join(project.versions)
    return f"{project.project} [{versions}]"
