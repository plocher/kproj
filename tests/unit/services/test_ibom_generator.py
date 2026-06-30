"""Unit tests for :mod:`kproj.services.ibom_generator`.

Validates the contract per ADR 0008 + ``docs/DESIGN.md`` §
*IbomGenerator*:

- The argv is exactly:
  ``<python> <ibom_script> --no-browser --no-compression
  --dest-dir <staging> --name-format <P>-<R>.ibom
  --extra-data-file <pcb> --dnp-field kicad_dnp
  --extra-fields MPN,Manufacturer --include-tracks <pcb>``.
- The Python interpreter is :data:`sys.executable` (so iBOM runs
  under the same Python as kproj per ADR 0008).
- The produced ``<dest-dir>/<name_format>.html`` file is moved into
  the caller's *output_file*.
- ChangeJournal injection is optional via method parameter.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from kproj.common import subprocess_runner
from kproj.model.export_result import ExportResult
from kproj.services import ibom_generator as ibom_generator_module
from kproj.services.change_journal import ChangeJournal
from kproj.services.ibom_generator import IbomGenerator


def _make_fake_ibom_run(
    *,
    write_html: bool = True,
) -> tuple[Any, list[list[str]]]:
    """Fake subprocess_run that writes ``<dest-dir>/<name-format>.html``."""
    captured: list[list[str]] = []

    def _fake_run(command: Iterable[Any], **kwargs: Any) -> subprocess_runner.SubprocessResult:
        argv = [str(a) for a in command]
        captured.append(argv)
        if write_html:
            dest_idx = argv.index("--dest-dir") + 1
            name_idx = argv.index("--name-format") + 1
            dest_dir = Path(argv[dest_idx])
            dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / f"{argv[name_idx]}.html").write_text("<html><body>iBOM</body></html>")
        return subprocess_runner.SubprocessResult(
            command=tuple(argv),
            returncode=0,
            stdout="",
            stderr="",
            elapsed_seconds=0.0,
        )

    return _fake_run, captured


@pytest.fixture
def ibom_script(tmp_path: Path) -> Path:
    """A synthetic iBOM script path (subprocess is mocked)."""
    script = tmp_path / "generate_interactive_bom.py"
    script.write_text("# stub")
    return script


def test_generate_emits_canonical_argv(
    ibom_script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The argv matches the ADR 0008 contract token-for-token."""
    fake_run, captured = _make_fake_ibom_run()
    monkeypatch.setattr(ibom_generator_module, "subprocess_run", fake_run)

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "demo-1.0.ibom.html"

    result = IbomGenerator(ibom_script=ibom_script).generate(
        pcb_path=pcb,
        output_file=output,
        name_format="demo-1.0.ibom",
    )

    assert isinstance(result, ExportResult)
    assert result.path == output
    assert output.exists()
    argv = captured[0]
    # Python interpreter is sys.executable per ADR 0008.
    assert argv[0] == sys.executable
    assert argv[1] == str(ibom_script)
    # All required flags present in stable, predictable order.
    assert "--no-browser" in argv
    assert "--no-compression" in argv
    assert "--dest-dir" in argv
    assert "--name-format" in argv
    name_idx = argv.index("--name-format") + 1
    assert argv[name_idx] == "demo-1.0.ibom"
    assert "--extra-data-file" in argv
    extra_data_idx = argv.index("--extra-data-file") + 1
    assert argv[extra_data_idx] == str(pcb)
    assert "--dnp-field" in argv
    dnp_idx = argv.index("--dnp-field") + 1
    assert argv[dnp_idx] == "kicad_dnp"
    assert "--extra-fields" in argv
    fields_idx = argv.index("--extra-fields") + 1
    assert argv[fields_idx] == "MPN,Manufacturer"
    assert "--include-tracks" in argv
    # Positional <pcb> is the final argument.
    assert argv[-1] == str(pcb)


