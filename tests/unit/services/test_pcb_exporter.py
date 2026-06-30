"""Unit tests for :mod:`kproj.services.pcb_exporter`.

Validates the PcbExporter contract per ``docs/DESIGN.md`` § *PcbExporter*
+ ``docs/DESIGN.md`` § *Release asset set*:

- ``export_render(side)`` invokes ``<kicad_cli> pcb render --side <side>
  --output <file> <pcb>``.
- ``export_step()`` invokes ``<kicad_cli> pcb export step --output <file>
  <pcb>``.
- Writes are atomic (tempfile + os.replace) and journaled when a
  ChangeJournal is supplied.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from kproj.common import subprocess_runner
from kproj.model.export_result import ExportResult
from kproj.services import pcb_exporter as pcb_exporter_module
from kproj.services.change_journal import ChangeJournal
from kproj.services.pcb_exporter import PcbExporter


def _make_fake_run(
    *,
    side_effect_writes: list[tuple[int, str]] | None = None,
) -> tuple[Any, list[list[str]]]:
    """Return a fake subprocess_runner.run that writes to the --output path.

    Each call records its argv. By default, every call writes a 1-byte
    payload to the tempfile path that follows ``--output`` in the argv.
    """
    captured: list[list[str]] = []

    def _fake_run(command: Iterable[Any], **kwargs: Any) -> subprocess_runner.SubprocessResult:
        argv = [str(a) for a in command]
        captured.append(argv)
        # Honor --output OUTPUT_FILE contract: write a marker payload at that path.
        if "--output" in argv:
            output_idx = argv.index("--output") + 1
            output_path = Path(argv[output_idx])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"x")
        return subprocess_runner.SubprocessResult(
            command=tuple(argv),
            returncode=0,
            stdout="",
            stderr="",
            elapsed_seconds=0.01,
        )

    return _fake_run, captured


@pytest.fixture
def kicad_cli(tmp_path: Path) -> Path:
    """Return a synthetic kicad-cli path (no real binary needed; mocked)."""
    cli = tmp_path / "kicad-cli"
    cli.write_text("#!/bin/sh\n")
    cli.chmod(0o755)
    return cli


def test_export_render_top_invokes_kicad_cli_pcb_render(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``export_render(side='top')`` invokes ``<cli> pcb render --side top --output ... <pcb>``."""
    fake_run, captured = _make_fake_run()
    monkeypatch.setattr(pcb_exporter_module, "subprocess_run", fake_run)

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "out" / "demo-1.0.top.png"

    exporter = PcbExporter(kicad_cli=kicad_cli)
    result = exporter.export_render(pcb_path=pcb, side="top", output=output)

    assert isinstance(result, ExportResult)
    assert result.path == output
    assert result.skipped is False
    assert result.command is not None
    assert len(captured) == 1
    argv = captured[0]
    assert argv[0] == str(kicad_cli)
    assert argv[1:4] == ["pcb", "render", "--side"]
    assert argv[4] == "top"
    assert "--output" in argv
    assert argv[-1] == str(pcb)
    # The output file is in place after atomic os.replace.
    assert output.exists()


