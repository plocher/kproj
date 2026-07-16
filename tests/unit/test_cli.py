"""Unit tests for :mod:`kproj.cli`.

Validates the user-facing surface (positional + flags) per
``docs/DESIGN.md`` § *CLI surface mechanics* and the exit-code mapping
per § *Exit code mapping*. Per ADR 0006, ``argparse`` lives only inside
``src/kproj/cli/main.py`` - these tests poke at the public ``main()``
and ``build_request`` helpers.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

from kproj import cli
from kproj.application.publish_workflow import PublishRequest, PublishResult
from kproj.model.finding import Finding
from kproj.model.severity import Severity
from kproj.model.site_management import DeleteResult, ProjectListResult

cli_main = importlib.import_module("kproj.cli.main")

# ----------------------------------------------------------------------
# Argparse surface
# ----------------------------------------------------------------------


def test_parse_args_defaults_to_cwd_positional() -> None:
    """No positional argument → project_arg defaults to ``"."``."""
    parsed = cli.parse_args([])
    assert parsed.project == "."
    assert parsed.site_repo is None
    assert parsed.inventory is None
    assert parsed.datasheet_library is None
    assert parsed.datasheet_repo is None
    assert parsed.fabricator is None
    assert parsed.dry_run is False
    assert parsed.republish is False
    assert parsed.no_push is False
    assert parsed.verbose == 0
    assert parsed.debug is False


def test_parse_args_supports_all_documented_flags() -> None:
    """Every flag in DESIGN § CLI surface mechanics is wired up."""
    parsed = cli.parse_args(
        [
            "/tmp/proj",
            "--site-repo",
            "/tmp/site",
            "--inventory",
            "/tmp/inventory.csv",
            "--datasheet-library",
            "/tmp/datasheets",
            "--datasheet-repo",
            "example/datasheets",
            "--fabricator",
            "jlc",
            "--dry-run",
            "--republish",
            "--no-push",
            "-v",
            "-d",
        ]
    )
    assert parsed.project == "/tmp/proj"
    assert parsed.site_repo == "/tmp/site"
    assert parsed.inventory == "/tmp/inventory.csv"
    assert parsed.datasheet_library == "/tmp/datasheets"
    assert parsed.datasheet_repo == "example/datasheets"
    assert parsed.fabricator == "jlc"
    assert parsed.dry_run is True
    assert parsed.republish is True
    assert parsed.no_push is True
    assert parsed.verbose == 1
    assert parsed.debug is True


def test_parse_args_verbose_is_a_count_flag() -> None:
    """``-vv`` stacks the verbose count to 2."""
    parsed = cli.parse_args(["-vv"])
    assert parsed.verbose == 2


def test_parse_args_long_form_verbose() -> None:
    """``--verbose`` is the documented long form."""
    parsed = cli.parse_args(["--verbose"])
    assert parsed.verbose == 1


def test_parse_args_force_alias_sets_republish() -> None:
    """``--force`` aliases ``--republish``."""
    parsed = cli.parse_args(["--force"])
    assert parsed.republish is True


def test_parse_args_project_list_command() -> None:
    """The project list command parses as a non-publish command."""
    parsed = cli.parse_args(["project", "--list"])
    assert parsed.command == "project"
    assert parsed.list_projects is True
    assert parsed.site_repo is None


def test_parse_args_delete_version_command() -> None:
    """Version-scoped delete command parses project + version + force flags."""
    parsed = cli.parse_args(["delete", "Demo", "--version", "1.0", "--force"])
    assert parsed.command == "delete"
    assert parsed.project == "Demo"
    assert parsed.version == "1.0"
    assert parsed.force is True


def test_parse_args_delete_project_preview_command() -> None:
    """Bare delete parses as preview-mode input (no version, no force)."""
    parsed = cli.parse_args(["delete", "Demo"])
    assert parsed.command == "delete"
    assert parsed.project == "Demo"
    assert parsed.version is None
    assert parsed.force is False


# ----------------------------------------------------------------------
# build_request: Namespace + env → ConfigOverrides + PublishRequest
# ----------------------------------------------------------------------


def test_build_request_propagates_cli_overrides(tmp_path: Path) -> None:
    """CLI flags surface as :class:`ConfigOverrides` non-None fields."""
    parsed = cli.parse_args(
        [
            "/tmp/proj",
            "--site-repo",
            str(tmp_path),
            "--inventory",
            str(tmp_path / "inventory.csv"),
            "--datasheet-library",
            str(tmp_path / "datasheets"),
            "--datasheet-repo",
            "example/datasheets",
            "--fabricator",
            "pcbway",
            "--dry-run",
            "--republish",
            "--no-push",
        ]
    )
    request = cli.build_request(parsed, env={}, yaml_path=tmp_path / "missing.yaml")
    assert isinstance(request, PublishRequest)
    assert request.project_arg == "/tmp/proj"
    assert request.dry_run is True
    assert request.republish is True
    assert request.config.site_repo == tmp_path
    assert request.config.no_push is True
    assert request.config.inventory == tmp_path / "inventory.csv"
    assert request.config.datasheet_library == tmp_path / "datasheets"
    assert request.config.datasheet_repo == "example/datasheets"
    assert request.config.fabricator == "pcbway"


def test_help_documents_config_precedence_and_yaml_example(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``kproj --help`` makes yaml/env/precedence discoverable."""
    with pytest.raises(SystemExit) as exc_info:
        cli.parse_args(["--help"])
    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "CLI flag > KPROJ_* environment variable > ~/.kproj.yaml > default" in help_text
    assert "KPROJ_INVENTORY" in help_text
    assert "KPROJ_DATASHEET_LIBRARY" in help_text
    assert "KPROJ_DATASHEET_REPO" in help_text
    assert "KPROJ_FABRICATOR" in help_text
    assert "site_repo:" in help_text
    assert "datasheet_library:" in help_text
    assert "datasheet_repo:" in help_text
    assert "fabricator:" in help_text


