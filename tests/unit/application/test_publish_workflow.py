"""Unit tests for :mod:`kproj.application.publish_workflow` (wave-2).

Covers DESIGN steps 1-4 (resolve, kicad-cli discovery + version check,
read, analyze, status detection) plus the exit-code population from the
``compute_exit_code`` helper.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from kproj.application import publish_workflow as workflow_module
from kproj.application.publish_workflow import PublishWorkflow
from kproj.common import github_link as github_link_module
from kproj.common.kicad_install import KicadNotFoundError
from kproj.config import (
    DEFAULT_FABRICATOR,
    DEFAULT_IBOM_EXTRA_FIELDS,
    GENERIC_SITE_PROFILE,
    KprojConfig,
)
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
    assert "kicad-cli 9.0.4" not in err


def test_verbose_mode_emits_toolchain_reports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Toolchain info lines are shown only when ``verbose_level >= 1``."""
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
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("IPN,Category,Value,Package\n", encoding="utf-8")
    _stub_kicad_version(monkeypatch, (9, 0, 4))
    monkeypatch.setattr(
        workflow_module,
        "jbom_tool_report",
        lambda: "Info: Using jbom 7.8.1 at /tmp/jbom",
    )

    config = KprojConfig(
        site_repo=tmp_path / "site",
        no_push=False,
        kicad_cli=fake_cli,
        site_profile=GENERIC_SITE_PROFILE,
        inventory=inventory,
    )
    request = replace(
        PublishRequest(project_arg=str(proj_dir), config=config),
        verbose_level=1,
    )
    workflow = _workflow(tmp_path)
    result = workflow.run(request)
    assert result.outcome == "private-skip"
    err = capsys.readouterr().err
    assert "Info: Using kicad-cli 9.0.4" in err
    assert "Info: Using jbom 7.8.1 at /tmp/jbom" in err


