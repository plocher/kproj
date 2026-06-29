"""Unit tests for :mod:`kproj.cli`.

Validates the user-facing surface (positional + flags) per
``docs/DESIGN.md`` § *CLI surface mechanics* and the exit-code mapping
per § *Exit code mapping*. Per ADR 0006, ``argparse`` lives only inside
``cli.py`` — these tests poke at the public ``main()`` and ``build_request``
helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kproj import cli
from kproj.application.publish_workflow import PublishRequest, PublishResult
from kproj.model.finding import Finding
from kproj.model.severity import Severity

# ----------------------------------------------------------------------
# Argparse surface
# ----------------------------------------------------------------------


def test_parse_args_defaults_to_cwd_positional() -> None:
    """No positional argument → project_arg defaults to ``"."``."""
    parsed = cli.parse_args([])
    assert parsed.project == "."
    assert parsed.site_repo is None
    assert parsed.dry_run is False
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
            "--dry-run",
            "--no-push",
            "-v",
            "-d",
        ]
    )
    assert parsed.project == "/tmp/proj"
    assert parsed.site_repo == "/tmp/site"
    assert parsed.dry_run is True
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


# ----------------------------------------------------------------------
# build_request: Namespace + env → ConfigOverrides + PublishRequest
# ----------------------------------------------------------------------


def test_build_request_propagates_cli_overrides(tmp_path: Path) -> None:
    """CLI flags surface as :class:`ConfigOverrides` non-None fields."""
    parsed = cli.parse_args(["/tmp/proj", "--site-repo", str(tmp_path), "--dry-run", "--no-push"])
    request = cli.build_request(parsed, env={}, yaml_path=tmp_path / "missing.yaml")
    assert isinstance(request, PublishRequest)
    assert request.project_arg == "/tmp/proj"
    assert request.dry_run is True
    assert request.config.site_repo == tmp_path
    assert request.config.no_push is True


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

    monkeypatch.setattr(cli, "PublishWorkflow", _StubWorkflow)
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

    monkeypatch.setattr(cli, "PublishWorkflow", _CleanWorkflow)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("KPROJ_SITE_REPO", raising=False)
    monkeypatch.delenv("KPROJ_NO_PUSH", raising=False)
    monkeypatch.delenv("KPROJ_KICAD_CLI", raising=False)
    assert cli.main(["/tmp/proj"]) == 0
