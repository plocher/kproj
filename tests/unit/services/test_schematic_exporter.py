"""Unit tests for :mod:`kproj.services.schematic_exporter`.

Validates the contract per ``docs/DESIGN.md`` § *SchematicExporter*:

- ``export_svg(root_only=True)`` invokes ``<kicad_cli> sch export svg
  --output <tempdir> --pages 1 <sch>`` (``--output`` is OUTPUT_DIR
  per the local kicad-cli help), then discovers the single produced
  SVG and atomically moves it into the final ``output_file``.
- ``export_pdf(all_sheets=True)`` invokes ``<kicad_cli> sch export pdf
  --output <tempfile.pdf> <sch>`` (``--output`` is OUTPUT_FILE here)
  and atomically replaces into the final ``output_file``.
- ChangeJournal injection is optional via method parameter.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from kproj.common import subprocess_runner
from kproj.model.export_result import ExportResult
from kproj.services import schematic_exporter as schematic_exporter_module
from kproj.services.change_journal import ChangeJournal
from kproj.services.schematic_exporter import (
    SchematicExporter,
    SchematicExportError,
)


def _make_fake_svg_run(
    *,
    produced_svgs: tuple[str, ...] = ("root.svg",),
) -> tuple[Any, list[list[str]]]:
    """Fake subprocess_run that writes *produced_svgs* into the --output dir."""
    captured: list[list[str]] = []

    def _fake_run(command: Iterable[Any], **kwargs: Any) -> subprocess_runner.SubprocessResult:
        argv = [str(a) for a in command]
        captured.append(argv)
        output_idx = argv.index("--output") + 1
        out_dir = Path(argv[output_idx])
        out_dir.mkdir(parents=True, exist_ok=True)
        for svg_name in produced_svgs:
            (out_dir / svg_name).write_bytes(b"<svg/>")
        return subprocess_runner.SubprocessResult(
            command=tuple(argv),
            returncode=0,
            stdout="",
            stderr="",
            elapsed_seconds=0.0,
        )

    return _fake_run, captured


def _make_fake_pdf_run() -> tuple[Any, list[list[str]]]:
    """Fake subprocess_run that writes a PDF marker to the --output path (a file)."""
    captured: list[list[str]] = []

    def _fake_run(command: Iterable[Any], **kwargs: Any) -> subprocess_runner.SubprocessResult:
        argv = [str(a) for a in command]
        captured.append(argv)
        output_idx = argv.index("--output") + 1
        out_path = Path(argv[output_idx])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"%PDF-1.4\n")
        return subprocess_runner.SubprocessResult(
            command=tuple(argv),
            returncode=0,
            stdout="",
            stderr="",
            elapsed_seconds=0.0,
        )

    return _fake_run, captured


@pytest.fixture
def kicad_cli(tmp_path: Path) -> Path:
    """A synthetic kicad-cli path (subprocess is mocked)."""
    cli = tmp_path / "kicad-cli"
    cli.write_text("#!/bin/sh\n")
    cli.chmod(0o755)
    return cli


# ----- export_svg -----


def test_export_svg_invokes_kicad_cli_with_output_dir_and_pages_1(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SVG export passes ``--output <dir>`` (not a file) and ``--pages 1`` for root only."""
    fake_run, captured = _make_fake_svg_run()
    monkeypatch.setattr(schematic_exporter_module, "subprocess_run", fake_run)

    sch = tmp_path / "demo.kicad_sch"
    sch.write_text("(kicad_sch)")
    output = tmp_path / "demo-1.0.sch.svg"

    result = SchematicExporter(kicad_cli=kicad_cli).export_svg(sch, output)

    assert isinstance(result, ExportResult)
    assert result.path == output
    assert output.exists()
    argv = captured[0]
    assert argv[0] == str(kicad_cli)
    assert argv[1:4] == ["sch", "export", "svg"]
    assert "--output" in argv
    output_idx = argv.index("--output") + 1
    tempdir = Path(argv[output_idx])
    # The --output value is a DIRECTORY (not a file); kicad-cli writes one svg per sheet here.
    # It must NOT equal the final output file path.
    assert tempdir != output
    assert "--pages" in argv
    pages_idx = argv.index("--pages") + 1
    assert argv[pages_idx] == "1"
    assert argv[-1] == str(sch)


