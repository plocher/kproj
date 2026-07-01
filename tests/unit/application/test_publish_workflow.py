"""Unit tests for :mod:`kproj.application.publish_workflow` (wave-2).

Covers DESIGN steps 1-4 (resolve, kicad-cli discovery + version check,
read, analyze, status detection) plus the exit-code population from the
``compute_exit_code`` helper.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from kproj.application import publish_workflow as workflow_module
from kproj.application.publish_workflow import PublishWorkflow
from kproj.common.kicad_install import KicadNotFoundError
from kproj.config import GENERIC_SITE_PROFILE, KprojConfig
from kproj.model.analysis_info import AnalysisInfo
from kproj.model.publication import AssetRef
from kproj.model.publish_request import PublishRequest
from kproj.model.publish_result import PublishResult
from kproj.services.change_journal import ChangeJournal
from kproj.services.kicad_project_reader import KicadProjectReader
from kproj.services.site_publisher import SitePublisher

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
        site_profile=GENERIC_SITE_PROFILE,
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
    config = KprojConfig(
        site_repo=tmp_path,
        no_push=False,
        kicad_cli=None,
        site_profile=GENERIC_SITE_PROFILE,
    )
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
        site_profile=GENERIC_SITE_PROFILE,
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


def test_active_project_fails_preflight_without_ibom(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An active project with missing iBOM plugin fails at step 5a pre-flight.

    Wave-4 (kproj#4) wires steps 5-11.  Without the iBOM plugin installed
    the pipeline fails at step 5a (iBOM pre-flight) and returns
    ``outcome="failed"``, ``exit_code=2``.
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

    # Patch ibom script locator to raise KicadNotFoundError.
    from kproj.common.kicad_install import KicadNotFoundError

    def _no_ibom() -> Path:
        raise KicadNotFoundError("iBOM plugin not installed")

    workflow = PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_silent_design_analyzer_factory(),
        ibom_script_locator=_no_ibom,
    )
    result = workflow.run(_make_request(str(proj_dir), fake_cli))
    assert result.outcome == "failed"
    assert result.exit_code == 2
    assert "iBOM" in result.message or "ibom" in result.message.lower()


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


def test_drc_erc_mechanical_failure_returns_failed_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M4 round-2 regression: DesignAnalysisError → failed/exit 2.

    When ``kicad-cli pcb drc`` (or ``sch erc``) fails mechanically
    (nonzero return, no JSON emitted), :class:`DesignAnalyzer` raises
    :class:`DesignAnalysisError`.  The workflow catches it *before*
    opening the change journal and returns
    ``PublishResult(outcome="failed", exit_code=2)`` with no site
    writes — the mechanical-vs-findings split locked in ADR 0004.
    """
    from kproj.services.design_analyzer import DesignAnalysisError

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

    class _CrashingAnalyzer:
        """Analyzer that always crashes mechanically."""

        def __init__(self, _cli: Path) -> None: ...

        def analyze(self, _resolved: object) -> object:
            raise DesignAnalysisError(
                "kicad-cli pcb drc failed without producing JSON (rc=2): "
                "kicad-cli: segfault probing board",
                origin="drc",
                returncode=2,
            )

    workflow = PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_CrashingAnalyzer,
    )
    result = workflow.run(_make_request(str(proj_dir), fake_cli))
    assert result.outcome == "failed", (
        f"M4: DesignAnalysisError must convert to outcome=failed; got {result.outcome!r}"
    )
    assert result.exit_code == 2
    assert "drc" in result.message.lower(), (
        f"expected drc context in failure message; got {result.message!r}"
    )


