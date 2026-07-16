"""Unit tests for :mod:`kproj.application.site_management_workflow`."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from kproj.application.site_management_workflow import SiteManagementWorkflow
from kproj.config import KprojConfig, SiteProfile
from kproj.model.site_management import DeleteRequest

_TEST_PROFILE = SiteProfile(
    name="test",
    versions_dir="content/versions",
    assets_dir="static/versions",
    layout_field=None,
)


def _config(site_repo: Path, *, no_push: bool = True) -> KprojConfig:
    return KprojConfig(
        site_repo=site_repo,
        no_push=no_push,
        kicad_cli=None,
        site_profile=_TEST_PROFILE,
    )


def _seed_project(site_repo: Path, project: str, versions: tuple[str, ...]) -> None:
    versions_root = site_repo / _TEST_PROFILE.versions_dir / project
    assets_root = site_repo / _TEST_PROFILE.assets_dir / project
    versions_root.mkdir(parents=True, exist_ok=True)
    assets_root.mkdir(parents=True, exist_ok=True)
    (versions_root / "_index.md").write_text("index", encoding="utf-8")
    for version in versions:
        (versions_root / f"{version}.md").write_text(
            f"---\ntitle: {version}\n---\nbody\n", encoding="utf-8"
        )
        version_assets = assets_root / version
        version_assets.mkdir(parents=True, exist_ok=True)
        (version_assets / f"{project}-{version}.top.png").write_bytes(b"placeholder")


def test_list_projects_reports_project_shapes(tmp_path: Path) -> None:
    site_repo = tmp_path / "site"
    site_repo.mkdir()
    _seed_project(site_repo, "Alpha", ("1.0",))
    _seed_project(site_repo, "Demo", ("1.0", "1.1"))
    workflow = SiteManagementWorkflow()

    result = workflow.list_projects(_config(site_repo))

    assert result.exit_code == 0
    assert "Alpha [1.0]" in result.message
    assert "Demo [1.0, 1.1]" in result.message


def test_list_projects_scopes_to_single_project(tmp_path: Path) -> None:
    site_repo = tmp_path / "site"
    site_repo.mkdir()
    _seed_project(site_repo, "Alpha", ("1.0",))
    _seed_project(site_repo, "Demo", ("1.0", "1.1"))
    workflow = SiteManagementWorkflow()

    result = workflow.list_projects(_config(site_repo), project="Demo")

    assert result.exit_code == 0
    assert result.message == "Demo [1.0, 1.1]"


def test_list_projects_natural_orders_projects_and_versions(tmp_path: Path) -> None:
    site_repo = tmp_path / "site"
    site_repo.mkdir()
    _seed_project(site_repo, "Demo10", ("1.10", "1.2"))
    _seed_project(site_repo, "Demo2", ("2.0",))
    _seed_project(site_repo, "Demo1", ("1.0",))
    workflow = SiteManagementWorkflow()

    result = workflow.list_projects(_config(site_repo))

    assert result.exit_code == 0
    assert result.message.splitlines() == [
        "Demo1 [1.0]",
        "Demo2 [2.0]",
        "Demo10 [1.2, 1.10]",
    ]


def test_delete_version_removes_single_version_and_keeps_other_versions(tmp_path: Path) -> None:
    site_repo = tmp_path / "site"
    site_repo.mkdir()
    _seed_project(site_repo, "Demo", ("1.0", "1.1"))
    request = DeleteRequest(
        project="Demo",
        version="1.0",
        force=False,
        dry_run=False,
        config=_config(site_repo),
    )
    workflow = SiteManagementWorkflow()
    git_calls: list[list[str]] = []

    def _fake_git_run(cmd: list[str], *, site_repo: Path, check: bool = True) -> None:
        del site_repo, check
        git_calls.append(cmd)

    with (
        patch("kproj.application.site_management_workflow._git_run", side_effect=_fake_git_run),
        patch(
            "kproj.application.site_management_workflow._git_staged_names",
            return_value=["content/versions/Demo/1.0.md"],
        ),
        patch("kproj.application.site_management_workflow._git_pending_push_count", return_value=0),
    ):
        result = workflow.delete(request)

    assert result.exit_code == 0
    assert not (site_repo / "content/versions/Demo/1.0.md").exists()
    assert not (site_repo / "static/versions/Demo/1.0").exists()
    assert (site_repo / "content/versions/Demo/1.1.md").exists()
    commit_commands = [call for call in git_calls if call[:2] == ["commit", "-m"]]
    assert commit_commands
    assert commit_commands[0][2] == "delete version 1.0"


def test_delete_last_version_requires_force(tmp_path: Path) -> None:
    site_repo = tmp_path / "site"
    site_repo.mkdir()
    _seed_project(site_repo, "Solo", ("1.0",))
    request = DeleteRequest(
        project="Solo",
        version="1.0",
        force=False,
        dry_run=False,
        config=_config(site_repo),
    )
    workflow = SiteManagementWorkflow()

    result = workflow.delete(request)

    assert result.exit_code == 2
    assert "Use --force" in result.message
    assert (site_repo / "content/versions/Solo/1.0.md").exists()


def test_delete_last_version_with_force_escalates_to_full_project_delete(tmp_path: Path) -> None:
    site_repo = tmp_path / "site"
    site_repo.mkdir()
    _seed_project(site_repo, "Solo", ("1.0",))
    request = DeleteRequest(
        project="Solo",
        version="1.0",
        force=True,
        dry_run=False,
        config=_config(site_repo),
    )
    workflow = SiteManagementWorkflow()
    git_calls: list[list[str]] = []

    def _fake_git_run(cmd: list[str], *, site_repo: Path, check: bool = True) -> None:
        del site_repo, check
        git_calls.append(cmd)

    with (
        patch("kproj.application.site_management_workflow._git_run", side_effect=_fake_git_run),
        patch(
            "kproj.application.site_management_workflow._git_staged_names",
            return_value=["content/versions/Solo/1.0.md"],
        ),
        patch("kproj.application.site_management_workflow._git_pending_push_count", return_value=0),
    ):
        result = workflow.delete(request)

    assert result.exit_code == 0
    assert not (site_repo / "content/versions/Solo").exists()
    assert not (site_repo / "static/versions/Solo").exists()
    commit_commands = [call for call in git_calls if call[:2] == ["commit", "-m"]]
    assert commit_commands
    assert commit_commands[0][2] == "delete project 1.0"


def test_bare_delete_previews_and_fails_without_force(tmp_path: Path) -> None:
    site_repo = tmp_path / "site"
    site_repo.mkdir()
    _seed_project(site_repo, "Demo", ("1.0", "1.1"))
    request = DeleteRequest(
        project="Demo",
        version=None,
        force=False,
        dry_run=False,
        config=_config(site_repo),
    )
    workflow = SiteManagementWorkflow()

    result = workflow.delete(request)

    assert result.exit_code == 2
    assert "Would delete" in result.message
    assert (site_repo / "content/versions/Demo/1.0.md").exists()
    assert (site_repo / "content/versions/Demo/1.1.md").exists()


def test_delete_project_force_removes_all_versions(tmp_path: Path) -> None:
    site_repo = tmp_path / "site"
    site_repo.mkdir()
    _seed_project(site_repo, "Demo", ("1.0", "1.1"))
    request = DeleteRequest(
        project="Demo",
        version=None,
        force=True,
        dry_run=False,
        config=_config(site_repo),
    )
    workflow = SiteManagementWorkflow()
    git_calls: list[list[str]] = []

    def _fake_git_run(cmd: list[str], *, site_repo: Path, check: bool = True) -> None:
        del site_repo, check
        git_calls.append(cmd)

    with (
        patch("kproj.application.site_management_workflow._git_run", side_effect=_fake_git_run),
        patch(
            "kproj.application.site_management_workflow._git_staged_names",
            return_value=["content/versions/Demo/1.0.md", "content/versions/Demo/1.1.md"],
        ),
        patch("kproj.application.site_management_workflow._git_pending_push_count", return_value=0),
    ):
        result = workflow.delete(request)

    assert result.exit_code == 0
    assert not (site_repo / "content/versions/Demo").exists()
    assert not (site_repo / "static/versions/Demo").exists()
    commit_commands = [call for call in git_calls if call[:2] == ["commit", "-m"]]
    assert commit_commands
    assert commit_commands[0][2] == "delete project 1.0, 1.1"