def test_export_svg_moves_discovered_root_sheet_to_output(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single SVG kicad-cli emits in the temp dir is atomically moved into ``output``."""
    fake_run, _ = _make_fake_svg_run(produced_svgs=("demo.svg",))
    monkeypatch.setattr(schematic_exporter_module, "subprocess_run", fake_run)

    sch = tmp_path / "demo.kicad_sch"
    sch.write_text("(kicad_sch)")
    output = tmp_path / "out" / "demo-1.0.sch.svg"

    SchematicExporter(kicad_cli=kicad_cli).export_svg(sch, output)

    assert output.read_bytes() == b"<svg/>"


def test_export_svg_raises_when_kicad_cli_emits_zero_svgs(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero SVGs produced is a SchematicExportError (workflow converts to Finding+rollback)."""
    fake_run, _ = _make_fake_svg_run(produced_svgs=())
    monkeypatch.setattr(schematic_exporter_module, "subprocess_run", fake_run)

    sch = tmp_path / "demo.kicad_sch"
    sch.write_text("(kicad_sch)")
    output = tmp_path / "out.svg"

    with pytest.raises(SchematicExportError, match="no SVG"):
        SchematicExporter(kicad_cli=kicad_cli).export_svg(sch, output)


def test_export_svg_raises_when_kicad_cli_emits_multiple_svgs_root_only(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multiple SVGs from a ``root_only=True`` run is an unexpected shape: error."""
    fake_run, _ = _make_fake_svg_run(produced_svgs=("a.svg", "b.svg"))
    monkeypatch.setattr(schematic_exporter_module, "subprocess_run", fake_run)

    sch = tmp_path / "demo.kicad_sch"
    sch.write_text("(kicad_sch)")
    output = tmp_path / "out.svg"

    with pytest.raises(SchematicExportError, match="multiple SVG"):
        SchematicExporter(kicad_cli=kicad_cli).export_svg(sch, output, root_only=True)


def test_export_svg_root_only_false_omits_pages_flag(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``root_only=False`` would emit all sheets; ``--pages`` is omitted."""
    fake_run, captured = _make_fake_svg_run(produced_svgs=("root.svg",))
    monkeypatch.setattr(schematic_exporter_module, "subprocess_run", fake_run)

    sch = tmp_path / "demo.kicad_sch"
    sch.write_text("(kicad_sch)")
    output = tmp_path / "out.svg"

    SchematicExporter(kicad_cli=kicad_cli).export_svg(sch, output, root_only=False)
    assert "--pages" not in captured[0]


def test_export_svg_registers_with_change_journal(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The final SVG path is registered via :meth:`ChangeJournal.will_create`."""
    fake_run, _ = _make_fake_svg_run()
    monkeypatch.setattr(schematic_exporter_module, "subprocess_run", fake_run)

    site_repo = tmp_path / "site"
    site_repo.mkdir()
    sch = tmp_path / "demo.kicad_sch"
    sch.write_text("(kicad_sch)")
    output = site_repo / "demo.sch.svg"

    with ChangeJournal(site_repo) as journal:
        SchematicExporter(kicad_cli=kicad_cli).export_svg(sch, output, journal=journal)
        assert output in set(journal.all_paths())


# ----- export_pdf -----


def test_export_pdf_invokes_kicad_cli_with_output_file(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PDF export passes ``--output <file.pdf>`` (file, not dir) per local kicad-cli."""
    fake_run, captured = _make_fake_pdf_run()
    monkeypatch.setattr(schematic_exporter_module, "subprocess_run", fake_run)

    sch = tmp_path / "demo.kicad_sch"
    sch.write_text("(kicad_sch)")
    output = tmp_path / "demo-1.0.sch.pdf"

    result = SchematicExporter(kicad_cli=kicad_cli).export_pdf(sch, output)

    assert isinstance(result, ExportResult)
    assert result.path == output
    assert output.exists()
    argv = captured[0]
    assert argv[0] == str(kicad_cli)
    assert argv[1:4] == ["sch", "export", "pdf"]
    assert "--output" in argv
    output_idx = argv.index("--output") + 1
    tempfile_path = Path(argv[output_idx])
    # PDF --output is a file path; tempfile must end with .pdf so KiCad preserves the format.
    assert tempfile_path.suffix == ".pdf"
    assert tempfile_path != output
    assert argv[-1] == str(sch)


def test_export_pdf_atomically_replaces_into_output(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The PDF bytes end up at the final output via atomic replace."""
    fake_run, _ = _make_fake_pdf_run()
    monkeypatch.setattr(schematic_exporter_module, "subprocess_run", fake_run)

    sch = tmp_path / "demo.kicad_sch"
    sch.write_text("(kicad_sch)")
    output = tmp_path / "out" / "demo-1.0.sch.pdf"

    SchematicExporter(kicad_cli=kicad_cli).export_pdf(sch, output)
    assert output.read_bytes().startswith(b"%PDF-")


def test_export_pdf_registers_with_change_journal(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The final PDF path is registered via :meth:`ChangeJournal.will_create`."""
    fake_run, _ = _make_fake_pdf_run()
    monkeypatch.setattr(schematic_exporter_module, "subprocess_run", fake_run)

    site_repo = tmp_path / "site"
    site_repo.mkdir()
    sch = tmp_path / "demo.kicad_sch"
    sch.write_text("(kicad_sch)")
    output = site_repo / "demo.sch.pdf"

    with ChangeJournal(site_repo) as journal:
        SchematicExporter(kicad_cli=kicad_cli).export_pdf(sch, output, journal=journal)
        assert output in set(journal.all_paths())


def test_export_pdf_propagates_subprocess_failure(
    kicad_cli: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing kicad-cli surfaces SubprocessFailedError unchanged."""

    def _failing(command: Iterable[Any], **kwargs: Any) -> subprocess_runner.SubprocessResult:
        raise subprocess_runner.SubprocessFailedError(
            list(command), returncode=2, stdout="", stderr="boom"
        )

    monkeypatch.setattr(schematic_exporter_module, "subprocess_run", _failing)

    sch = tmp_path / "demo.kicad_sch"
    sch.write_text("(kicad_sch)")
    output = tmp_path / "out.pdf"

    with pytest.raises(subprocess_runner.SubprocessFailedError):
        SchematicExporter(kicad_cli=kicad_cli).export_pdf(sch, output)
    assert not output.exists()