def test_generate_moves_html_from_staging_dir_to_output_file(
    ibom_script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The produced ``<dest-dir>/<name-format>.html`` is moved into ``output_file``."""
    fake_run, _ = _make_fake_ibom_run()
    monkeypatch.setattr(ibom_generator_module, "subprocess_run", fake_run)

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "out" / "demo-1.0.ibom.html"

    IbomGenerator(ibom_script=ibom_script).generate(
        pcb_path=pcb,
        output_file=output,
        name_format="demo-1.0.ibom",
    )
    assert output.exists()
    assert "iBOM" in output.read_text()


def test_generate_raises_when_html_missing(
    ibom_script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When iBOM exits 0 but produces no HTML, the service raises a clear error."""
    fake_run, _ = _make_fake_ibom_run(write_html=False)
    monkeypatch.setattr(ibom_generator_module, "subprocess_run", fake_run)

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "out.html"

    with pytest.raises(FileNotFoundError):
        IbomGenerator(ibom_script=ibom_script).generate(
            pcb_path=pcb,
            output_file=output,
            name_format="demo-1.0.ibom",
        )


def test_generate_registers_with_change_journal(
    ibom_script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The final HTML path is registered via :meth:`ChangeJournal.will_create`."""
    fake_run, _ = _make_fake_ibom_run()
    monkeypatch.setattr(ibom_generator_module, "subprocess_run", fake_run)

    site_repo = tmp_path / "site"
    site_repo.mkdir()
    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = site_repo / "demo.ibom.html"

    with ChangeJournal(site_repo) as journal:
        IbomGenerator(ibom_script=ibom_script).generate(
            pcb_path=pcb,
            output_file=output,
            name_format="demo.ibom",
            journal=journal,
        )
        assert output in set(journal.all_paths())


def test_generate_sets_interactive_html_bom_no_display_env(
    ibom_script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The subprocess env must include ``INTERACTIVE_HTML_BOM_NO_DISPLAY=1``.

    The PCM-installed iBOM script imports wxPython unless this env var is
    set, and kproj runs headless (ADR 0007 + ADR 0008).  Pin the value
    here so a future refactor doesn't silently drop it and re-break the
    KiCad-10-host iBOM contract.
    """
    captured_env: dict[str, str] = {}

    def _capture_run(command: Iterable[Any], **kwargs: Any) -> subprocess_runner.SubprocessResult:
        env = kwargs.get("env") or {}
        captured_env.update(env)
        argv = [str(a) for a in command]
        dest_idx = argv.index("--dest-dir") + 1
        name_idx = argv.index("--name-format") + 1
        dest_dir = Path(argv[dest_idx])
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / f"{argv[name_idx]}.html").write_text("<html/>")
        return subprocess_runner.SubprocessResult(
            command=tuple(argv),
            returncode=0,
            stdout="",
            stderr="",
            elapsed_seconds=0.0,
        )

    monkeypatch.setattr(ibom_generator_module, "subprocess_run", _capture_run)
    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "demo.ibom.html"
    IbomGenerator(ibom_script=ibom_script).generate(
        pcb_path=pcb,
        output_file=output,
        name_format="demo.ibom",
    )
    assert captured_env.get("INTERACTIVE_HTML_BOM_NO_DISPLAY") == "1"


def test_generate_propagates_subprocess_failure(
    ibom_script: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing iBOM script surfaces SubprocessFailedError unchanged."""

    def _failing(command: Iterable[Any], **kwargs: Any) -> subprocess_runner.SubprocessResult:
        raise subprocess_runner.SubprocessFailedError(
            list(command), returncode=2, stdout="", stderr="iBOM: boom"
        )

    monkeypatch.setattr(ibom_generator_module, "subprocess_run", _failing)

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "out.html"

    with pytest.raises(subprocess_runner.SubprocessFailedError):
        IbomGenerator(ibom_script=ibom_script).generate(
            pcb_path=pcb,
            output_file=output,
            name_format="demo.ibom",
        )
    assert not output.exists()
