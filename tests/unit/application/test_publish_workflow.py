"""Unit tests for :mod:`kproj.application.publish_workflow` (wave-2).

Covers DESIGN steps 1-4 (resolve, kicad-cli discovery + version check,
read, analyze, status detection) plus the exit-code population from the
``compute_exit_code`` helper.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from kproj.application import publish_workflow as workflow_module
from kproj.application.publish_workflow import PublishWorkflow
from kproj.common.kicad_install import KicadNotFoundError
from kproj.config import KprojConfig
from kproj.model.publish_request import PublishRequest
from kproj.model.publish_result import PublishResult
from kproj.services.kicad_project_reader import KicadProjectReader

_TESTS_ROOT = Path(__file__).resolve().parents[2]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from _kicad_fixtures import (  # noqa: E402 - path setup above
    TitleBlockSpec,
    make_minimal_project,
)


def _make_request(project_arg: str, kicad_cli: Path) -> PublishRequest:
    """Build a request with a kicad_cli pinned for predictable tests."""
    config = KprojConfig(
        site_repo=Path("/tmp/site"),
        no_push=False,
        kicad_cli=kicad_cli,
    )
    return PublishRequest(project_arg=project_arg, config=config)


def _stub_kicad_version(monkeypatch: pytest.MonkeyPatch, version: tuple[int, int, int]) -> None:
    """Patch ``kicad_version`` inside publish_workflow to return *version*."""

    def _fake(_cli: Path) -> tuple[int, int, int]:
        return version

    monkeypatch.setattr(workflow_module, "kicad_version", _fake)


def _silent_design_analyzer_factory() -> object:
    """Return a factory producing a DesignAnalyzer that emits no findings.

    The factory is callable with the kicad-cli path; the returned object
    only needs an ``analyze(resolved)`` method returning an empty
    :class:`AnalysisInfo`.
    """

    class _Silent:
        def __init__(self, _cli: Path) -> None: ...

        def analyze(self, _resolved: object) -> object:
            from kproj.model.analysis_info import AnalysisInfo

            return AnalysisInfo(findings=())

    return _Silent


def _workflow(
    tmp_path: Path,
    *,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> PublishWorkflow:
    """Build a workflow with deterministic dependencies for unit tests."""
    return PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_silent_design_analyzer_factory(),
    )


# ----- pre-flight failure cases -----


def test_preflight_failure_on_unresolvable_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing project surfaces as ``outcome=failed`` with exit code 2."""
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 0))
    workflow = _workflow(tmp_path)
    result = workflow.run(_make_request(str(tmp_path / "absent"), fake_cli))
    assert result.outcome == "failed"
    assert result.exit_code == 2
    assert "project resolution failed" in result.message


def test_preflight_failure_on_kicad_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing configured kicad-cli surfaces as ``outcome=failed``."""
    proj_dir = make_minimal_project(tmp_path / "x", "demo")

    def _fake_find() -> Path:
        raise KicadNotFoundError("kicad-cli not found")

    monkeypatch.setattr(workflow_module, "find_kicad_cli", _fake_find)
    config = KprojConfig(site_repo=tmp_path, no_push=False, kicad_cli=None)
    request = PublishRequest(project_arg=str(proj_dir), config=config)
    workflow = _workflow(tmp_path)
    result = workflow.run(request)
    assert result.outcome == "failed"
    assert result.exit_code == 2
    assert "kicad-cli not found" in result.message


def test_preflight_rejects_non_9x_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A kicad-cli major != 9 fails pre-flight with a clear message."""
    proj_dir = make_minimal_project(tmp_path / "x", "demo")
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (8, 0, 2))
    workflow = _workflow(tmp_path)
    result = workflow.run(_make_request(str(proj_dir), fake_cli))
    assert result.outcome == "failed"
    assert result.exit_code == 2
    assert "unsupported kicad-cli version 8.0.2" in result.message


