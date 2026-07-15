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

from kproj.common import github_link as github_link_module
from kproj.common.github_link import (
    derive_github_link,
    derive_github_link_finding,
    parse_github_remote_url,
)
from kproj.common.subprocess_runner import SubprocessTimeoutError
from kproj.model.severity import Severity

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


def test_derive_github_link_returns_none_when_only_parent_directory_is_repo(
    tmp_path: Path,
) -> None:
    """A nested directory under a parent repo is not a project-local git repo."""
    workspace = tmp_path / "workspace"
    _init_repo(workspace)
    _git("remote", "add", "origin", "git@github.com:plocher/kproj.git", cwd=workspace)
    _seed_pushed_upstream(workspace)

    project_dir = workspace / "project"
    project_dir.mkdir(parents=True, exist_ok=True)
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


# ----------------------------------------------------------------------
# derive_github_link - never raises on mechanical git failures
# ----------------------------------------------------------------------


def test_derive_github_link_returns_none_on_subprocess_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A ``git`` invocation that times out yields ``None`` rather than raising.

    ``subprocess_runner.run(..., check=False)`` only suppresses non-zero
    exits - a timeout still raises :exc:`SubprocessTimeoutError` - so
    every git call in this module must catch it explicitly to honour the
    "publish never fails because of this enrichment" contract.
    """
    project_dir = tmp_path / "repo-slow-git"
    _init_repo(project_dir)

    def _raise_timeout(*args: object, **kwargs: object) -> None:
        raise SubprocessTimeoutError(["git", "rev-parse", "--is-inside-work-tree"], 30.0)

    monkeypatch.setattr(github_link_module, "subprocess_run", _raise_timeout)
    assert derive_github_link(project_dir) is None


def test_derive_github_link_returns_none_when_git_binary_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A missing/unusable ``git`` binary (``OSError``) yields ``None`` rather than raising."""
    project_dir = tmp_path / "repo-no-git-binary"
    _init_repo(project_dir)

    def _raise_oserror(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git: command not found")

    monkeypatch.setattr(github_link_module, "subprocess_run", _raise_oserror)
    assert derive_github_link(project_dir) is None


def test_derive_github_link_timeout_only_affects_head_pushed_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A timeout specifically during the pushed-check still yields ``None``, not a raise."""
    project_dir = tmp_path / "repo-timeout-on-pushed-check"
    _init_repo(project_dir)
    _git("remote", "add", "origin", "git@github.com:plocher/kproj.git", cwd=project_dir)
    _seed_pushed_upstream(project_dir)

    real_run = github_link_module.subprocess_run

    def _flaky_run(command: list[str], **kwargs: object) -> object:
        if "@{u}" in command:
            raise SubprocessTimeoutError(command, 30.0)
        return real_run(command, **kwargs)

    monkeypatch.setattr(github_link_module, "subprocess_run", _flaky_run)
    assert derive_github_link(project_dir) is None


# ----------------------------------------------------------------------
# derive_github_link_finding - absence-highlighting (kproj#30 clarified)
# ----------------------------------------------------------------------


def test_derive_github_link_finding_none_when_pushed(tmp_path: Path) -> None:
    """A pushed GitHub remote yields no advisory finding - nothing to advise."""
    project_dir = tmp_path / "repo-pushed"
    _init_repo(project_dir)
    _git("remote", "add", "origin", "git@github.com:plocher/kproj.git", cwd=project_dir)
    _seed_pushed_upstream(project_dir)
    assert derive_github_link_finding(project_dir) is None


def test_derive_github_link_finding_missing_for_non_repo(tmp_path: Path) -> None:
    """A plain (non-git) directory gets the 'no repo backing at all' finding."""
    project_dir = tmp_path / "not-a-repo"
    project_dir.mkdir()
    finding = derive_github_link_finding(project_dir, project="Demo")
    assert finding is not None
    assert finding.field == "github_link_missing"
    assert finding.severity is Severity.INFO
    assert finding.value == ""
    assert "not a Git repository" in finding.reason
    assert "git init" in finding.reason
    assert finding.project == "Demo"
    assert finding.source == "audit"


def test_derive_github_link_finding_missing_for_no_origin_remote(tmp_path: Path) -> None:
    """A git repo with no ``origin`` remote gets the 'no repo backing at all' finding."""
    project_dir = tmp_path / "repo-no-remote"
    _init_repo(project_dir)
    finding = derive_github_link_finding(project_dir)
    assert finding is not None
    assert finding.field == "github_link_missing"
    assert "no `origin` remote" in finding.reason
    assert "adding one" in finding.reason


def test_derive_github_link_finding_missing_for_non_github_remote(tmp_path: Path) -> None:
    """A pushed non-GitHub remote (e.g. GitLab) gets the 'no repo backing at all' finding."""
    project_dir = tmp_path / "repo-gitlab"
    _init_repo(project_dir)
    _git("remote", "add", "origin", "git@gitlab.com:plocher/kproj.git", cwd=project_dir)
    _seed_pushed_upstream(project_dir)
    finding = derive_github_link_finding(project_dir)
    assert finding is not None
    assert finding.field == "github_link_missing"


def test_derive_github_link_finding_unpushed_for_no_upstream(tmp_path: Path) -> None:
    """A GitHub remote with no upstream tracking gets the 'not pushed' finding."""
    project_dir = tmp_path / "repo-unpushed"
    _init_repo(project_dir)
    _git("remote", "add", "origin", "git@github.com:plocher/kproj.git", cwd=project_dir)
    finding = derive_github_link_finding(project_dir)
    assert finding is not None
    assert finding.field == "github_link_unpushed"
    assert finding.severity is Severity.INFO
    assert "push" in finding.reason
    assert finding.source == "audit"


def test_derive_github_link_finding_unpushed_for_ahead_head(tmp_path: Path) -> None:
    """HEAD ahead of the last-known pushed upstream ref gets the 'not pushed' finding."""
    project_dir = tmp_path / "repo-ahead"
    _init_repo(project_dir)
    _git("remote", "add", "origin", "git@github.com:plocher/kproj.git", cwd=project_dir)
    _seed_pushed_upstream(project_dir)
    (project_dir / "more.txt").write_text("more\n", encoding="utf-8")
    _git("add", "-A", cwd=project_dir)
    _git("commit", "-q", "-m", "more work", cwd=project_dir)
    finding = derive_github_link_finding(project_dir)
    assert finding is not None
    assert finding.field == "github_link_unpushed"


def test_derive_github_link_finding_distinguishes_missing_from_unpushed(tmp_path: Path) -> None:
    """The two advisory reasons use distinct field names and wording."""
    no_repo = derive_github_link_finding(tmp_path / "no-such-dir")
    unpushed_dir = tmp_path / "repo-unpushed-2"
    _init_repo(unpushed_dir)
    _git("remote", "add", "origin", "git@github.com:plocher/kproj.git", cwd=unpushed_dir)
    unpushed = derive_github_link_finding(unpushed_dir)
    assert no_repo is not None and unpushed is not None
    assert no_repo.field != unpushed.field
    assert no_repo.reason != unpushed.reason


def test_derive_github_link_finding_never_raises_on_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A git subprocess timeout still yields a (missing-backing) finding, not a raise."""
    project_dir = tmp_path / "repo-slow-git"
    _init_repo(project_dir)

    def _raise_timeout(*args: object, **kwargs: object) -> None:
        raise SubprocessTimeoutError(["git", "rev-parse", "--is-inside-work-tree"], 30.0)

    monkeypatch.setattr(github_link_module, "subprocess_run", _raise_timeout)
    finding = derive_github_link_finding(project_dir)
    assert finding is not None
    assert finding.field == "github_link_missing"