def test_help_explains_no_push_batch_flush(capsys: pytest.CaptureFixture[str]) -> None:
    """``--no-push`` help tells users how a final plain run flushes batches."""
    with pytest.raises(SystemExit):
        cli.parse_args(["--help"])
    assert "final plain run flushes pending site commits" in capsys.readouterr().out


def test_first_run_hint_emitted_when_no_yaml_and_no_inventory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """kproj#37: an INFO hint fires when ~/.kproj.yaml is absent and inventory is unset.

    Calls ``_emit_first_run_hint`` directly (bypassing ``configure_logging``'s
    ``propagate = False`` side effect on the ``kproj`` logger, which would
    otherwise make this hint invisible to pytest's root-attached ``caplog``).
    """
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(cli_main._log, "info", lambda *args: calls.append(args))
    cli_main._emit_first_run_hint(yaml_path=tmp_path / ".kproj.yaml", inventory=None)
    assert len(calls) == 1


def test_first_run_hint_suppressed_when_inventory_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No hint when the user has already configured an inventory."""
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(cli_main._log, "info", lambda *args: calls.append(args))
    cli_main._emit_first_run_hint(
        yaml_path=tmp_path / ".kproj.yaml", inventory=tmp_path / "inventory.csv"
    )
    assert calls == []


def test_first_run_hint_suppressed_when_yaml_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No hint when ~/.kproj.yaml exists, even with inventory unset."""
    yaml_path = tmp_path / ".kproj.yaml"
    yaml_path.write_text("site_repo: /x\n")
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(cli_main._log, "info", lambda *args: calls.append(args))
    cli_main._emit_first_run_hint(yaml_path=yaml_path, inventory=None)
    assert calls == []


def test_build_request_omits_no_push_override_when_flag_not_given(
    tmp_path: Path,
) -> None:
    """Without ``--no-push``, the override is ``None`` (fall through to env)."""
    parsed = cli.parse_args(["/tmp/proj"])
    request = cli.build_request(
        parsed,
        env={"KPROJ_NO_PUSH": "1"},
        yaml_path=tmp_path / "missing.yaml",
    )
    assert request.config.no_push is True


