"""Unit tests for :mod:`kproj.services.design_analyzer`.

Exercises the DRC + ERC subprocess wiring + JSON parser using a fake
:func:`subprocess.run` that writes a canned JSON payload to the
``--output`` path argv carries.  No real ``kicad-cli`` is invoked.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from kproj.common.subprocess_runner import SubprocessResult
from kproj.model.resolved_project import ResolvedProject
from kproj.model.severity import Severity
from kproj.services.design_analyzer import DesignAnalysisError, DesignAnalyzer


def _resolved(tmp_path: Path) -> ResolvedProject:
    """Construct a minimal :class:`ResolvedProject` for DesignAnalyzer."""
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    pcb = project_dir / "demo.kicad_pcb"
    sch = project_dir / "demo.kicad_sch"
    pcb.write_text("")
    sch.write_text("")
    (project_dir / "demo.kicad_pro").write_text("{}")
    return ResolvedProject(
        project_file=project_dir / "demo.kicad_pro",
        project_dir=project_dir,
        pcb_file=pcb,
        root_schematic=sch,
        hierarchical_schematics=(sch,),
        jbom_resolved=None,
    )


def _fake_runner(
    drc_payload: dict[str, Any] | None = None,
    erc_payload: dict[str, Any] | None = None,
    *,
    write_drc: bool = True,
    write_erc: bool = True,
) -> tuple[Any, list[Sequence[str]]]:
    """Return a (runner, recorded_commands) pair for tests to inspect."""
    recorded: list[Sequence[str]] = []

    def runner(command: Sequence[str], **_kwargs: Any) -> SubprocessResult:
        recorded.append(tuple(command))
        # Find the --output path the implementation passed.
        cmd_list = list(command)
        out_index = cmd_list.index("--output")
        output_path = Path(cmd_list[out_index + 1])
        if "drc" in cmd_list and write_drc and drc_payload is not None:
            output_path.write_text(json.dumps(drc_payload), encoding="utf-8")
        if "erc" in cmd_list and write_erc and erc_payload is not None:
            output_path.write_text(json.dumps(erc_payload), encoding="utf-8")
        return SubprocessResult(
            command=tuple(command),
            returncode=0,
            stdout="",
            stderr="",
            elapsed_seconds=0.0,
        )

    return runner, recorded


def test_drc_violation_with_items_emits_per_item_finding(tmp_path: Path) -> None:
    """Each item under a DRC violation produces one :class:`Finding`."""
    payload = {
        "violations": [
            {
                "severity": "warning",
                "type": "silk_overlap",
                "description": "Silkscreen overlap",
                "items": [
                    {"description": "F.SilkS over pad U1", "pos": "10,20"},
                    {"description": "F.SilkS over pad U2", "pos": "15,25"},
                ],
            }
        ]
    }
    runner, _ = _fake_runner(drc_payload=payload, erc_payload={"violations": []})
    analyzer = DesignAnalyzer(tmp_path / "kicad-cli", runner=runner)
    result = analyzer.analyze(_resolved(tmp_path))
    drc_findings = [f for f in result.findings if f.source == "drc"]
    assert len(drc_findings) == 2
    assert {f.field for f in drc_findings} == {"silk_overlap"}
    assert {f.severity for f in drc_findings} == {Severity.WARNING}
    assert drc_findings[0].value == "10,20"


def test_erc_exclusion_severity_preserved(tmp_path: Path) -> None:
    """``exclusion`` severity is mapped to :attr:`Severity.EXCLUSION`."""
    payload = {
        "violations": [
            {
                "severity": "exclusion",
                "type": "pin_to_pin",
                "description": "Suppressed mismatch",
                "items": [{"description": "U1.1", "pos": "0,0"}],
            }
        ]
    }
    runner, _ = _fake_runner(drc_payload={"violations": []}, erc_payload=payload)
    analyzer = DesignAnalyzer(tmp_path / "kicad-cli", runner=runner)
    result = analyzer.analyze(_resolved(tmp_path))
    erc_findings = [f for f in result.findings if f.source == "erc"]
    assert erc_findings and erc_findings[0].severity is Severity.EXCLUSION
    # Exclusions must NOT mark the analysis as "has_findings" per ADR 0004.
    assert result.has_findings is False


def test_runner_receives_severity_all_and_format_json(tmp_path: Path) -> None:
    """The assembled argv passes ``--severity-all`` + ``--format json``."""
    runner, recorded = _fake_runner(drc_payload={"violations": []}, erc_payload={"violations": []})
    analyzer = DesignAnalyzer(tmp_path / "kicad-cli", runner=runner)
    analyzer.analyze(_resolved(tmp_path))
    assert len(recorded) == 2
    drc_cmd = next(cmd for cmd in recorded if "drc" in cmd)
    erc_cmd = next(cmd for cmd in recorded if "erc" in cmd)
    for cmd in (drc_cmd, erc_cmd):
        assert "--format" in cmd
        assert "json" in cmd
        assert "--severity-all" in cmd


def test_no_output_file_and_clean_exit_returns_empty_findings(tmp_path: Path) -> None:
    """M4 fix-up: kicad-cli rc=0 with empty stderr + no JSON → no findings.

    This is the genuine "kicad-cli ran but produced nothing actionable"
    path.  The mechanical-failure detector (rc != 0 OR stderr non-empty)
    is exercised by ``test_no_output_file_with_failure_emits_mechanical_finding``.
    """
    runner, _ = _fake_runner(write_drc=False, write_erc=False)
    analyzer = DesignAnalyzer(tmp_path / "kicad-cli", runner=runner)
    result = analyzer.analyze(_resolved(tmp_path))
    assert result.findings == ()


def test_no_output_file_with_failure_raises_design_analysis_error(tmp_path: Path) -> None:
    """M4 round-2: kicad-cli rc!=0 with no JSON must raise mechanical failure.

    Round-1 modelled the crash as an ordinary error :class:`Finding`,
    but ``compute_exit_code`` then mapped a mechanical failure to
    ``exit=1`` ("findings present, publish succeeded") instead of
    ``exit=2`` ("mechanical failure").  Round-2 gives the mechanical
    failure a distinct channel: :class:`DesignAnalysisError` is
    raised so :class:`~kproj.application.publish_workflow.PublishWorkflow`
    can catch it, short-circuit before opening the change journal,
    and return ``PublishResult(outcome="failed", exit_code=2)`` per
    ADR 0004's mechanical-vs-findings split.
    """

    def runner(command: Sequence[str], **_kwargs: Any) -> SubprocessResult:
        # No JSON file written; nonzero return + stderr context.
        return SubprocessResult(
            command=tuple(command),
            returncode=2,
            stdout="",
            stderr="kicad-cli: segfault probing board\n",
            elapsed_seconds=0.0,
        )

    analyzer = DesignAnalyzer(tmp_path / "kicad-cli", runner=runner)
    with pytest.raises(DesignAnalysisError) as excinfo:
        analyzer.analyze(_resolved(tmp_path))
    # DRC runs before ERC; the DRC failure short-circuits.
    assert excinfo.value.origin == "drc", (
        f"expected DRC to short-circuit first; got origin={excinfo.value.origin!r}"
    )
    assert excinfo.value.returncode == 2
    assert "segfault" in str(excinfo.value)


def test_erc_mechanical_failure_after_clean_drc_raises(tmp_path: Path) -> None:
    """M4 round-2: ERC-only mechanical failure still short-circuits.

    Locks the second subcommand's error handling: even when DRC
    completes cleanly, an ERC mechanical crash must raise
    :class:`DesignAnalysisError` so the workflow returns failed/exit 2.
    """

    def runner(command: Sequence[str], **_kwargs: Any) -> SubprocessResult:
        cmd = list(command)
        if "drc" in cmd:
            out_index = cmd.index("--output")
            Path(cmd[out_index + 1]).write_text(json.dumps({"violations": []}), encoding="utf-8")
            return SubprocessResult(
                command=tuple(command),
                returncode=0,
                stdout="",
                stderr="",
                elapsed_seconds=0.0,
            )
        # ERC crashes without producing JSON.
        return SubprocessResult(
            command=tuple(command),
            returncode=1,
            stdout="",
            stderr="kicad-cli: could not open schematic\n",
            elapsed_seconds=0.0,
        )

    analyzer = DesignAnalyzer(tmp_path / "kicad-cli", runner=runner)
    with pytest.raises(DesignAnalysisError) as excinfo:
        analyzer.analyze(_resolved(tmp_path))
    assert excinfo.value.origin == "erc"
    assert excinfo.value.returncode == 1


def test_violation_without_items_emits_single_finding(tmp_path: Path) -> None:
    """A violation with no ``items`` array yields one violation-level finding."""
    payload = {
        "violations": [
            {
                "severity": "error",
                "type": "drc_mismatch",
                "description": "Solder mask short",
            }
        ]
    }
    runner, _ = _fake_runner(drc_payload=payload, erc_payload={"violations": []})
    analyzer = DesignAnalyzer(tmp_path / "kicad-cli", runner=runner)
    result = analyzer.analyze(_resolved(tmp_path))
    drc_findings = [f for f in result.findings if f.source == "drc"]
    assert len(drc_findings) == 1
    assert drc_findings[0].field == "drc_mismatch"
    assert drc_findings[0].severity is Severity.ERROR


def test_erc_reads_kicad10_per_sheet_shape(tmp_path: Path) -> None:
    """KiCad 10 ERC nests findings under ``sheets[].violations``.

    Wave-3 M12 fix-up: the M12 contract test caught a real drift —
    KiCad 10 ERC no longer emits a top-level ``violations`` array but
    instead a ``sheets`` array whose elements each carry a
    ``violations`` list.  Pre-fix DesignAnalyzer silently returned
    zero findings for KiCad 10 ERC.  This unit test locks the new
    per-sheet parser branch with a canned KiCad-10-shape payload.
    """
    payload = {
        "$schema": "...",
        "kicad_version": "10.0.1",
        "sheets": [
            {
                "path": "/",
                "uuid_path": "/root-uuid",
                "violations": [
                    {
                        "severity": "warning",
                        "type": "unconnected_pin",
                        "description": "U3.5 is floating",
                        "items": [{"description": "U3.5", "pos": "60,70"}],
                    }
                ],
            },
            {
                "path": "/subsheet",
                "uuid_path": "/sub-uuid",
                "violations": [
                    {
                        "severity": "error",
                        "type": "pin_conflict",
                        "description": "conflicting drivers",
                    }
                ],
            },
        ],
    }
    runner, _ = _fake_runner(drc_payload={"violations": []}, erc_payload=payload)
    analyzer = DesignAnalyzer(tmp_path / "kicad-cli", runner=runner)
    result = analyzer.analyze(_resolved(tmp_path))
    erc_findings = [f for f in result.findings if f.source == "erc"]
    fields = {f.field for f in erc_findings}
    assert "unconnected_pin" in fields, (
        f"M12: KiCad 10 ERC per-sheet violation not surfaced; got fields={fields}"
    )
    assert "pin_conflict" in fields, f"M12: nested per-sheet violation missed; got fields={fields}"


def test_erc_reads_unconnected_items_array(tmp_path: Path) -> None:
    """ERC's ``unconnected_items`` array surfaces as findings."""
    payload = {
        "violations": [],
        "unconnected_items": [
            {
                "severity": "warning",
                "type": "unconnected_pin",
                "description": "U3.5 is floating",
                "items": [{"description": "U3.5", "pos": "60,70"}],
            }
        ],
    }
    runner, _ = _fake_runner(drc_payload={"violations": []}, erc_payload=payload)
    analyzer = DesignAnalyzer(tmp_path / "kicad-cli", runner=runner)
    result = analyzer.analyze(_resolved(tmp_path))
    erc_findings = [f for f in result.findings if f.source == "erc"]
    assert erc_findings and erc_findings[0].field == "unconnected_pin"