def test_run_surfaces_github_link_missing_finding_for_non_repo_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project directory with no git repo backing gets a github_link_missing finding.

    Absence-highlighting (kproj#30 clarified requirement): kproj must
    actively surface the missing GitHub-repo backing rather than
    silently omitting the link. Uses the private-skip fixture/path
    (no site repo or artifact pipeline needed) purely as a convenient
    terminal point that still returns the merged findings.
    """
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
    github_findings = [f for f in result.findings if f.field == "github_link_missing"]
    assert len(github_findings) == 1, (
        f"expected exactly one github_link_missing finding; got fields="
        f"{[f.field for f in result.findings]}"
    )
    assert github_findings[0].project == "demo"


def test_run_detects_github_link_exactly_once_per_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``detect_github_link`` (the only git-touching call) runs exactly once per publish.

    Human ruling on kproj#30: the front-matter ``github_url`` and the
    absence-highlighting audit finding must be derived from the same
    detection pass, not two independent ones. Wraps
    ``github_link.subprocess_run`` to count invocations while still
    delegating to the real implementation, then asserts the initial
    ``rev-parse --is-inside-work-tree`` probe - the entry point of
    every :func:`~kproj.common.github_link.detect_github_link` call -
    fires exactly once for the whole publish.
    """
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

    real_subprocess_run = github_link_module.subprocess_run
    work_tree_probe_calls: list[tuple[str, ...]] = []

    def _counting_subprocess_run(command: list[str], **kwargs: object) -> object:
        if "--is-inside-work-tree" in command:
            work_tree_probe_calls.append(tuple(command))
        return real_subprocess_run(command, **kwargs)

    monkeypatch.setattr(github_link_module, "subprocess_run", _counting_subprocess_run)

    workflow = _workflow(tmp_path)
    result = workflow.run(_make_request(str(proj_dir), fake_cli))

    assert result.outcome == "private-skip"
    assert len(work_tree_probe_calls) == 1, (
        f"expected exactly one detect_github_link pass (one "
        f"--is-inside-work-tree probe) per publish; got "
        f"{len(work_tree_probe_calls)}: {work_tree_probe_calls}"
    )


def test_raising_datasheet_lookup_cannot_fail_a_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A datasheet-name lookup that raises degrades to a warning, never a failure.

    Structural-enforcement regression test (PR #35 adversarial review
    finding #2): mutation-proves that ``PublishWorkflow.run`` itself -
    not just ``read_datasheet_names`` / ``check_datasheet_links``
    internally - upholds the "advisory-only, never a publish blocker"
    contract. Injects a ``datasheet_name_lookup`` that unconditionally
    raises (standing in for any surprise exception, including one from
    inside ``check_datasheet_links`` that the mutation-tested
    ``candidate.is_file()`` call used to be able to leak).
    """
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

    def _raising_lookup(
        _project_dir: Path,
        _inventory: Path | None,
        _fabricator: str,
    ) -> object:
        raise RuntimeError("simulated unexpected failure inside the datasheet guard")

    workflow = PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_silent_design_analyzer_factory(),
        datasheet_name_lookup=_raising_lookup,
    )
    result = workflow.run(_make_request(str(proj_dir), fake_cli))

    assert result.outcome == "private-skip", (
        f"a raising datasheet lookup must never turn into outcome=failed; "
        f"got {result.outcome!r} - {result.message!r}"
    )
    lookup_findings = [f for f in result.findings if f.field == "datasheet_lookup_failed"]
    assert len(lookup_findings) == 1, (
        f"expected exactly one datasheet_lookup_failed advisory finding; "
        f"got fields={[f.field for f in result.findings]}"
    )


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


def test_active_project_fails_preflight_without_kicad_python(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """kproj#10: a missing KiCad-bundled Python fails step 5a pre-flight.

    The iBOM script needs the interpreter that can ``import pcbnew``.
    When it cannot be located, pre-flight returns ``outcome="failed"``,
    ``exit_code=2`` before any change journal opens - the same class as
    a missing iBOM script.
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

    fake_ibom = tmp_path / "generate_interactive_bom.py"
    fake_ibom.write_text("")

    def _no_python() -> Path:
        raise KicadNotFoundError(
            "KiCad's bundled Python interpreter (the one that can 'import pcbnew') was not found."
        )

    workflow = PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_silent_design_analyzer_factory(),
        ibom_script_locator=_stub_ibom_locator(fake_ibom),
        kicad_python_locator=_no_python,
    )
    result = workflow.run(_make_request(str(proj_dir), fake_cli))
    assert result.outcome == "failed"
    assert result.exit_code == 2
    assert "pcbnew" in result.message


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
        kicad_python: Path,
        _site_repo: Path,
        _site_profile: object,
        inventory: Path | None,
        fabricator: str,
        ibom_extra_fields: tuple[str, ...],
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
        del inventory, fabricator, ibom_extra_fields
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
    # No partial markdown on disk (mechanical failure before any writes).
    versions_dir = site / GENERIC_SITE_PROFILE.versions_dir
    assert not versions_dir.exists() or not list(versions_dir.rglob("*.md"))


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
        kicad_python: Path,
        _site_repo: Path,
        _site_profile: object,
        inventory: Path | None,
        fabricator: str,
        ibom_extra_fields: tuple[str, ...],
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
        del inventory, fabricator, ibom_extra_fields
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
    fake_python = tmp_path / "kicad-python3"
    fake_python.write_text("")
    return PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_silent_design_analyzer_factory(),
        ibom_script_locator=_stub_ibom_locator(fake_ibom),
        kicad_python_locator=lambda: fake_python,
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
    inventory: Path | None = None,
    fabricator: str = DEFAULT_FABRICATOR,
    ibom_extra_fields: tuple[str, ...] = DEFAULT_IBOM_EXTRA_FIELDS,
) -> PublishRequest:
    config = KprojConfig(
        site_repo=site_repo,
        no_push=no_push,
        kicad_cli=kicad_cli,
        site_profile=GENERIC_SITE_PROFILE,
        inventory=inventory,
        fabricator=fabricator,
        ibom_extra_fields=ibom_extra_fields,
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


def test_regenerates_when_existing_publish_lacks_publish_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy pages without publish context should trigger one regeneration."""
    import subprocess

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
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))

    project = "demo"
    board_rev = "1.0"
    version_file = site / GENERIC_SITE_PROFILE.versions_dir / project / f"{board_rev}.md"
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(
        "---\n"
        "project: demo\n"
        "title: 1.0\n"
        "date: 2026-01-01T00:00:00+00:00\n"
        "---\n"
        "legacy\n",
        encoding="utf-8",
    )
    project_index = GENERIC_SITE_PROFILE.project_index_path(site, project)
    project_index.parent.mkdir(parents=True, exist_ok=True)
    project_index.write_text("---\ntitle: demo\nproject: demo\n---\n", encoding="utf-8")
    asset_dir = site / GENERIC_SITE_PROFILE.assets_dir / project / board_rev
    asset_dir.mkdir(parents=True, exist_ok=True)
    for suffix in (
        "top.png",
        "bottom.png",
        "sch.svg",
        "sch.pdf",
        "ibom.html",
        "step",
        "source.zip",
    ):
        (asset_dir / f"{project}-{board_rev}.{suffix}").write_bytes(b"legacy")

    subprocess.run(["git", "add", "-A"], cwd=site, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "seed legacy publish"],
        cwd=site,
        check=True,
        capture_output=True,
        text=True,
    )

    fake_ibom = tmp_path / "generate_interactive_bom.py"
    fake_ibom.write_text("")
    fake_python = tmp_path / "kicad-python3"
    fake_python.write_text("")
    generator_calls: list[int] = []

    def _recording_gen(
        resolved: object,
        project_info: object,
        kicad_cli: Path,
        ibom_script: Path,
        kicad_python: Path,
        _site_repo: Path,
        _site_profile: object,
        inventory: Path | None,
        fabricator: str,
        ibom_extra_fields: tuple[str, ...],
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
        del (
            resolved,
            project_info,
            kicad_cli,
            ibom_script,
            kicad_python,
            _site_repo,
            _site_profile,
            inventory,
            fabricator,
            ibom_extra_fields,
            journal,
        )
        generator_calls.append(1)
        return (), (), ()

    workflow = PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_silent_design_analyzer_factory(),
        ibom_script_locator=_stub_ibom_locator(fake_ibom),
        kicad_python_locator=lambda: fake_python,
        artifact_generator=_recording_gen,
        site_publisher_factory=_stub_site_publisher_factory(site),
    )
    request = _make_full_request(str(proj_dir), fake_cli, site, no_push=True)
    with patch("kproj.services.site_publisher._git_run"):
        workflow.run(request)

    assert len(generator_calls) == 1, (
        "legacy version pages without kproj_publish_context should trigger a regeneration pass"
    )


def test_republish_request_forces_regeneration_even_when_sources_are_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``republish=True`` bypasses unchanged checks and reruns producers."""
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
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))

    seed_workflow = _full_pipeline_workflow(tmp_path, site, monkeypatch)
    seed_request = _make_full_request(str(proj_dir), fake_cli, site, no_push=True)
    first = seed_workflow.run(seed_request)
    assert first.outcome in {"published", "refreshed"}

    fake_ibom = tmp_path / "generate_interactive_bom.py"
    fake_ibom.write_text("")
    fake_python = tmp_path / "kicad-python3"
    fake_python.write_text("")
    generator_calls: list[int] = []

    def _recording_gen(
        resolved: object,
        project_info: object,
        kicad_cli: Path,
        ibom_script: Path,
        kicad_python: Path,
        _site_repo: Path,
        _site_profile: object,
        inventory: Path | None,
        fabricator: str,
        ibom_extra_fields: tuple[str, ...],
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
        del (
            resolved,
            project_info,
            kicad_cli,
            ibom_script,
            kicad_python,
            _site_repo,
            _site_profile,
            inventory,
            fabricator,
            ibom_extra_fields,
            journal,
        )
        generator_calls.append(1)
        return (), (), ()

    force_workflow = PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_silent_design_analyzer_factory(),
        ibom_script_locator=_stub_ibom_locator(fake_ibom),
        kicad_python_locator=lambda: fake_python,
        artifact_generator=_recording_gen,
        site_publisher_factory=_stub_site_publisher_factory(site),
    )
    force_request = replace(seed_request, republish=True)
    with patch("kproj.services.site_publisher._git_run"):
        force_workflow.run(force_request)

    assert len(generator_calls) == 1, (
        "--republish/--force should rerun artifact generation even when sources are unchanged"
    )