def test_export_render_bottom_uses_bottom_side(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``export_render(side='bottom')`` passes ``--side bottom``."""
    fake_run, captured = _make_fake_run()
    monkeypatch.setattr(pcb_exporter_module, "subprocess_run", fake_run)

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "demo-1.0.bottom.png"

    PcbExporter(kicad_cli=kicad_cli).export_render(pcb, "bottom", output)

    assert captured[0][4] == "bottom"


def test_export_render_rejects_invalid_side(kicad_cli: Path, tmp_path: Path) -> None:
    """An invalid side string is rejected at intake (validation at boundary)."""
    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "out.png"
    with pytest.raises(ValueError, match="side"):
        PcbExporter(kicad_cli=kicad_cli).export_render(pcb, "left", output)  # type: ignore[arg-type]


def test_export_render_writes_atomically_through_tempfile(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The kicad-cli output path is a sibling tempfile, then atomically replaced into output."""
    captured_argv: list[list[str]] = []

    def _fake_run(command: Iterable[Any], **kwargs: Any) -> subprocess_runner.SubprocessResult:
        argv = [str(a) for a in command]
        captured_argv.append(argv)
        output_idx = argv.index("--output") + 1
        tmp_output = Path(argv[output_idx])
        # The tempfile path must NOT equal the final output (it's a staging file).
        tmp_output.parent.mkdir(parents=True, exist_ok=True)
        tmp_output.write_bytes(b"png")
        return subprocess_runner.SubprocessResult(
            command=tuple(argv),
            returncode=0,
            stdout="",
            stderr="",
            elapsed_seconds=0.0,
        )

    monkeypatch.setattr(pcb_exporter_module, "subprocess_run", _fake_run)

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "demo-1.0.top.png"

    PcbExporter(kicad_cli=kicad_cli).export_render(pcb, "top", output)

    argv = captured_argv[0]
    output_idx = argv.index("--output") + 1
    cli_output = Path(argv[output_idx])
    # kicad-cli was directed at a tempfile, not the final output.
    assert cli_output != output
    # The final output exists with the rendered bytes.
    assert output.read_bytes() == b"png"


def test_export_render_registers_with_change_journal(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When a ChangeJournal is supplied, ``will_create`` is called for the output."""
    fake_run, _ = _make_fake_run()
    monkeypatch.setattr(pcb_exporter_module, "subprocess_run", fake_run)

    site_repo = tmp_path / "site"
    site_repo.mkdir()
    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = site_repo / "versions" / "demo" / "1.0" / "demo-1.0.top.png"

    with ChangeJournal(site_repo) as journal:
        PcbExporter(kicad_cli=kicad_cli).export_render(pcb, "top", output, journal=journal)
        assert output in set(journal.all_paths())


def test_export_render_rolls_back_when_journal_raises(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The journaled artifact is removed if a downstream step inside the ``with`` raises."""
    fake_run, _ = _make_fake_run()
    monkeypatch.setattr(pcb_exporter_module, "subprocess_run", fake_run)

    site_repo = tmp_path / "site"
    site_repo.mkdir()
    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = site_repo / "demo-1.0.top.png"

    class _Boom(RuntimeError):
        pass

    with pytest.raises(_Boom), ChangeJournal(site_repo) as journal:
        PcbExporter(kicad_cli=kicad_cli).export_render(pcb, "top", output, journal=journal)
        assert output.exists()
        raise _Boom

    assert not output.exists()


def test_export_step_invokes_kicad_cli_pcb_export_step(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``export_step()`` invokes ``<cli> pcb export step --output <file> <pcb>``."""
    fake_run, captured = _make_fake_run()
    monkeypatch.setattr(pcb_exporter_module, "subprocess_run", fake_run)

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "demo-1.0.step"

    result = PcbExporter(kicad_cli=kicad_cli).export_step(pcb, output)

    assert isinstance(result, ExportResult)
    assert result.path == output
    argv = captured[0]
    assert argv[0] == str(kicad_cli)
    assert argv[1:4] == ["pcb", "export", "step"]
    assert "--output" in argv
    assert argv[-1] == str(pcb)
    assert output.exists()


def test_export_step_raises_on_subprocess_failure(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A SubprocessFailedError from the runner propagates (workflow handles rollback)."""

    def _failing_run(command: Iterable[Any], **kwargs: Any) -> subprocess_runner.SubprocessResult:
        raise subprocess_runner.SubprocessFailedError(
            list(command), returncode=2, stdout="", stderr="kicad-cli: boom"
        )

    monkeypatch.setattr(pcb_exporter_module, "subprocess_run", _failing_run)

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "demo.step"

    with pytest.raises(subprocess_runner.SubprocessFailedError):
        PcbExporter(kicad_cli=kicad_cli).export_step(pcb, output)
    # The final artifact must NOT exist after a failure.
    assert not output.exists()
