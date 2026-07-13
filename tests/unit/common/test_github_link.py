"""Unit tests for :mod:`kproj.common.github_link`.

Covers URL derivation from every remote-URL shape kproj must recognise,
plus the three publish-time detection outcomes (pushed GitHub remote,
non-repo, unpushed). All git state is real (a throwaway repo under
``tmp_path``) but "pushed" is simulated via local-only git metadata
(a manually seeded ``refs/remotes/origin/<branch>`` + upstream config) so
no network call is ever made, per ``docs/DESIGN.md``'s "no network calls
required for detection" acceptance criterion.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from kproj.common.github_link import derive_github_link, parse_github_remote_url

# ----------------------------------------------------------------------
# parse_github_remote_url
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "remote_url,expected",
    [
        ("git@github.com:plocher/kproj.git", "https://github.com/plocher/kproj"),
        ("https://github.com/plocher/kproj.git", "https://github.com/plocher/kproj"),
        ("https://github.com/plocher/kproj", "https://github.com/plocher/kproj"),
        ("ssh://git@github.com/plocher/kproj.git", "https://github.com/plocher/kproj"),
        ("git@github.com:plocher/kproj", "https://github.com/plocher/kproj"),
        ("https://github.com/plocher/kproj/", "https://github.com/plocher/kproj"),
    ],
)
def test_parse_github_remote_url_recognised_shapes(remote_url: str, expected: str) -> None:
    """Every documented remote-URL shape resolves to the canonical repo-root URL."""
    assert parse_github_remote_url(remote_url) == expected


@pytest.mark.parametrize(
    "remote_url",
    [
        "git@gitlab.com:plocher/kproj.git",
        "https://bitbucket.org/plocher/kproj",
        "/local/path/to/repo.git",
        "",
    ],
)
def test_parse_github_remote_url_rejects_non_github(remote_url: str) -> None:
    """Non-GitHub (or unparsable) remote URLs return ``None``."""
    assert parse_github_remote_url(remote_url) is None


# ----------------------------------------------------------------------
# derive_github_link - git-state fixtures
# ----------------------------------------------------------------------


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(project_dir: Path) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", cwd=project_dir)
    _git("config", "user.email", "test@test.com", cwd=project_dir)
    _git("config", "user.name", "Test", cwd=project_dir)
    (project_dir / "README.md").write_text("hello\n", encoding="utf-8")
    _git("add", "-A", cwd=project_dir)
    _git("commit", "-q", "-m", "initial", cwd=project_dir)


def _seed_pushed_upstream(project_dir: Path, *, branch: str = "main") -> None:
    """Simulate "HEAD is pushed" using only local git metadata (no network).

    Renames the current branch to *branch*, seeds
    ``refs/remotes/origin/<branch>`` to point at the current HEAD commit,
    and configures the branch's upstream tracking - exactly the local
    state a real ``git push -u origin <branch>`` would leave behind.
    """
    _git("branch", "-M", branch, cwd=project_dir)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=project_dir, check=True, capture_output=True, text=True
    ).stdout.strip()
    _git("update-ref", f"refs/remotes/origin/{branch}", head, cwd=project_dir)
    _git("config", f"branch.{branch}.remote", "origin", cwd=project_dir)
    _git("config", f"branch.{branch}.merge", f"refs/heads/{branch}", cwd=project_dir)


def test_derive_github_link_returns_none_for_non_repo(tmp_path: Path) -> None:
    """A plain directory (no ``.git``) yields ``None``."""
    project_dir = tmp_path / "not-a-repo"
    project_dir.mkdir()
    assert derive_github_link(project_dir) is None


def test_derive_github_link_returns_none_without_origin_remote(tmp_path: Path) -> None:
    """A git repo with no ``origin`` remote yields ``None``."""
    project_dir = tmp_path / "repo-no-remote"
    _init_repo(project_dir)
    assert derive_github_link(project_dir) is None


def test_derive_github_link_returns_none_for_non_github_remote(tmp_path: Path) -> None:
    """A pushed, non-GitHub remote (e.g. GitLab) yields ``None``."""
    project_dir = tmp_path / "repo-gitlab"
    _init_repo(project_dir)
    _git("remote", "add", "origin", "git@gitlab.com:plocher/kproj.git", cwd=project_dir)
    _seed_pushed_upstream(project_dir)
    assert derive_github_link(project_dir) is None


def test_derive_github_link_returns_none_when_unpushed(tmp_path: Path) -> None:
    """A GitHub remote configured but HEAD not (yet) pushed yields ``None``."""
    project_dir = tmp_path / "repo-unpushed"
    _init_repo(project_dir)
    _git("remote", "add", "origin", "git@github.com:plocher/kproj.git", cwd=project_dir)
    # No upstream tracking configured at all - the common "never pushed" state.
    assert derive_github_link(project_dir) is None


def test_derive_github_link_returns_none_when_local_head_is_ahead(tmp_path: Path) -> None:
    """HEAD has local commits beyond the last-pushed upstream ref yields ``None``."""
    project_dir = tmp_path / "repo-ahead"
    _init_repo(project_dir)
    _git("remote", "add", "origin", "git@github.com:plocher/kproj.git", cwd=project_dir)
    _seed_pushed_upstream(project_dir)
    (project_dir / "more.txt").write_text("more\n", encoding="utf-8")
    _git("add", "-A", cwd=project_dir)
    _git("commit", "-q", "-m", "more work", cwd=project_dir)
    assert derive_github_link(project_dir) is None


def test_derive_github_link_returns_url_when_pushed_github_remote(tmp_path: Path) -> None:
    """A pushed GitHub remote yields the canonical repo-root URL."""
    project_dir = tmp_path / "repo-pushed"
    _init_repo(project_dir)
    _git("remote", "add", "origin", "git@github.com:plocher/kproj.git", cwd=project_dir)
    _seed_pushed_upstream(project_dir)
    assert derive_github_link(project_dir) == "https://github.com/plocher/kproj"


def test_derive_github_link_returns_none_for_missing_directory(tmp_path: Path) -> None:
    """A nonexistent directory yields ``None`` rather than raising."""
    assert derive_github_link(tmp_path / "no-such-dir") is None