# ----------------------------------------------------------------------
# Exit-code mapping
# ----------------------------------------------------------------------


def _result(outcome: str, exit_code: int, findings: tuple[Finding, ...] = ()) -> PublishResult:
    return PublishResult(
        outcome=outcome,  # type: ignore[arg-type]
        exit_code=exit_code,
        findings=findings,
    )


@pytest.mark.parametrize(
    ("outcome", "findings", "expected"),
    [
        ("published", (), 0),
        ("refreshed", (), 0),
        ("noop", (), 0),
        ("private-skip", (), 0),
        (
            "published",
            (Finding(severity=Severity.WARNING, field="x", value="", reason=""),),
            1,
        ),
        (
            "noop",
            (Finding(severity=Severity.ERROR, field="x", value="", reason=""),),
            1,
        ),
        # exclusions are intentionally-suppressed: still exit 0
        (
            "published",
            (Finding(severity=Severity.EXCLUSION, field="x", value="", reason=""),),
            0,
        ),
        ("failed", (), 2),
    ],
)
def test_resolve_exit_code_matches_design(
    outcome: str, findings: tuple[Finding, ...], expected: int
) -> None:
    """:func:`kproj.cli.resolve_exit_code` maps PublishResult → process exit code."""
    assert cli.resolve_exit_code(_result(outcome, expected, findings)) == expected


def test_resolve_exit_code_honours_explicit_failed_exit_code() -> None:
    """An explicit ``exit_code=2`` from the workflow always wins."""
    result = PublishResult(outcome="failed", exit_code=2)
    assert cli.resolve_exit_code(result) == 2


# ----------------------------------------------------------------------
# main(): glue + side-effect test
# ----------------------------------------------------------------------


