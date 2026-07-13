"""Step definitions for ``github_link.feature`` (kproj#30).

Reuses the ``publish_steps.py`` infrastructure (``context.proj_dir`` /
``context.site_repo`` / ``_run_workflow``) so these scenarios exercise
the full publish pipeline, not just the isolated detection function.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from behave import given, then  # type: ignore[import-untyped]

from kproj.config import GENERIC_SITE_PROFILE

_VDIR = GENERIC_SITE_PROFILE.versions_dir


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _git_output(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def _init_repo(project_dir: Path) -> None:
    _git("init", "-q", cwd=project_dir)
    _git("config", "user.email", "test@test.com", cwd=project_dir)
    _git("config", "user.name", "Test", cwd=project_dir)
    _git("add", "-A", cwd=project_dir)
    _git("commit", "-q", "-m", "initial", cwd=project_dir)


@given("the project directory is a git repo with a pushed GitHub remote")
def step_given_pushed_github_remote(context: Any) -> None:
    """Seed local-only git metadata simulating a pushed GitHub origin (no network)."""
    project_dir = context.proj_dir
    _init_repo(project_dir)
    _git("branch", "-M", "main", cwd=project_dir)
    _git("remote", "add", "origin", "git@github.com:plocher/MyProject.git", cwd=project_dir)
    head = _git_output("rev-parse", "HEAD", cwd=project_dir)
    _git("update-ref", "refs/remotes/origin/main", head, cwd=project_dir)
    _git("config", "branch.main.remote", "origin", cwd=project_dir)
    _git("config", "branch.main.merge", "refs/heads/main", cwd=project_dir)


@given("the project directory is a git repo with a GitHub remote but no upstream tracking")
def step_given_no_upstream_tracking(context: Any) -> None:
    """A GitHub origin is configured, but no upstream tracking is set (never pushed)."""
    project_dir = context.proj_dir
    _init_repo(project_dir)
    _git("remote", "add", "origin", "git@github.com:plocher/MyProject.git", cwd=project_dir)


@given(
    "the project directory is a git repo with a GitHub remote but local commits ahead of upstream"
)
def step_given_ahead_of_upstream(context: Any) -> None:
    """Upstream tracking is configured, but HEAD has diverged (local commits not pushed)."""
    project_dir = context.proj_dir
    _init_repo(project_dir)
    _git("branch", "-M", "main", cwd=project_dir)
    _git("remote", "add", "origin", "git@github.com:plocher/MyProject.git", cwd=project_dir)
    head = _git_output("rev-parse", "HEAD", cwd=project_dir)
    _git("update-ref", "refs/remotes/origin/main", head, cwd=project_dir)
    _git("config", "branch.main.remote", "origin", cwd=project_dir)
    _git("config", "branch.main.merge", "refs/heads/main", cwd=project_dir)
    # Add a local-only commit so HEAD is ahead of the last-known upstream ref.
    (project_dir / "WIP.txt").write_text("work in progress\n", encoding="utf-8")
    _git("add", "-A", cwd=project_dir)
    _git("commit", "-q", "-m", "unpushed work", cwd=project_dir)


@given("the project directory is a git repo with a pushed GitHub remote but checked out detached")
def step_given_detached_head(context: Any) -> None:
    """HEAD is detached (not on any branch), so there is no ``@{u}`` to resolve at all."""
    project_dir = context.proj_dir
    _init_repo(project_dir)
    _git("branch", "-M", "main", cwd=project_dir)
    _git("remote", "add", "origin", "git@github.com:plocher/MyProject.git", cwd=project_dir)
    head = _git_output("rev-parse", "HEAD", cwd=project_dir)
    _git("update-ref", "refs/remotes/origin/main", head, cwd=project_dir)
    _git("config", "branch.main.remote", "origin", cwd=project_dir)
    _git("config", "branch.main.merge", "refs/heads/main", cwd=project_dir)
    _git("checkout", "-q", head, cwd=project_dir)


def _version_file_content(context: Any) -> str:
    project_name = getattr(context, "project_name", "MyProject")
    version_file = context.site_repo / _VDIR / project_name / "1.0.md"
    assert version_file.exists(), f"version file not found: {version_file}"
    return version_file.read_text(encoding="utf-8")


@then("the version page front-matter includes the GitHub link")
def step_then_github_link_present(context: Any) -> None:
    content = _version_file_content(context)
    assert "github_url: https://github.com/plocher/MyProject" in content, (
        f"expected github_url in front-matter:\n{content[:800]}"
    )


@then("the version page front-matter has no GitHub link")
def step_then_no_github_link(context: Any) -> None:
    content = _version_file_content(context)
    assert "github_url" not in content, f"unexpected github_url in front-matter:\n{content[:800]}"