def test_invalid_json_emits_warning_finding(tmp_path: Path) -> None:
    """Malformed JSON produces a warning :class:`Finding` instead of raising."""

    def runner(command: Sequence[str], **_kwargs: Any) -> SubprocessResult:
        cmd = list(command)
        out_index = cmd.index("--output")
        Path(cmd[out_index + 1]).write_text("not-json", encoding="utf-8")
        return SubprocessResult(
            command=tuple(command),
            returncode=0,
            stdout="",
            stderr="",
            elapsed_seconds=0.0,
        )

    analyzer = DesignAnalyzer(tmp_path / "kicad-cli", runner=runner)
    result = analyzer.analyze(_resolved(tmp_path))
    fields = {f.field for f in result.findings}
    assert "drc_json_unreadable" in fields or "erc_json_unreadable" in fields


def test_tempfile_not_persisted(tmp_path: Path) -> None:
    """No DRC/ERC JSON tempfile remains on disk after ``analyze`` returns."""
    seen_paths: list[Path] = []

    def runner(command: Sequence[str], **_kwargs: Any) -> SubprocessResult:
        cmd = list(command)
        out_index = cmd.index("--output")
        out_path = Path(cmd[out_index + 1])
        out_path.write_text(json.dumps({"violations": []}), encoding="utf-8")
        seen_paths.append(out_path)
        return SubprocessResult(
            command=tuple(command),
            returncode=0,
            stdout="",
            stderr="",
            elapsed_seconds=0.0,
        )

    analyzer = DesignAnalyzer(tmp_path / "kicad-cli", runner=runner)
    analyzer.analyze(_resolved(tmp_path))
    assert seen_paths and all(not p.exists() for p in seen_paths)