def test_main_delegates_to_publish_workflow(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """``main`` calls :class:`PublishWorkflow.run` and returns its exit code."""
    captured_request: dict[str, Any] = {}

    class _StubWorkflow:
        def run(self, request: PublishRequest) -> PublishResult:
            captured_request["request"] = request
            return PublishResult(
                outcome="failed",
                exit_code=2,
                message="kproj: stub workflow",
            )

    monkeypatch.setattr(cli_main, "PublishWorkflow", _StubWorkflow)
    monkeypatch.setenv("HOME", str(tmp_path))  # isolate ~/.kproj.yaml
    monkeypatch.delenv("KPROJ_SITE_REPO", raising=False)
    monkeypatch.delenv("KPROJ_NO_PUSH", raising=False)
    monkeypatch.delenv("KPROJ_KICAD_CLI", raising=False)
    exit_code = cli.main(["/tmp/proj", "--dry-run"])
    assert exit_code == 2
    request = captured_request["request"]
    assert request.project_arg == "/tmp/proj"
    assert request.dry_run is True
    captured = capsys.readouterr()
    assert "kproj: stub workflow" in captured.err


def test_main_exit_code_zero_on_clean_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A clean PublishResult (no findings, success outcome) exits 0."""

    class _CleanWorkflow:
        def run(self, request: PublishRequest) -> PublishResult:
            return PublishResult(outcome="published", exit_code=0)

    monkeypatch.setattr(cli_main, "PublishWorkflow", _CleanWorkflow)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("KPROJ_SITE_REPO", raising=False)
    monkeypatch.delenv("KPROJ_NO_PUSH", raising=False)
    monkeypatch.delenv("KPROJ_KICAD_CLI", raising=False)
    assert cli.main(["/tmp/proj"]) == 0


def test_main_dispatches_project_list_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """`kproj project --list` dispatches to the site-management workflow."""

    class _StubSiteWorkflow:
        def list_projects(self, _config: object) -> ProjectListResult:
            return ProjectListResult(exit_code=0, message="Project: Demo\nVersions: 1.0, 1.1")

        def delete(self, _request: object) -> DeleteResult:
            return DeleteResult(outcome="failed", exit_code=2, message="unexpected delete")

    monkeypatch.setattr(cli_main, "SiteManagementWorkflow", _StubSiteWorkflow)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("KPROJ_SITE_REPO", raising=False)
    monkeypatch.delenv("KPROJ_NO_PUSH", raising=False)
    monkeypatch.delenv("KPROJ_KICAD_CLI", raising=False)

    exit_code = cli.main(["project", "--list"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Project: Demo" in captured.err


def test_main_dispatches_delete_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """`kproj delete ...` dispatches to the site-management delete path."""

    class _StubSiteWorkflow:
        def list_projects(self, _config: object) -> ProjectListResult:
            return ProjectListResult(exit_code=2, message="unexpected list")

        def delete(self, _request: object) -> DeleteResult:
            return DeleteResult(
                outcome="deleted-version", exit_code=0, message="Info: Deleted version Demo-1.0."
            )

    monkeypatch.setattr(cli_main, "SiteManagementWorkflow", _StubSiteWorkflow)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("KPROJ_SITE_REPO", raising=False)
    monkeypatch.delenv("KPROJ_NO_PUSH", raising=False)
    monkeypatch.delenv("KPROJ_KICAD_CLI", raising=False)

    exit_code = cli.main(["delete", "Demo", "--version", "1.0"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Deleted version" in captured.err


# ----------------------------------------------------------------------
# BLOCKER 4 regressions: findings must surface on stderr (ADR 0004)
# ----------------------------------------------------------------------


def _stub_workflow_returning(result: PublishResult) -> type:
    """Return a stub workflow class whose ``run`` returns *result* verbatim."""

    class _Stub:
        def run(self, request: PublishRequest) -> PublishResult:
            return result

    return _Stub


def test_main_prints_findings_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """ADR 0004: every audit/DRC/ERC finding must be printed to stderr.

    The pre-fix CLI emitted only ``result.message``; findings only
    showed up via the exit code (and indirectly in the version page),
    never on the user's terminal.  The fix wires ``StderrFormatter``
    into ``main()`` so every Finding is one stderr line.
    """
    findings = (
        Finding(
            severity=Severity.WARNING,
            field="comment9_missing",
            value="",
            reason="COMMENT9 absent",
            project="Demo",
        ),
        Finding(
            severity=Severity.ERROR,
            field="drc_violation",
            value="(50, 75)",
            reason="silk overlap",
            project="Demo",
        ),
    )
    result = PublishResult(
        outcome="published",
        exit_code=1,
        message="kproj: published Demo-1.0B.",
        findings=findings,
    )
    monkeypatch.setattr(cli_main, "PublishWorkflow", _stub_workflow_returning(result))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("KPROJ_SITE_REPO", raising=False)
    monkeypatch.delenv("KPROJ_NO_PUSH", raising=False)
    monkeypatch.delenv("KPROJ_KICAD_CLI", raising=False)

    exit_code = cli.main(["/tmp/proj"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Warning: COMMENT9 absent" in captured.err, (
        f"issue #43: human finding message missing from stderr; got: {captured.err!r}"
    )
    assert "Error: silk overlap" in captured.err
    assert "silk overlap" in captured.err


def test_main_emits_nothing_extra_when_findings_empty(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """An empty findings tuple must not add noise on stderr."""
    result = PublishResult(
        outcome="published",
        exit_code=0,
        message="kproj: published Demo-1.0B.",
        findings=(),
    )
    monkeypatch.setattr(cli_main, "PublishWorkflow", _stub_workflow_returning(result))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("KPROJ_SITE_REPO", raising=False)
    monkeypatch.delenv("KPROJ_NO_PUSH", raising=False)
    monkeypatch.delenv("KPROJ_KICAD_CLI", raising=False)

    cli.main(["/tmp/proj"])
    captured = capsys.readouterr()

    # The only stderr content should be the result message itself.
    assert captured.err.strip() == "kproj: published Demo-1.0B."
