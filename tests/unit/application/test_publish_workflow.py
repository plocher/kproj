"""Unit tests for :mod:`kproj.application.publish_workflow`.

Validates the walking-skeleton pre-flight per ``docs/DESIGN.md`` §
*Pipeline orchestration sequence* step 1: project resolution +
kicad-cli discovery + version check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kproj.application import publish_workflow as workflow_module
from kproj.application.publish_workflow import (
    PublishRequest,
    PublishResult,
    PublishWorkflow,
)
from kproj.common.kicad_install import KicadNotFoundError
from kproj.config import KprojConfig
from kproj.services.kicad_project_reader import (
    KicadProjectReader,
)


def _make_kicad_project(root: Path, name: str = "demo") -> Path:
    """Create a minimal KiCad project tree under *root*."""
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.kicad_pro").write_text("")
    (root / f"{name}.kicad_pcb").write_text("")
    (root / f"{name}.kicad_sch").write_text("")
    return root


def _make_request(project_arg: str, kicad_cli: Path) -> PublishRequest:
    """Build a PublishRequest with kicad_cli pinned for predictable tests."""
    config = KprojConfig(
        site_repo=Path("/tmp/site"),
        no_push=False,
        kicad_cli=kicad_cli,
    )
    return PublishRequest(project_arg=project_arg, config=config)


def _stub_kicad_version(monkeypatch: pytest.MonkeyPatch, version: tuple[int, int, int]) -> None:
    """Patch ``kicad_version`` inside publish_workflow to return *version*."""

    def _fake(cli: Path) -> tuple[int, int, int]:
        return version

    monkeypatch.setattr(workflow_module, "kicad_version", _fake)


def test_publish_workflow_preflight_failure_on_unresolvable_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing project surfaces as ``outcome=failed``."""
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 0))
    workflow = PublishWorkflow(project_reader=KicadProjectReader(projects_root=tmp_path))
    result = workflow.run(_make_request(str(tmp_path / "absent"), fake_cli))
    assert result.outcome == "failed"
    assert result.exit_code == 2
    assert "project resolution failed" in result.message


def test_publish_workflow_preflight_failure_on_kicad_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing configured kicad-cli surfaces as ``outcome=failed``."""
    proj_dir = _make_kicad_project(tmp_path / "x")
    # Force the workflow to probe via find_kicad_cli, then make it raise.

    def _fake_find() -> Path:
        raise KicadNotFoundError("kicad-cli not found")

    monkeypatch.setattr(workflow_module, "find_kicad_cli", _fake_find)
    config = KprojConfig(site_repo=tmp_path, no_push=False, kicad_cli=None)
    request = PublishRequest(project_arg=str(proj_dir), config=config)
    workflow = PublishWorkflow(project_reader=KicadProjectReader(projects_root=tmp_path))
    result = workflow.run(request)
    assert result.outcome == "failed"
    assert "kicad-cli not found" in result.message


def test_publish_workflow_preflight_rejects_non_9x_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A kicad-cli major != 9 fails pre-flight with a clear message."""
    proj_dir = _make_kicad_project(tmp_path / "x")
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (8, 0, 2))
    workflow = PublishWorkflow(project_reader=KicadProjectReader(projects_root=tmp_path))
    result = workflow.run(_make_request(str(proj_dir), fake_cli))
    assert result.outcome == "failed"
    assert "unsupported kicad-cli version 8.0.2" in result.message


def test_publish_workflow_preflight_success_returns_failed_for_downstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A successful pre-flight still returns ``failed`` (downstream not implemented).

    The stderr summary line ``kproj: kicad-cli <version> at <path>``
    must surface for auditability.
    """
    proj_dir = _make_kicad_project(tmp_path / "x")
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))
    workflow = PublishWorkflow(project_reader=KicadProjectReader(projects_root=tmp_path))
    result = workflow.run(_make_request(str(proj_dir), fake_cli))
    assert isinstance(result, PublishResult)
    assert result.outcome == "failed"
    assert "pre-flight succeeded" in result.message
    err = capsys.readouterr().err
    assert "kicad-cli 9.0.4" in err
    assert str(fake_cli) in err


def test_publish_workflow_rejects_configured_kicad_cli_that_does_not_exist(
    tmp_path: Path,
) -> None:
    """Configured kicad_cli pointing at a missing path surfaces as failed."""
    proj_dir = _make_kicad_project(tmp_path / "x")
    config = KprojConfig(
        site_repo=tmp_path,
        no_push=False,
        kicad_cli=tmp_path / "no-such-kicad-cli",
    )
    request = PublishRequest(project_arg=str(proj_dir), config=config)
    workflow = PublishWorkflow(project_reader=KicadProjectReader(projects_root=tmp_path))
    result = workflow.run(request)
    assert result.outcome == "failed"
    assert "configured kicad_cli" in result.message