def test_full_publish_detects_github_link_once_and_shares_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full publish calls ``detect_github_link`` exactly once end-to-end.

    Human ruling on kproj#30: covers the seam the private-skip-only test
    (``test_run_detects_github_link_exactly_once_per_publish``) can't -
    that a *full* publish (which also calls ``build_publication`` at
    step 9) doesn't perform a second, independent detection pass there.
    Also asserts the front-matter ``github_url`` and the absence of a
    ``github_link_*`` advisory finding agree (both derived from the one
    detection) for a pushed-GitHub-repo project.
    """
    import subprocess

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

    # Turn the project directory into a pushed GitHub repo (local-only
    # metadata; see tests/unit/common/test_github_link.py for the
    # seeding technique).
    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=proj_dir, check=True, capture_output=True, text=True)

    _git("init", "-q")
    _git("config", "user.email", "test@test.com")
    _git("config", "user.name", "Test")
    _git("add", "-A")
    _git("commit", "-q", "-m", "initial")
    _git("branch", "-M", "main")
    _git("remote", "add", "origin", "git@github.com:plocher/demo.git")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=proj_dir, check=True, capture_output=True, text=True
    ).stdout.strip()
    _git("update-ref", "refs/remotes/origin/main", head)
    _git("config", "branch.main.remote", "origin")
    _git("config", "branch.main.merge", "refs/heads/main")

    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))

    real_subprocess_run = github_link_module.subprocess_run
    work_tree_probe_calls: list[tuple[str, ...]] = []

    def _counting_subprocess_run(command: list[str], **kwargs: object) -> object:
        if "--is-inside-work-tree" in command:
            work_tree_probe_calls.append(tuple(command))
        return real_subprocess_run(command, **kwargs)

    monkeypatch.setattr(github_link_module, "subprocess_run", _counting_subprocess_run)

    workflow = _full_pipeline_workflow(tmp_path, site, monkeypatch)
    request = _make_full_request(str(proj_dir), fake_cli, site)

    with patch("kproj.services.site_publisher._git_run"):
        result = workflow.run(request)

    assert result.outcome in ("published", "refreshed", "noop")
    assert len(work_tree_probe_calls) == 1, (
        f"expected exactly one detect_github_link pass across the whole "
        f"publish (read+analyze AND build_publication); got "
        f"{len(work_tree_probe_calls)}: {work_tree_probe_calls}"
    )
    assert not any(f.field.startswith("github_link_") for f in result.findings), (
        "a pushed GitHub repo must not get a github_link_missing/unpushed advisory"
    )

    version_file = site / GENERIC_SITE_PROFILE.versions_dir / "demo" / "1.0.md"
    assert version_file.exists(), f"{version_file} not found"
    content = version_file.read_text(encoding="utf-8")
    assert "github_url: https://github.com/plocher/demo" in content, (
        f"expected github_url in front-matter:\n{content[:800]}"
    )


def test_second_publish_refreshes_metadata_when_project_becomes_pushed_github_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """kproj#49: second run refreshes metadata after non-repo → pushed-repo transition."""
    import subprocess

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
    request = _make_full_request(str(proj_dir), fake_cli, site, no_push=True)
    caplog.set_level(logging.INFO, logger="kproj.application.publish_workflow")

    # Initial publish while the project directory is NOT a git repo.
    first = workflow.run(request)
    assert first.outcome in {"published", "refreshed"}

    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=proj_dir, check=True, capture_output=True, text=True)

    # Convert the project into a pushed GitHub repo using local-only
    # metadata seeding (no network).
    _git("init", "-q")
    _git("config", "user.email", "test@test.com")
    _git("config", "user.name", "Test")
    _git("add", "-A")
    _git("commit", "-q", "-m", "initial")
    _git("branch", "-M", "main")
    _git("remote", "add", "origin", "git@github.com:plocher/demo.git")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=proj_dir, check=True, capture_output=True, text=True
    ).stdout.strip()
    _git("update-ref", "refs/remotes/origin/main", head)
    _git("config", "branch.main.remote", "origin")
    _git("config", "branch.main.merge", "refs/heads/main")

    second = workflow.run(request)
    assert second.outcome == "refreshed", (
        "expected metadata-only refresh after project git metadata changes "
        "from non-repo to pushed GitHub repo"
    )
    assert "Refreshed demo-1.0" in second.message

    version_file = site / GENERIC_SITE_PROFILE.versions_dir / "demo" / "1.0.md"
    content = version_file.read_text(encoding="utf-8")
    assert "github_url: https://github.com/plocher/demo" in content, (
        f"expected github_url in refreshed front-matter:\n{content[:800]}"
    )
    assert "github_link_missing" not in content
    assert "github_link_unpushed" not in content
    assert any(
        "metadata drift for demo-1.0: github_url changed" in record.message
        for record in caplog.records
    ), "expected explicit metadata-drift log line"
    assert any(
        "artifact regeneration decision for demo-1.0: "
        "skip (sources unchanged; metadata drift: github_url changed)" in record.message
        for record in caplog.records
    ), "expected regeneration decision log to include metadata-drift reason"


