"""Unit tests for the ``github_url`` wiring in :meth:`PublishWorkflow.build_publication`.

Pins DESIGN step 9's population of :attr:`Publication.github_url` from
:func:`kproj.common.github_link.derive_github_link` (kproj#30). Git state
is real (a throwaway repo under ``tmp_path``); "pushed" is simulated via
local-only git metadata so no network call is made — see
``tests/unit/common/test_github_link.py`` for the detection-logic tests
themselves.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from kproj.application.publish_workflow import PublishWorkflow
from kproj.common import github_link as github_link_module
from kproj.common.subprocess_runner import SubprocessTimeoutError
from kproj.model.analysis_info import AnalysisInfo
from kproj.model.project_info import ProjectInfo, Status
from kproj.model.resolved_project import ResolvedProject

_TESTS_ROOT = Path(__file__).resolve().parents[2]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from _kicad_fixtures import make_minimal_project  # noqa: E402 - path setup above


def _project_info(basename: str = "demo") -> ProjectInfo:
    return ProjectInfo(
        project=basename,
        title=basename,
        company="MRCS",
        design_rev="1.0",
        board_rev="1.0",
        date="2026.06",
        designer="Alice Designer",
        tagline="t",
        overview="o",
        status=Status.ACTIVE,
    )


def _resolved(project_dir: Path, basename: str = "demo") -> ResolvedProject:
    return ResolvedProject(
        project_file=project_dir / f"{basename}.kicad_pro",
        project_dir=project_dir,
        pcb_file=project_dir / f"{basename}.kicad_pcb",
        root_schematic=project_dir / f"{basename}.kicad_sch",
        hierarchical_schematics=(project_dir / f"{basename}.kicad_sch",),
    )


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _make_pushed_github_repo(project_dir: Path) -> None:
    """Turn *project_dir* into a repo with a "pushed" GitHub origin (no network)."""
    _git("init", "-q", cwd=project_dir)
    _git("config", "user.email", "test@test.com", cwd=project_dir)
    _git("config", "user.name", "Test", cwd=project_dir)
    _git("add", "-A", cwd=project_dir)
    _git("commit", "-q", "-m", "initial", cwd=project_dir)
    _git("branch", "-M", "main", cwd=project_dir)
    _git("remote", "add", "origin", "git@github.com:plocher/demo.git", cwd=project_dir)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=project_dir, check=True, capture_output=True, text=True
    ).stdout.strip()
    _git("update-ref", "refs/remotes/origin/main", head, cwd=project_dir)
    _git("config", "branch.main.remote", "origin", cwd=project_dir)
    _git("config", "branch.main.merge", "refs/heads/main", cwd=project_dir)


def test_build_publication_github_url_defaults_to_empty(tmp_path: Path) -> None:
    """A project directory that is not a git repo yields an empty github_url."""
    project = make_minimal_project(tmp_path / "demo", "demo")
    publication = PublishWorkflow.build_publication(
        _resolved(project),
        _project_info(),
        AnalysisInfo(findings=()),
    )
    assert publication.github_url == ""


def test_build_publication_populates_github_url_when_pushed(tmp_path: Path) -> None:
    """A pushed GitHub-remote project directory populates github_url."""
    project = make_minimal_project(tmp_path / "demo", "demo")
    _make_pushed_github_repo(project)
    publication = PublishWorkflow.build_publication(
        _resolved(project),
        _project_info(),
        AnalysisInfo(findings=()),
    )
    assert publication.github_url == "https://github.com/plocher/demo"


def test_build_publication_github_url_empty_when_unpushed(tmp_path: Path) -> None:
    """A GitHub remote configured but never pushed yields an empty github_url."""
    project = make_minimal_project(tmp_path / "demo", "demo")
    _git("init", "-q", cwd=project)
    _git("config", "user.email", "test@test.com", cwd=project)
    _git("config", "user.name", "Test", cwd=project)
    _git("add", "-A", cwd=project)
    _git("commit", "-q", "-m", "initial", cwd=project)
    _git("remote", "add", "origin", "git@github.com:plocher/demo.git", cwd=project)
    publication = PublishWorkflow.build_publication(
        _resolved(project),
        _project_info(),
        AnalysisInfo(findings=()),
    )
    assert publication.github_url == ""


def test_build_publication_survives_github_detection_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A ``git`` timeout during GitHub-link detection must not fail the publish.

    Regression test: ``derive_github_link`` must catch
    :exc:`SubprocessTimeoutError` internally rather than letting it
    propagate through ``build_publication`` - a slow/hung ``git`` must
    only omit the (best-effort) link, never abort the publish.
    """
    project = make_minimal_project(tmp_path / "demo", "demo")
    _make_pushed_github_repo(project)

    def _raise_timeout(*args: object, **kwargs: object) -> None:
        raise SubprocessTimeoutError(["git", "rev-parse", "--is-inside-work-tree"], 30.0)

    monkeypatch.setattr(github_link_module, "subprocess_run", _raise_timeout)

    publication = PublishWorkflow.build_publication(
        _resolved(project),
        _project_info(),
        AnalysisInfo(findings=()),
    )
    assert publication.github_url == ""