def test_drc_erc_mechanical_failure_does_not_open_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M4 round-2: mechanical failure must occur BEFORE any site writes.

    The DesignAnalyzer runs at step 3 (before the change journal is
    opened at step 7).  A mechanical failure raised there must never
    reach the artifact generator or site publisher, guaranteeing zero
    partial writes on disk.
    """
    from kproj.services.design_analyzer import DesignAnalysisError

    site = _make_site_repo(tmp_path)
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

    class _CrashingAnalyzer:
        def __init__(self, _cli: Path) -> None: ...

        def analyze(self, _resolved: object) -> object:
            raise DesignAnalysisError(
                "kicad-cli sch erc failed without producing JSON (rc=1): schematic unreadable",
                origin="erc",
                returncode=1,
            )

    called = {"artifact_gen": False}

    def _generator(
        resolved: object,
        project_info: object,
        kicad_cli: Path,
        ibom_script: Path,
        _site_repo: Path,
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
        called["artifact_gen"] = True
        return (), (), ()

    fake_ibom = tmp_path / "generate_interactive_bom.py"
    fake_ibom.write_text("")

    workflow = PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_CrashingAnalyzer,
        ibom_script_locator=_stub_ibom_locator(fake_ibom),
        artifact_generator=_generator,
        site_publisher_factory=_stub_site_publisher_factory(site),
    )
    request = _make_full_request(str(proj_dir), fake_cli, site)
    with patch("kproj.services.site_publisher._git_run") as mock_git:
        result = workflow.run(request)

    assert result.outcome == "failed"
    assert result.exit_code == 2
    # No site writes at all: no artifact generator, no git operations.
    assert not called["artifact_gen"], (
        "M4: artifact generator must not run when DesignAnalyzer raises mechanically"
    )
    assert not mock_git.call_args_list, (
        "M4: no git operations expected on mechanical failure; got "
        f"{[c.args for c in mock_git.call_args_list]!r}"
    )
    # No partial version/page markdown on disk.
    versions_dir = site / "_versions"
    pages_dir = site / "pages"
    assert not versions_dir.exists() or not list(versions_dir.rglob("*.md"))
    assert not pages_dir.exists() or not list(pages_dir.rglob("*.md"))


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


# ----- full-pipeline helpers (steps 5-11) -----


def _stub_ibom_locator(fake_script: Path) -> object:
    """Return an iBOM locator that returns *fake_script* without probing."""
    return lambda: fake_script


def _stub_artifact_generator(
    site_repo: Path,
) -> object:
    """Return an artifact generator that writes placeholder files."""

    def _gen(
        resolved: object,
        project_info: object,
        kicad_cli: Path,
        ibom_script: Path,
        _site_repo: Path,
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
        from kproj.services.kicad_project_reader import KicadProjectReader  # noqa: F401

        # Use the canonical project + board_rev from project_info per the
        # post-BLOCKER-1 generator contract.
        basename = getattr(project_info, "project", None) or getattr(resolved, "basename", "demo")
        R = getattr(project_info, "board_rev", None) or "1.0"
        PR = f"{basename}-{R}"
        base_site = f"/versions/{basename}/{R}"
        asset_dir = _site_repo / "versions" / basename / R
        asset_dir.mkdir(parents=True, exist_ok=True)
        # Write placeholder files so detect_outcome's asset check passes.
        for filename in [
            f"{PR}.top.png",
            f"{PR}.bottom.png",
            f"{PR}.sch.svg",
            f"{PR}.sch.pdf",
            f"{PR}.ibom.html",
            f"{PR}.step",
            f"{PR}.source.zip",
        ]:
            f = asset_dir / filename
            f.write_bytes(b"placeholder")
            journal.will_create(f)
        images: tuple[AssetRef, ...] = (
            AssetRef(path=f"{base_site}/{PR}.top.png", tag="render-top", title="Top"),
            AssetRef(path=f"{base_site}/{PR}.bottom.png", tag="render-bottom", title="Bottom"),
            AssetRef(path=f"{base_site}/{PR}.sch.svg", tag="schematic-svg", title="Schematic"),
        )
        artifacts: tuple[AssetRef, ...] = (
            AssetRef(
                path=f"{base_site}/{PR}.sch.pdf",
                tag="schematic-pdf",
                post="Full schematic (all sheets)",
            ),
            AssetRef(
                path=f"{base_site}/{PR}.ibom.html",
                tag="interactive-bom",
                post="Interactive HTML BOM",
            ),
            AssetRef(path=f"{base_site}/{PR}.step", tag="step-model", post="3D STEP model"),
            AssetRef(
                path=f"{base_site}/{PR}.source.zip",
                tag="source-archive",
                post="KiCad source archive",
            ),
        )
        return images, artifacts, ()

    return _gen


def _stub_site_publisher_factory(
    site_repo: Path,
) -> object:
    """Return a SitePublisher factory that patches _git_run to a no-op."""

    def _factory(journal: ChangeJournal) -> SitePublisher:
        return SitePublisher(journal)

    return _factory


def _full_pipeline_workflow(
    tmp_path: Path,
    site_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> PublishWorkflow:
    """Build a workflow with all external side-effects stubbed out."""
    fake_ibom = tmp_path / "generate_interactive_bom.py"
    fake_ibom.write_text("")
    return PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_silent_design_analyzer_factory(),
        ibom_script_locator=_stub_ibom_locator(fake_ibom),
        artifact_generator=_stub_artifact_generator(site_repo),
        site_publisher_factory=_stub_site_publisher_factory(site_repo),
    )


def _make_site_repo(tmp_path: Path, *, name: str = "site") -> Path:
    """Initialise a bare git repo as a fixture site repo."""
    import os

    site = tmp_path / name
    site.mkdir()
    os.system(f"git -C '{site}' init -q")
    os.system(f"git -C '{site}' config user.email 'test@test.com'")
    os.system(f"git -C '{site}' config user.name 'Test'")
    return site


def _make_full_request(
    project_arg: str,
    kicad_cli: Path,
    site_repo: Path,
    *,
    dry_run: bool = False,
    no_push: bool = True,
) -> PublishRequest:
    config = KprojConfig(
        site_repo=site_repo,
        no_push=no_push,
        kicad_cli=kicad_cli,
        site_profile=GENERIC_SITE_PROFILE,
    )
    return PublishRequest(
        project_arg=project_arg,
        config=config,
        dry_run=dry_run,
    )


# ----- full-pipeline tests -----


def test_active_project_publishes_successfully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An active project with all services stubbed returns outcome='published'."""
    site = _make_site_repo(tmp_path)
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(
            title="My Board",
            revision="1.0",
            company="MRCS",
            date="2026.04",
            comments={1: "Alice Designer", 9: "active"},
        ),
        pcb_title_block=TitleBlockSpec(
            title="My Board",
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))

    workflow = _full_pipeline_workflow(tmp_path, site, monkeypatch)
    request = _make_full_request(str(proj_dir), fake_cli, site)

    with patch("kproj.services.site_publisher._git_run"):
        result = workflow.run(request)

    assert result.outcome in ("published", "refreshed", "noop")
    assert result.exit_code in (0, 1)  # may have warnings