def test_transition_from_parent_repo_to_project_repo_refreshes_github_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """kproj#49: ignore parent repos until the project directory is git-init'd."""
    import subprocess

    def _git(cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

    def _seed_pushed_origin(cwd: Path, remote_url: str) -> None:
        _git(cwd, "config", "user.email", "test@test.com")
        _git(cwd, "config", "user.name", "Test")
        _git(cwd, "add", "-A")
        _git(cwd, "commit", "-q", "-m", "initial")
        _git(cwd, "branch", "-M", "main")
        _git(cwd, "remote", "add", "origin", remote_url)
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=cwd, check=True, capture_output=True, text=True
        ).stdout.strip()
        _git(cwd, "update-ref", "refs/remotes/origin/main", head)
        _git(cwd, "config", "branch.main.remote", "origin")
        _git(cwd, "config", "branch.main.merge", "refs/heads/main")

    site = _make_site_repo(tmp_path)
    workspace_root = tmp_path / "workspace"
    proj_dir = make_minimal_project(
        workspace_root / "demo",
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

    # Parent repo exists, but the project directory itself is not a repo yet.
    _git(workspace_root, "init", "-q")
    _seed_pushed_origin(workspace_root, "git@github.com:plocher/demo.git")

    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    _stub_kicad_version(monkeypatch, (9, 0, 4))

    workflow = _full_pipeline_workflow(tmp_path, site, monkeypatch)
    request = _make_full_request(str(proj_dir), fake_cli, site, no_push=True)

    first = workflow.run(request)
    assert first.outcome in {"published", "refreshed"}
    version_file = site / GENERIC_SITE_PROFILE.versions_dir / "demo" / "1.0.md"
    first_content = version_file.read_text(encoding="utf-8")
    assert "github_url:" not in first_content, (
        "project nested under a parent repo must be treated as not-a-repo "
        "until the project directory itself is git-init'd"
    )

    # Now convert the project directory into its own pushed repo.
    _git(proj_dir, "init", "-q")
    _seed_pushed_origin(proj_dir, "git@github.com:plocher/demo.git")

    second = workflow.run(request)
    assert second.outcome == "refreshed"
    second_content = version_file.read_text(encoding="utf-8")
    assert "github_url: https://github.com/plocher/demo" in second_content


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
    fake_python = tmp_path / "kicad-python3"
    fake_python.write_text("")

    captured: dict[str, object] = {}

    def _recording_gen(
        resolved: object,
        project_info: object,
        kicad_cli: Path,
        ibom_script: Path,
        kicad_python: Path,
        _site_repo: Path,
        _site_profile: object,
        inventory: Path | None,
        fabricator: str,
        ibom_extra_fields: tuple[str, ...],
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
        del inventory, fabricator, ibom_extra_fields
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
        kicad_python_locator=lambda: fake_python,
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


def test_artifact_generator_receives_inventory_and_fabricator_and_ibom_extra_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """kproj#48: workflow passes inventory/fabricator/iBOM field config to generators."""
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
    fake_python = tmp_path / "kicad-python3"
    fake_python.write_text("")

    captured: dict[str, object] = {}

    def _recording_gen(
        resolved: object,
        project_info: object,
        kicad_cli: Path,
        ibom_script: Path,
        kicad_python: Path,
        _site_repo: Path,
        _site_profile: object,
        inventory: Path | None,
        fabricator: str,
        ibom_extra_fields: tuple[str, ...],
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
        del (
            resolved,
            project_info,
            kicad_cli,
            ibom_script,
            kicad_python,
            _site_repo,
            _site_profile,
        )
        del journal
        captured["inventory"] = inventory
        captured["fabricator"] = fabricator
        captured["ibom_extra_fields"] = ibom_extra_fields
        return (), (), ()

    workflow = PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_silent_design_analyzer_factory(),
        ibom_script_locator=_stub_ibom_locator(fake_ibom),
        kicad_python_locator=lambda: fake_python,
        artifact_generator=_recording_gen,
        site_publisher_factory=_stub_site_publisher_factory(site),
    )
    inventory_path = tmp_path / "inventory.csv"
    inventory_path.write_text("IPN,Category,Value,Package\n", encoding="utf-8")
    request = _make_full_request(
        str(proj_dir),
        fake_cli,
        site,
        inventory=inventory_path,
        fabricator="pcbway",
        ibom_extra_fields=("Manufacturer", "MFGPN"),
    )

    with patch("kproj.services.site_publisher._git_run"):
        workflow.run(request)

    assert captured["inventory"] == inventory_path
    assert captured["fabricator"] == "pcbway"
    assert captured["ibom_extra_fields"] == ("Manufacturer", "MFGPN")


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
    fake_python = tmp_path / "kicad-python3"
    fake_python.write_text("")

    def _exploding_gen(
        resolved: object,
        project_info: object,
        kicad_cli: Path,
        ibom_script: Path,
        kicad_python: Path,
        _site_repo: Path,
        _site_profile: object,
        inventory: Path | None,
        fabricator: str,
        ibom_extra_fields: tuple[str, ...],
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
        del inventory, fabricator, ibom_extra_fields
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
        kicad_python_locator=lambda: fake_python,
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

    fake_python = tmp_path / "kicad-python3"
    fake_python.write_text("")

    def _gen_with_diagnostics(
        resolved: object,
        project_info: object,
        kicad_cli: Path,
        ibom_script: Path,
        kicad_python: Path,
        _site_repo: Path,
        _site_profile: object,
        inventory: Path | None,
        fabricator: str,
        ibom_extra_fields: tuple[str, ...],
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[Finding, ...]]:
        del inventory, fabricator, ibom_extra_fields
        # Return no asset refs; just surface a producer-stage diagnostic.
        return (), (), (producer_warning,)

    workflow = PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=tmp_path),
        design_analyzer_factory=_silent_design_analyzer_factory(),
        ibom_script_locator=_stub_ibom_locator(fake_ibom),
        kicad_python_locator=lambda: fake_python,
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
