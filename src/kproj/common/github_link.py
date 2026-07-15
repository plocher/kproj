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
should see. :func:`finding_for_detection` surfaces this as a
non-fatal ``warning``-severity :class:`~kproj.model.finding.Finding`
(never raises, never blocks publish) whenever the link is absent,
with wording that distinguishes two situations:

- **no GitHub repo backing at all** (``field="github_link_missing"``) -
  not a git repo, no ``origin`` remote, or ``origin`` isn't GitHub.
- **GitHub repo backing exists but isn't (confirmed) pushed**
  (``field="github_link_unpushed"``) - covers no upstream tracking, a
  diverged/ahead ``HEAD``, and detached ``HEAD`` alike.

No finding is emitted when the link is present (status ``"pushed"``).

Single-evaluation guarantee: :func:`detect_github_link` is the only
function in this module that touches the filesystem/subprocess for a
given call. Both the front-matter ``github_url`` and the audit finding
MUST be derived from the *same* :class:`GithubLinkDetection` value by
construction - callers with access to the resolved project directory
(currently only :meth:`PublishWorkflow.run`) call
:func:`detect_github_link` exactly once per publish and thread the
result to both :attr:`GithubLinkDetection.url` (front-matter) and
:func:`finding_for_detection` (audit finding, a pure function with no
I/O of its own). :func:`derive_github_link` /
:func:`derive_github_link_finding` remain as convenience wrappers for
standalone callers (tests, one-off scripts) that don't need both
facets from a single evaluation; kproj's own publish pipeline does not
use them, to avoid two independent detection passes ever disagreeing.
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
"""Closed taxonomy of :func:`detect_github_link`'s outcome.

Only ``"pushed"`` yields a link; every other status is a reason to
omit it (and, via :func:`finding_for_detection`, to advise why).
"""


@dataclass(frozen=True)
class GithubLinkDetection:
    """Result of a single local-git-metadata detection pass over a project directory.

    Threading one :class:`GithubLinkDetection` value to every consumer
    (front-matter URL + audit finding) is what guarantees they can
    never disagree - there is exactly one detection per publish, not
    one per consumer.
    """

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


def detect_github_link(project_dir: Path) -> GithubLinkDetection:
    """Run the full local-git-metadata detection pass over *project_dir*.

    This is the **only** function in this module that touches the
    filesystem or spawns a subprocess. Callers that need both the URL
    and the advisory-finding facets (i.e. :meth:`PublishWorkflow.run`)
    must call this exactly once per publish and thread the returned
    :class:`GithubLinkDetection` to both :attr:`GithubLinkDetection.url`
    and :func:`finding_for_detection` - see the module docstring's
    *Single-evaluation guarantee*. Every failure mode - not a repo, no
    ``origin``, non-GitHub remote, unpushed ``HEAD``, or a mechanical
    git failure (subprocess timeout / missing binary) - resolves to a
    non-``"pushed"`` status rather than raising.

    Args:
        project_dir: The resolved KiCad project directory.

    Returns:
        A :class:`GithubLinkDetection` whose ``status`` is one of
        :data:`GithubLinkStatus`; ``url`` is set only when
        ``status == "pushed"``.
    """
    if not project_dir.is_dir():
        return GithubLinkDetection(status="not_a_repo")

    if not _is_git_work_tree(project_dir):
        return GithubLinkDetection(status="not_a_repo")

    remote_url = _git_output(project_dir, ["remote", "get-url", "origin"])
    if remote_url is None:
        return GithubLinkDetection(status="no_origin_remote")

    github_url = parse_github_remote_url(remote_url)
    if github_url is None:
        return GithubLinkDetection(status="non_github_remote")

    if not _head_is_pushed(project_dir):
        return GithubLinkDetection(status="not_pushed")

    return GithubLinkDetection(status="pushed", url=github_url)


def finding_for_detection(
    detection: GithubLinkDetection, *, project_dir: Path | str = "", project: str = ""
) -> Finding | None:
    """Return an advisory :class:`Finding` for an already-computed *detection*, or ``None``.

    Pure function - no filesystem or subprocess access - so it can be
    called as many times as convenient from a single
    :func:`detect_github_link` result without ever re-touching git.
    See :func:`derive_github_link_finding` for a detect-and-advise
    convenience wrapper when the caller doesn't already have a
    :class:`GithubLinkDetection` in hand.

    Args:
        detection: The result of a prior :func:`detect_github_link` call.
        project_dir: Optional path echoed into :attr:`Finding.value`
            for diagnostic context (empty string when not supplied).
        project: Project basename, threaded onto :attr:`Finding.project`
            when known (empty string otherwise).

    Returns:
        ``None`` when ``detection.status == "pushed"`` (the link is
        present, nothing to advise). Otherwise a ``warning``
        :class:`Finding` whose ``field`` is ``"github_link_missing"``
        (no GitHub repo backing at all) or ``"github_link_unpushed"``
        (backing exists, but isn't confirmed pushed).
    """
    if detection.status == "pushed":
        return None
    if detection.status == "not_pushed":
        return Finding(
            severity=Severity.INFO,
            field="github_link_unpushed",
            value="",
            reason=(
                "Project has a GitHub `origin`, but the current commit is not confirmed "
                "pushed there, so no links to a repo will be published. Push the current "
                "branch and run kproj again."
            ),
            project=project,
            source="audit",
        )
    reasons = {
        "not_a_repo": (
            "Project is not a Git repository, so no links to a repo will be published. "
            "You can run `git init` to start tracking this project."
        ),
        "no_origin_remote": (
            "Project is a Git repository with no `origin` remote, so no links to a repo "
            "will be published. Consider adding one that points to GitHub before publishing."
        ),
        "non_github_remote": (
            "Project `origin` is not hosted on GitHub, so no links to a repo will be "
            "published. Repository links only support GitHub."
        ),
    }
    return Finding(
        severity=Severity.INFO,
        field="github_link_missing",
        value="",
        reason=reasons.get(detection.status, reasons["not_a_repo"]),
        project=project,
        source="audit",
    )


def derive_github_link(project_dir: Path) -> str | None:
    """Detect-and-return the "see/fork on GitHub" link for *project_dir*, or ``None``.

    Convenience wrapper around :func:`detect_github_link` for standalone
    callers that only need the URL. kproj's own publish pipeline does
    NOT use this - it calls :func:`detect_github_link` once and reads
    :attr:`GithubLinkDetection.url` directly, so the URL and the
    advisory finding are always derived from the same detection pass.

    Args:
        project_dir: The resolved KiCad project directory.

    Returns:
        The canonical ``https://github.com/<owner>/<repo>`` URL, or
        ``None`` when the project isn't a pushed GitHub repo.
    """
    return detect_github_link(project_dir).url


def derive_github_link_finding(project_dir: Path, *, project: str = "") -> Finding | None:
    """Detect-and-advise in one call: see :func:`finding_for_detection`.

    Convenience wrapper around :func:`detect_github_link` +
    :func:`finding_for_detection` for standalone callers that only need
    the finding. kproj's own publish pipeline does NOT use this - see
    :func:`derive_github_link`'s docstring for why.

    Args:
        project_dir: The resolved KiCad project directory.
        project: Project basename, threaded onto :attr:`Finding.project`
            when known (empty string otherwise).

    Returns:
        See :func:`finding_for_detection`.
    """
    return finding_for_detection(
        detect_github_link(project_dir), project_dir=project_dir, project=project
    )


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