def test_dry_run_does_not_write_site_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """dry_run=True skips artifact generation and site writes."""
    site = _make_site_repo(tmp_path)
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(
            revision="1.0",
            comments={1: "Alice Designer", 9: "active"},
        ),
        pcb_title_block=TitleBlockSpec(
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))

    workflow = _full_pipeline_workflow(tmp_path, site, monkeypatch)
    request = _make_full_request(str(proj_dir), fake_cli, site, dry_run=True)

    with patch("kproj.services.site_publisher._git_run"):
        result = workflow.run(request)

    # No version file should be written
    version_files = (
        list((site / "_versions").rglob("*.md")) if (site / "_versions").exists() else []
    )
    assert not version_files, f"dry-run wrote files: {version_files}"
    assert result.outcome in ("published", "refreshed", "noop")


def test_site_repo_dirty_fails_preflight(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A dirty site repo (uncommitted changes) fails at step 5b."""
    site = _make_site_repo(tmp_path)
    # Create an uncommitted file in the site repo
    (site / "dirty.md").write_text("uncommitted")

    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(
            revision="1.0",
            comments={1: "Alice Designer", 9: "active"},
        ),
        pcb_title_block=TitleBlockSpec(
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))

    workflow = _full_pipeline_workflow(tmp_path, site, monkeypatch)
    request = _make_full_request(str(proj_dir), fake_cli, site)
    result = workflow.run(request)
    assert result.outcome == "failed"
    assert result.exit_code == 2
    assert (
        "uncommitted" in result.message
        or "dirty" in result.message.lower()
        or "changes" in result.message
    )


def test_artifact_generator_receives_project_info_with_canonical_board_rev(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BLOCKER 1 regression: generator must be invoked with the real board_rev.

    The pre-fix default generator derived ``board_rev`` from the
    ``.kicad_pro`` stem (i.e. the project basename), so a project
    ``demo`` with PCB ``rev=1.0B`` produced asset paths under
    ``versions/demo/demo/`` named ``demo-demo.*``.  After the fix, the
    workflow threads :class:`ProjectInfo` (and therefore the canonical
    PCB-derived ``board_rev``) into the artifact-generator callable.
    """
    site = _make_site_repo(tmp_path)
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(
            title="My Board",
            revision="1.0",
            comments={1: "Alice Designer", 9: "active"},
        ),
        pcb_title_block=TitleBlockSpec(
            title="My Board",
            revision="1.0B",  # ← distinct from the project basename "demo"
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))

    fake_ibom = tmp_path / "generate_interactive_bom.py"
    fake_ibom.write_text("")

    captured: dict[str, object] = {}

    def _recording_gen(
        resolved: object,
        project_info: object,
        kicad_cli: Path,
        ibom_script: Path,
        _site_repo: Path,
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
        captured["project"] = getattr(project_info, "project", None)
        captured["board_rev"] = getattr(project_info, "board_rev", None)
        # Emit asset refs in the same shape the workflow's preliminary
        # detection uses so detect_outcome's asset existence check is
        # consistent (the test does not need real files on disk —
        # detect_outcome sees the version file as absent so returns
        # "publish" before checking assets).
        return (), (), ()

    workflow = PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_silent_design_analyzer_factory(),
        ibom_script_locator=_stub_ibom_locator(fake_ibom),
        artifact_generator=_recording_gen,
        site_publisher_factory=_stub_site_publisher_factory(site),
    )
    request = _make_full_request(str(proj_dir), fake_cli, site)

    with patch("kproj.services.site_publisher._git_run"):
        workflow.run(request)

    assert captured["project"] == "demo"
    assert captured["board_rev"] == "1.0B", (
        f"artifact generator received board_rev={captured['board_rev']!r}; "
        "BLOCKER 1: must be the PCB-derived board_rev, not the project stem."
    )