def test_rejects_configured_kicad_cli_that_does_not_exist(tmp_path: Path) -> None:
    """Configured kicad_cli pointing at a missing path surfaces as failed."""
    proj_dir = make_minimal_project(tmp_path / "x", "demo")
    config = KprojConfig(
        site_repo=tmp_path,
        no_push=False,
        kicad_cli=tmp_path / "no-such-kicad-cli",
    )
    request = PublishRequest(project_arg=str(proj_dir), config=config)
    workflow = _workflow(tmp_path)
    result = workflow.run(request)
    assert result.outcome == "failed"
    assert "configured kicad_cli" in result.message


# ----- post-pre-flight: status detection + findings -----


def test_private_project_short_circuits_with_private_skip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``status=private`` short-circuits with ``outcome=private-skip``."""
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(
            title="Hello",
            company="ACME",
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer", 9: "private"},
        ),
        pcb_title_block=TitleBlockSpec(
            title="Hello",
            company="ACME",
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))
    workflow = _workflow(tmp_path)
    result = workflow.run(_make_request(str(proj_dir), fake_cli))
    assert result.outcome == "private-skip"
    # exit_code is 1 because the production_missing audit warning still fires;
    # the locked PRD Story 7 contract states private status STILL surfaces
    # findings - only the site writes are skipped.
    assert result.exit_code in (0, 1)
    assert "status=private" in result.message
    err = capsys.readouterr().err
    assert "kicad-cli 9.0.4" in err


def test_active_project_reaches_walking_skeleton_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An active project surfaces ``outcome=failed`` past step 4 (steps 5+ not impl).

    The ``failed`` here documents the wave-2 walking-skeleton boundary,
    NOT a mechanical failure - wave-3 wires the remaining steps.
    """
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(
            title="Hello",
            revision="1.0",
            comments={1: "Alice Designer", 9: "active"},
        ),
        pcb_title_block=TitleBlockSpec(
            title="Hello",
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))
    workflow = _workflow(tmp_path)
    result = workflow.run(_make_request(str(proj_dir), fake_cli))
    assert result.outcome == "failed"
    assert "walking-skeleton" in result.message or "not yet implemented" in result.message
    # exit_code == 2 because outcome is "failed" - that's mechanical-failure
    # signal until wave-3 finishes the rest of the pipeline.
    assert result.exit_code == 2


def test_workflow_threads_findings_into_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit + DRC/ERC findings reach ``PublishResult.findings``."""
    # COMMENT9 missing → comment9_missing warning will be emitted.
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(
            title="Hello",
            revision="1.0",
            comments={1: "Alice Designer"},
        ),
        pcb_title_block=TitleBlockSpec(
            title="Hello",
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))
    workflow = _workflow(tmp_path)
    result = workflow.run(_make_request(str(proj_dir), fake_cli))
    assert any(f.field == "comment9_missing" for f in result.findings)


def test_workflow_uses_injected_design_analyzer_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tests can inject a fake DesignAnalyzer factory to avoid kicad-cli."""
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(
            title="Hello",
            revision="1.0",
            comments={1: "Alice Designer", 9: "active"},
        ),
        pcb_title_block=TitleBlockSpec(
            title="Hello",
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))

    seen: list[Path] = []

    class _Recording:
        def __init__(self, cli: Path) -> None:
            seen.append(cli)

        def analyze(self, _resolved: object) -> object:
            from kproj.model.analysis_info import AnalysisInfo

            return AnalysisInfo(findings=())

    workflow = PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_Recording,
    )
    workflow.run(_make_request(str(proj_dir), fake_cli))
    assert seen == [fake_cli]


def test_result_is_instance_of_publish_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity: the run result is the model-layer :class:`PublishResult`."""
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))
    workflow = _workflow(tmp_path)
    result = workflow.run(_make_request(str(tmp_path / "absent"), fake_cli))
    assert isinstance(result, PublishResult)
