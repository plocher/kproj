"""Detection of a project's "see/fork on GitHub" link (kproj#30).

A KiCad project directory is often itself a git repository, independent
of the SPCoast site repo kproj publishes into. When that project repo
has a GitHub ``origin`` remote and the currently-published commit is
already pushed there, kproj surfaces a link so a site visitor can view
or fork the source. Detection uses **local git metadata only** - no
``git fetch`` / network call - per the kproj#30 acceptance criterion, so
a stale local view of the remote can only make the feature conservative
(omit the link), never wrong (link to content that isn't really there).

Locked decisions for the open design points in kproj#30 (see
``docs/DESIGN.md`` § *GitHub project link*):

- Only the ``origin`` remote is considered when several exist.
- The link targets the repo root (``https://github.com/<owner>/<repo>``),
  not a tree/branch-specific URL - stable across board revisions.
- "Unpushed" (no upstream tracking, or local ``HEAD`` ahead of the
  last-known upstream ref) omits the link entirely rather than
  downgrading to a repo-root link, since kproj cannot locally confirm
  the pushed remote actually contains a GitHub repo at all in that case
  (a repo-root link could be issued for a same-named-but-unrelated
  GitHub repo if ``origin`` were merely configured but never pushed to).

This module never raises for a non-repo / non-GitHub / unpushed project
directory - every failure mode returns ``None`` (or, for
:func:`derive_github_link_finding`, a non-fatal advisory ``Finding``)
so a publish never fails because of this optional, best-effort
enrichment. This includes mechanical git failures (a subprocess
timeout, or ``git`` being missing/unusable): those are
indistinguishable, from this module's perspective, from "git said no" -
both collapse to "omit the link".

Relatedly, :func:`_head_is_pushed` deliberately collapses two distinct
situations - "inconclusive" (no upstream configured, detached HEAD, or
a mechanical git failure) and "confirmed unpushed" (HEAD diverged from
a known upstream) - into the same ``False`` result. Both cases point to
the same conservative action (omit the link), so kproj does not need to
tell them apart.

Absence-highlighting (kproj#30 clarified requirement): the old
EAGLE-era site linked every project to its GitHub repo, so a KiCad
project silently missing that backing is a regression the maintainer
should see. :func:`derive_github_link_finding` surfaces this as a
non-fatal ``warning``-severity :class:`~kproj.model.finding.Finding`
(never raises, never blocks publish) whenever the link is absent,
with wording that distinguishes two situations:

- **no GitHub repo backing at all** (``field="github_link_missing"``) -
  not a git repo, no ``origin`` remote, or ``origin`` isn't GitHub.
- **GitHub repo backing exists but isn't (confirmed) pushed**
  (``field="github_link_unpushed"``) - covers no upstream tracking, a
  diverged/ahead ``HEAD``, and detached ``HEAD`` alike.

No finding is emitted when the link is present (status ``"pushed"``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..model.finding import Finding
from ..model.severity import Severity
from .subprocess_runner import DEFAULT_GIT_TIMEOUT, SubprocessTimeoutError
from .subprocess_runner import run as subprocess_run

GithubLinkStatus = Literal[
    "pushed", "not_a_repo", "no_origin_remote", "non_github_remote", "not_pushed"
]
"""Closed taxonomy of :func:`_detect`'s outcome.