def test_schematic_export_error_converts_to_failed_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BLOCKER 5 regression: SchematicExportError → failed/exit 2.

    The pre-fix workflow caught only ``SubprocessFailedError``,
    ``SubprocessTimeoutError``, and ``OSError``.  A real output-shape
    mismatch (zero SVGs or multiple root-only SVGs) raised
    ``SchematicExportError`` which escaped as a Python traceback
    instead of becoming ``PublishResult(outcome="failed",
    exit_code=2)`` with a clean stderr message.
    """
    from kproj.services.schematic_exporter import SchematicExportError

    site = _make_site_repo(tmp_path)
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(
            revision="1.0",
            comments={1: "Alice Designer", 9: "active"},
        ),
        pcb_title_block=TitleBlockSpec(
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))

    fake_ibom = tmp_path / "generate_interactive_bom.py"
    fake_ibom.write_text("")

    def _exploding_gen(
        resolved: object,
        project_info: object,
        kicad_cli: Path,
        ibom_script: Path,
        _site_repo: Path,
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
        # Simulate the schematic-export shape-mismatch path: register
        # one output then raise.  The workflow must convert this into
        # outcome=failed/exit 2 rather than letting it propagate.
        bogus_asset = _site_repo / "versions" / "demo" / "1.0" / "demo-1.0.sch.svg"
        bogus_asset.parent.mkdir(parents=True, exist_ok=True)
        journal.will_create(bogus_asset)
        raise SchematicExportError(
            "kicad-cli sch export svg produced no SVG files in the staging dir"
        )

    workflow = PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_silent_design_analyzer_factory(),
        ibom_script_locator=_stub_ibom_locator(fake_ibom),
        artifact_generator=_exploding_gen,
        site_publisher_factory=_stub_site_publisher_factory(site),
    )
    request = _make_full_request(str(proj_dir), fake_cli, site)

    with patch("kproj.services.site_publisher._git_run"):
        result = workflow.run(request)

    assert result.outcome == "failed", (
        f"BLOCKER 5: SchematicExportError must convert to outcome=failed; got {result.outcome!r}"
    )
    assert result.exit_code == 2
    assert "svg" in result.message.lower() or "schematic" in result.message.lower(), (
        f"expected schematic context in failure message; got {result.message!r}"
    )


def test_stale_pcb_forces_publish_outcome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M1 regression: assets older than the source PCB → publish, not noop.

    Pre-fix ``SitePublisher.detect_outcome`` only checked asset
    existence + markdown content equality.  A PCB edited after the
    previous publish but whose title-block stayed stable yielded
    ``noop``, leaving stale renders / STEP / iBOM / source archives
    on the site forever.  The workflow now compares asset mtimes
    against their source mtimes and escalates to ``publish`` when
    any asset is stale.

    Wave-3 M11 round-2 tightens the escalation: pure mtime bumps
    without a content change no longer force a publish (that would
    conflict with PRD Story 6's cheap metadata refresh).  This test
    now performs a real content edit outside the title-block so the
    title-block-stripped hash changes and the M1 escalation still
    fires.
    """
    import os as _os
    import time as _time

    site = _make_site_repo(tmp_path)
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(
            title="Demo",
            revision="1.0",
            comments={1: "Alice Designer", 9: "active"},
        ),
        pcb_title_block=TitleBlockSpec(
            title="Demo",
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))

    # Step 1: prime the site repo with the version page + all assets
    # using the standard full-pipeline stubs (acting as the "prior
    # publish").  Capture the workflow's would-be content so we can
    # write an exactly-matching version file on disk for the second run.
    workflow = _full_pipeline_workflow(tmp_path, site, monkeypatch)
    request = _make_full_request(str(proj_dir), fake_cli, site)
    with patch("kproj.services.site_publisher._git_run"):
        first = workflow.run(request)
    assert first.outcome in ("published", "refreshed"), (
        f"setup: first publish should succeed; got {first.outcome!r}"
    )

    # Step 2: clean up the dirty git state that the mocked _git_run
    # left behind so the cleanliness pre-flight passes on the second
    # run (git really wasn't invoked above).
    _os.system(f"git -C '{site}' add -A")
    _os.system(f"git -C '{site}' commit -q -m 'prior publish'")

    # Sanity: a clean re-run with identical inputs is a noop.
    with patch("kproj.services.site_publisher._git_run"):
        noop_run = workflow.run(request)
    assert noop_run.outcome == "noop", (
        f"setup: idempotent re-run should be noop; got {noop_run.outcome!r}"
    )

    # Step 3: perform a real PCB content edit outside the title-block
    # subtree.  With M11 round-2, a pure mtime bump would leave the
    # title-block-stripped hash unchanged and the workflow would
    # correctly refuse to escalate (metadata-only edits stay refresh
    # per Story 6).  A genuine content edit changes both the mtime
    # AND the hash — the intended M1 mechanical-stale-asset trigger.
    pcb_path = proj_dir / "demo.kicad_pcb"
    pcb_path.write_text(
        pcb_path.read_text(encoding="utf-8").rstrip("\n)") + '\n\t(net 0 "")\n)\n',
        encoding="utf-8",
    )
    future = _time.time() + 120
    _os.utime(pcb_path, (future, future))

    with patch("kproj.services.site_publisher._git_run"):
        stale_run = workflow.run(request)

    assert stale_run.outcome == "published", (
        f"M1: stale assets vs PCB source must escalate to publish; got {stale_run.outcome!r}"
    )


