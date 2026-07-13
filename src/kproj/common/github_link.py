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
directory - every failure mode returns ``None`` so a publish never fails
because of this optional, best-effort enrichment. This includes
mechanical git failures (a subprocess timeout, or ``git`` being
missing/unusable): those are indistinguishable, from this module's
perspective, from "git said no" - both collapse to "omit the link".

Relatedly, :func:`_head_is_pushed` deliberately collapses two distinct
situations - "inconclusive" (no upstream configured, detached HEAD, or
a mechanical git failure) and "confirmed unpushed" (HEAD diverged from
a known upstream) - into the same ``False`` result. Both cases point to
the same conservative action (omit the link), so kproj does not need to
tell them apart.
"""

from __future__ import annotations

import re
from pathlib import Path

from .subprocess_runner import DEFAULT_GIT_TIMEOUT, SubprocessTimeoutError
from .subprocess_runner import run as subprocess_run

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

    Detection (local git metadata only; no network call):

    1. *project_dir* must be inside a git work tree.
    2. The ``origin`` remote must exist and resolve to a GitHub URL
       (see :func:`parse_github_remote_url`).
    3. ``HEAD`` must have a configured upstream (``@{u}``) whose commit
       matches ``HEAD`` exactly - i.e. the current commit is known
       (locally) to already be on the remote. No upstream, or a
       diverged/ahead ``HEAD``, is treated as "not (confirmed) pushed".

    Every failure mode - not a repo, no ``origin``, non-GitHub remote,
    no upstream, unpushed ``HEAD`` - returns ``None`` rather than
    raising, so publish never fails because of this optional enrichment.

    Args:
        project_dir: The resolved KiCad project directory.

    Returns:
        The canonical ``https://github.com/<owner>/<repo>`` URL, or
        ``None`` when the project isn't a pushed GitHub repo.
    """
    if not project_dir.is_dir():
        return None

    if not _is_git_work_tree(project_dir):
        return None

    remote_url = _git_output(project_dir, ["remote", "get-url", "origin"])
    if remote_url is None:
        return None

    github_url = parse_github_remote_url(remote_url)
    if github_url is None:
        return None

    if not _head_is_pushed(project_dir):
        return None

    return github_url


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