Only ``"pushed"`` yields a link; every other status is a reason to
omit it (and, via :func:`derive_github_link_finding`, to advise why).
"""


@dataclass(frozen=True)
class _Detection:
    """Internal result of a single detection pass over *project_dir*."""

    status: GithubLinkStatus
    url: str | None = None


# subprocess_run(..., check=False) only suppresses non-zero exits - a
# timeout still raises SubprocessTimeoutError, and a missing/unusable
# ``git`` binary raises OSError (e.g. FileNotFoundError). Every git
# invocation in this module is wrapped to catch both, so a slow or
# broken git can only make link detection conservative (no link),
# never abort a publish.
_GIT_INVOCATION_ERRORS: tuple[type[Exception], ...] = (SubprocessTimeoutError, OSError)

# Matches (with an optional ``.git`` suffix and optional trailing slash):
#   git@github.com:owner/repo(.git)?
#   ssh://git@github.com/owner/repo(.git)?
#   https://github.com/owner/repo(.git)?
_GITHUB_REMOTE_RE = re.compile(
    r"^(?:https?://|ssh://)?(?:[^@/]+@)?github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$"
)


def parse_github_remote_url(remote_url: str) -> str | None:
    """Return the canonical ``https://github.com/<owner>/<repo>`` URL, or ``None``.

    Recognises the SSH shorthand (``git@github.com:owner/repo.git``),
    ``ssh://`` URLs, and ``https://`` URLs, each with or without a
    trailing ``.git`` / ``/``. Any remote whose host is not
    ``github.com`` (or that doesn't parse at all) returns ``None``.

    Args:
        remote_url: The raw ``git remote get-url`` output.

    Returns:
        The repo-root GitHub URL, or ``None`` when *remote_url* is not a
        recognisable GitHub remote.
    """
    match = _GITHUB_REMOTE_RE.match(remote_url.strip())
    if match is None:
        return None
    owner, repo = match.group(1), match.group(2)
    if not owner or not repo:
        return None
    return f"https://github.com/{owner}/{repo}"


def derive_github_link(project_dir: Path) -> str | None:
    """Return the "see/fork on GitHub" link for *project_dir*, or ``None``.

    Detection (local git metadata only; no network call) - see
    :func:`_detect` for the full status taxonomy. Every failure mode -
    not a repo, no ``origin``, non-GitHub remote, unpushed ``HEAD`` -
    returns ``None`` rather than raising, so publish never fails
    because of this optional enrichment.

    Args:
        project_dir: The resolved KiCad project directory.

    Returns:
        The canonical ``https://github.com/<owner>/<repo>`` URL, or
        ``None`` when the project isn't a pushed GitHub repo.
    """
    return _detect(project_dir).url


def derive_github_link_finding(project_dir: Path, *, project: str = "") -> Finding | None:
    """Return an advisory :class:`Finding` when the GitHub link is absent, or ``None``.

    Absence-highlighting (kproj#30 clarified requirement): the old
    EAGLE-era site linked every project to its GitHub repo; kproj
    surfaces the gap as a non-fatal ``warning`` finding (``source``
    ``"audit"``, so it renders in the existing Metadata Audit table and
    counts without any new rendering work) rather than silently
    omitting the link. Never raises, and never returned when the link
    is present - a project can only be advised about a genuine gap.

    Args:
        project_dir: The resolved KiCad project directory.
        project: Project basename, threaded onto :attr:`Finding.project`
            when known (empty string otherwise).

    Returns:
        ``None`` when *project_dir* is a pushed GitHub repo (the link
        is present, nothing to advise). Otherwise a ``warning``
        :class:`Finding` whose ``field`` is ``"github_link_missing"``
        (no GitHub repo backing at all) or ``"github_link_unpushed"``
        (backing exists, but isn't confirmed pushed).
    """
    detection = _detect(project_dir)
    if detection.status == "pushed":
        return None
    if detection.status == "not_pushed":
        return Finding(
            severity=Severity.WARNING,
            field="github_link_unpushed",
            value=str(project_dir),
            reason=(
                "project directory has a GitHub `origin` remote configured, but the "
                "current commit isn't confirmed pushed there (no upstream tracking, a "
                "diverged/ahead HEAD, or a detached HEAD); the see/fork-on-GitHub link "
                "is omitted until a push is confirmed"
            ),
            project=project,
            source="audit",
        )
    return Finding(
        severity=Severity.WARNING,
        field="github_link_missing",
        value=str(project_dir),
        reason=(
            "project directory has no GitHub repo backing (not a git repo, no `origin` "
            "remote, or `origin` isn't a GitHub remote); the see/fork-on-GitHub link is "
            "omitted"
        ),
        project=project,
        source="audit",
    )


def _detect(project_dir: Path) -> _Detection:
    """Run the full local-git-metadata detection pass over *project_dir*.

    Shared by :func:`derive_github_link` (wants just the URL) and
    :func:`derive_github_link_finding` (wants the reason it's absent).
    Running this only once per call keeps the two consumers' local git
    reads consistent with each other within a single publish.

    Returns:
        A :class:`_Detection` whose ``status`` is one of
        :data:`GithubLinkStatus`; ``url`` is set only when
        ``status == "pushed"``.
    """
    if not project_dir.is_dir():
        return _Detection(status="not_a_repo")

    if not _is_git_work_tree(project_dir):
        return _Detection(status="not_a_repo")

    remote_url = _git_output(project_dir, ["remote", "get-url", "origin"])
    if remote_url is None:
        return _Detection(status="no_origin_remote")

    github_url = parse_github_remote_url(remote_url)
    if github_url is None:
        return _Detection(status="non_github_remote")

    if not _head_is_pushed(project_dir):
        return _Detection(status="not_pushed")

    return _Detection(status="pushed", url=github_url)


def _is_git_work_tree(project_dir: Path) -> bool:
    """Return whether *project_dir* is inside a git work tree."""
    try:
        result = subprocess_run(
            ["git", "-C", str(project_dir), "rev-parse", "--is-inside-work-tree"],
            timeout=DEFAULT_GIT_TIMEOUT,
            check=False,
        )
    except _GIT_INVOCATION_ERRORS:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _head_is_pushed(project_dir: Path) -> bool:
    """Return whether local ``HEAD`` matches its configured upstream ref.

    Uses only refs already present locally (``@{u}``) - never fetches.
    ``False`` when there is no upstream configured, or the two commits
    differ (local commits not yet pushed, or a diverged history).
    """
    upstream = _git_output(project_dir, ["rev-parse", "@{u}"])
    if upstream is None:
        return False
    head = _git_output(project_dir, ["rev-parse", "HEAD"])
    if head is None:
        return False
    return head == upstream


def _git_output(project_dir: Path, args: list[str]) -> str | None:
    """Run a git sub-command and return its trimmed stdout, or ``None`` on failure.

    ``None`` covers every failure mode uniformly - a non-zero exit, a
    subprocess timeout, or an unusable ``git`` binary (:data:`_GIT_INVOCATION_ERRORS`) -
    so callers can't distinguish "git said no" from "git couldn't even
    run"; both are equally reasons to omit the (best-effort) link
    rather than raise.
    """
    try:
        result = subprocess_run(
            ["git", "-C", str(project_dir), *args],
            timeout=DEFAULT_GIT_TIMEOUT,
            check=False,
        )
    except _GIT_INVOCATION_ERRORS:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()