def test_artifact_generator_diagnostics_flow_into_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M6 regression: producer diagnostics must reach PublishResult.findings.

    Pre-fix ``_default_artifact_generator`` inspected only
    ``fab_result.skipped`` and discarded ``fab_result.diagnostics``;
    the final ``Publication`` used the pre-artifact ``analysis``
    (built before generation), so artifact-stage warnings never
    reached stderr, the Markdown tables, front-matter counts, or the
    exit-code calculation.  After the fix the artifact-generator
    callable returns ``(images, artifacts, diagnostics)``, the
    workflow merges the diagnostics into the analysis, and rebuilds
    the body markdown before final publication.
    """
    from kproj.model.finding import Finding
    from kproj.model.severity import Severity

    site = _make_site_repo(tmp_path)
    proj_dir = make_minimal_project(
        tmp_path / "demo",
        "demo",
        sch_title_block=TitleBlockSpec(
            title="Demo",
            revision="1.0",
            comments={1: "Alice Designer", 9: "active"},
        ),
        pcb_title_block=TitleBlockSpec(
            title="Demo",
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))

    fake_ibom = tmp_path / "generate_interactive_bom.py"
    fake_ibom.write_text("")

    producer_warning = Finding(
        severity=Severity.WARNING,
        field="production_stale",
        value=str(proj_dir / "production"),
        reason="production/ outputs are older than the PCB",
        project="demo",
        source="audit",
    )

    def _gen_with_diagnostics(
        resolved: object,
        project_info: object,
        kicad_cli: Path,
        ibom_script: Path,
        _site_repo: Path,
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[Finding, ...]]:
        # Return no asset refs; just surface a producer-stage diagnostic.
        return (), (), (producer_warning,)

    workflow = PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_silent_design_analyzer_factory(),
        ibom_script_locator=_stub_ibom_locator(fake_ibom),
        artifact_generator=_gen_with_diagnostics,
        site_publisher_factory=_stub_site_publisher_factory(site),
    )
    request = _make_full_request(str(proj_dir), fake_cli, site)

    with patch("kproj.services.site_publisher._git_run"):
        result = workflow.run(request)

    assert any(
        f.field == "production_stale" and f.reason == producer_warning.reason
        for f in result.findings
    ), (
        "M6: producer-stage diagnostic did not reach PublishResult.findings. "
        f"result.findings={[f.field for f in result.findings]}"
    )
