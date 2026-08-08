"""Unit tests for :mod:`kproj.services.ibom_generator`.

Validates the contract per ADR 0008 + ``docs/DESIGN.md`` §
*IbomGenerator*:

- The argv is exactly:
  ``<python> <ibom_script> --no-browser --no-compression
  --dest-dir <staging> --name-format <P>-<R>.ibom
  --extra-data-file <pcb> --dnp-field kicad_dnp
  --layer-view <F|B|FB>
  --extra-fields MPN,Manufacturer --include-tracks <pcb>``.
- ``--layer-view`` is chosen from footprint placement sides on the PCB:
  front-only boards open on ``F``, back-only on ``B``, mixed on ``FB``
  so the default BOM table does not hide one side of the board.
- The Python interpreter is the injected KiCad-bundled Python
  (``python_exe``), NOT :data:`sys.executable` (ADR 0008 amendment /
  kproj#10: the iBOM script needs ``pcbnew``).
- The produced ``<dest-dir>/<name_format>.html`` file is moved into
  the caller's *output_file*.
- ChangeJournal injection is optional via method parameter.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ElementTree
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from kproj.common import subprocess_runner
from kproj.common.datasheet_library import build_datasheet_link
from kproj.common.install_info import InstallInfo
from kproj.model.datasheet_row import DatasheetRow
from kproj.model.export_result import ExportResult
from kproj.services import ibom_generator as ibom_generator_module
from kproj.services.change_journal import ChangeJournal
from kproj.services.ibom_generator import (
    IbomGenerator,
    choose_ibom_layer_view,
    detect_pcb_footprint_sides,
)


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


@pytest.fixture
def kicad_python(tmp_path: Path) -> Path:
    """A synthetic KiCad-bundled Python interpreter path (subprocess is mocked)."""
    python_exe = tmp_path / "kicad-python3"
    python_exe.write_text("# stub interpreter")
    return python_exe


def test_generate_emits_canonical_argv(
    ibom_script: Path, kicad_python: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The argv matches the ADR 0008 contract token-for-token."""
    fake_run, captured = _make_fake_ibom_run()
    monkeypatch.setattr(ibom_generator_module, "subprocess_run", fake_run)

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "demo-1.0.ibom.html"

    result = IbomGenerator(ibom_script=ibom_script, python_exe=kicad_python).generate(
        pcb_path=pcb,
        output_file=output,
        name_format="demo-1.0.ibom",
    )

    assert isinstance(result, ExportResult)
    assert result.path == output
    assert output.exists()
    argv = captured[0]
    # Interpreter is KiCad's bundled Python (ADR 0008 amendment / kproj#10),
    # NOT sys.executable which lacks pcbnew.
    assert argv[0] == str(kicad_python)
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
    assert "--layer-view" in argv
    layer_view_idx = argv.index("--layer-view") + 1
    # Stub PCB has no footprints → front default (same as front-only boards).
    assert argv[layer_view_idx] == "F"
    assert "--extra-fields" in argv
    fields_idx = argv.index("--extra-fields") + 1
    assert argv[fields_idx] == "MPN,Manufacturer"
    assert "--include-tracks" in argv
    # Positional <pcb> is the final argument.
    assert argv[-1] == str(pcb)


def test_generate_moves_html_from_staging_dir_to_output_file(
    ibom_script: Path, kicad_python: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The produced ``<dest-dir>/<name-format>.html`` is moved into ``output_file``."""
    fake_run, _ = _make_fake_ibom_run()
    monkeypatch.setattr(ibom_generator_module, "subprocess_run", fake_run)

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "out" / "demo-1.0.ibom.html"

    IbomGenerator(ibom_script=ibom_script, python_exe=kicad_python).generate(
        pcb_path=pcb,
        output_file=output,
        name_format="demo-1.0.ibom",
    )
    assert output.exists()
    assert "iBOM" in output.read_text()


def test_generate_raises_when_html_missing(
    ibom_script: Path, kicad_python: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When iBOM exits 0 but produces no HTML, the service raises a clear error."""
    fake_run, _ = _make_fake_ibom_run(write_html=False)
    monkeypatch.setattr(ibom_generator_module, "subprocess_run", fake_run)

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "out.html"

    with pytest.raises(FileNotFoundError):
        IbomGenerator(ibom_script=ibom_script, python_exe=kicad_python).generate(
            pcb_path=pcb,
            output_file=output,
            name_format="demo-1.0.ibom",
        )


def test_generate_registers_with_change_journal(
    ibom_script: Path, kicad_python: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
        IbomGenerator(ibom_script=ibom_script, python_exe=kicad_python).generate(
            pcb_path=pcb,
            output_file=output,
            name_format="demo.ibom",
            journal=journal,
        )
        assert output in set(journal.all_paths())


def test_generate_sets_interactive_html_bom_no_display_env(
    ibom_script: Path, kicad_python: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    IbomGenerator(ibom_script=ibom_script, python_exe=kicad_python).generate(
        pcb_path=pcb,
        output_file=output,
        name_format="demo.ibom",
    )
    assert captured_env.get("INTERACTIVE_HTML_BOM_NO_DISPLAY") == "1"


def test_generate_projects_inventory_rows_to_xml_extra_data(
    ibom_script: Path, kicad_python: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inventory rows are projected to a temporary XML file passed to iBOM."""
    captured: dict[str, object] = {}

    def _capture_run(command: Iterable[Any], **kwargs: Any) -> subprocess_runner.SubprocessResult:
        argv = [str(a) for a in command]
        captured["argv"] = argv
        extra_data_idx = argv.index("--extra-data-file") + 1
        extra_data_file = Path(argv[extra_data_idx])
        captured["extra_data_file"] = extra_data_file
        captured["extra_data_xml"] = extra_data_file.read_text(encoding="utf-8")
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
    rows = (
        DatasheetRow(
            reference="Q8",
            datasheet="https://example.com/bss138.pdf",
            datasheet_name="MOSFET-BSS138",
            manufacturer="ON & Semi",
            mfgpn="BSS138 <ALT>",
            mpn="",
            fabricator_part_number="LCSC999",
            description="N-channel MOSFET",
            dnp="DNP",
        ),
    )
    IbomGenerator(
        ibom_script=ibom_script,
        python_exe=kicad_python,
        extra_fields=(
            "Details",
            "Description",
        ),
    ).generate(
        pcb_path=pcb,
        output_file=output,
        name_format="demo.ibom",
        extra_data_rows=rows,
    )

    argv = captured["argv"]
    assert isinstance(argv, list)
    assert "--extra-fields" in argv
    fields_idx = argv.index("--extra-fields") + 1
    assert argv[fields_idx] == "Details,Description"
    extra_data_file = captured["extra_data_file"]
    assert isinstance(extra_data_file, Path)
    assert extra_data_file != pcb
    extra_data_xml = captured["extra_data_xml"]
    assert isinstance(extra_data_xml, str)
    expected_datasheet_url = build_datasheet_link("MOSFET-BSS138").view_url
    expected_datasheet_anchor = (
        f'<a href="{expected_datasheet_url}" target="_blank" rel="noopener noreferrer">'
        "Datasheet"
        "</a>"
    )
    xml_root = ElementTree.fromstring(extra_data_xml)
    comp = xml_root.find("./components/comp[@ref='Q8']")
    assert comp is not None
    assert '<comp ref="Q8">' in extra_data_xml
    assert comp.findtext("datasheet") == expected_datasheet_anchor
    assert (
        comp.findtext("./field[@name='Details']")
        == "ON &amp; Semi<br>BSS138 &lt;ALT&gt;<br>" + expected_datasheet_anchor
    )
    assert comp.findtext("./field[@name='Description']") == "N-channel MOSFET"
    assert "https://example.com/bss138.pdf" not in extra_data_xml
    assert '<property name="dnp" />' in extra_data_xml


def test_generate_omits_extra_fields_flag_when_configured_empty(
    ibom_script: Path, kicad_python: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty extra-field config omits ``--extra-fields`` from the argv."""
    fake_run, captured = _make_fake_ibom_run()
    monkeypatch.setattr(ibom_generator_module, "subprocess_run", fake_run)

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "demo.ibom.html"
    IbomGenerator(
        ibom_script=ibom_script,
        python_exe=kicad_python,
        extra_fields=(),
    ).generate(
        pcb_path=pcb,
        output_file=output,
        name_format="demo.ibom",
    )
    argv = captured[0]
    assert "--extra-fields" not in argv


def test_generate_does_not_write_ibom_user_files(
    ibom_script: Path, kicad_python: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``generate()`` no longer writes ``web/user.css``/``user.js`` itself.

    That responsibility moved to the module-level, publicly callable
    :func:`write_ibom_user_files`, invoked directly by
    ``PublishWorkflow.run`` once per publish (see
    ``tests/unit/application/test_publish_workflow.py``), so it can
    carry the per-publish install-type/watermark provenance without
    widening the injected artifact-generator callable's signature.
    """
    fake_run, _ = _make_fake_ibom_run()
    monkeypatch.setattr(ibom_generator_module, "subprocess_run", fake_run)

    pcb = tmp_path / "demo.kicad_pcb"
    pcb.write_text("(kicad_pcb)")
    output = tmp_path / "demo.ibom.html"

    IbomGenerator(ibom_script=ibom_script, python_exe=kicad_python).generate(
        pcb_path=pcb,
        output_file=output,
        name_format="demo.ibom",
    )

    assert not (ibom_script.parent / "web").exists()


def test_write_ibom_user_files_content(
    ibom_script: Path,
) -> None:
    """``write_ibom_user_files`` writes provenance-stamped user.css/user.js."""
    install_info = InstallInfo(install_type="editable", version="0.10.5")

    ibom_generator_module.write_ibom_user_files(
        ibom_script,
        install_info=install_info,
        watermark="my-test-tag",
    )

    web_dir = ibom_script.parent / "web"
    user_css = (web_dir / "user.css").read_text(encoding="utf-8")
    user_js = (web_dir / "user.js").read_text(encoding="utf-8")

    expected_provenance = "kproj 0.10.5 (editable) [my-test-tag]"

    assert "Managed by kproj" in user_css
    assert expected_provenance in user_css
    assert "table-layout: auto;" in user_css
    assert '.bom th[col_name="Details"] {' in user_css
    # th.numCol (hosts the vismenu dropdown) must stay unconstrained --
    # squeezing its width previously corrupted the dropdown's rendering.
    assert "th.numCol {" not in user_css
    assert "max-width: 4.4ch" not in user_css
    assert "#vismenu-content" in user_css

    assert "Managed by kproj" in user_js
    assert expected_provenance in user_js
    assert json.dumps(expected_provenance) in user_js
    assert 'storagePrefix + "hiddenColumns"' in user_js
    assert '["checkboxes", "Footprint"]' in user_js
    assert "referencesCheckbox" in user_js
    assert 'th[col_name="References"]' in user_js
    # Relabeling must survive re-renders (drag-reorder, mode changes),
    # so it rides the documented event hook, not a one-time load listener.
    assert "EventHandler.registerCallback(IBOM_EVENT_TYPES.BOM_BODY_CHANGE_EVENT" in user_js
    assert 'window.addEventListener("load"' not in user_js
    assert "vismenu-content" in user_js
    # The same provenance is also surfaced as a hover tooltip inside
    # iBOM's own UI (the standalone .ibom.html is a downloadable
    # artifact in its own right; see kproj.common.install_info).
    assert ".shameless-plug" in user_js
    assert "creditLine.title" in user_js


def test_write_ibom_user_files_omits_bracket_when_watermark_empty(
    ibom_script: Path,
) -> None:
    """A default (empty) watermark omits the trailing bracketed tag."""
    install_info = InstallInfo(install_type="release", version="0.10.5")

    ibom_generator_module.write_ibom_user_files(ibom_script, install_info=install_info)

    web_dir = ibom_script.parent / "web"
    user_css = (web_dir / "user.css").read_text(encoding="utf-8")
    assert "kproj 0.10.5 (release)" in user_css
    assert "[" not in user_css.split("kproj 0.10.5 (release)")[1].split("\n")[0]


def test_write_ibom_user_files_overwrites_idempotently(
    ibom_script: Path,
) -> None:
    """Repeated calls rewrite (not append to) user.css/user.js."""
    install_info = InstallInfo(install_type="release", version="0.10.5")

    ibom_generator_module.write_ibom_user_files(ibom_script, install_info=install_info)
    ibom_generator_module.write_ibom_user_files(ibom_script, install_info=install_info)

    web_dir = ibom_script.parent / "web"
    expected_css = ibom_generator_module._build_user_css(
        ibom_generator_module.format_provenance(install_info)
    )
    expected_js = ibom_generator_module._build_user_js(
        ibom_generator_module.format_provenance(install_info)
    )
    assert (web_dir / "user.css").read_text(encoding="utf-8") == expected_css
    assert (web_dir / "user.js").read_text(encoding="utf-8") == expected_js


def test_generate_propagates_subprocess_failure(
    ibom_script: Path, kicad_python: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
        IbomGenerator(ibom_script=ibom_script, python_exe=kicad_python).generate(
            pcb_path=pcb,
            output_file=output,
            name_format="demo.ibom",
        )
    assert not output.exists()



def _minimal_footprint(*, reference: str, layer: str, attr: str = "smd") -> str:
    """Return a minimal KiCad 8+ footprint s-expression for layer-side tests."""
    suffix = reference.encode("ascii", "ignore").hex()[:2].rjust(2, "0")
    return (
        f'\t(footprint "Lib:FP_{reference}"\n'
        f'\t\t(layer "{layer}")\n'
        f'\t\t(uuid "00000000-0000-0000-0000-0000000000{suffix}")\n'
        f"\t\t(at 0 0)\n"
        f"\t\t(attr {attr})\n"
        f'\t\t(property "Reference" "{reference}"\n'
        f"\t\t\t(at 0 -1.5 0)\n"
        f'\t\t\t(layer "F.Fab")\n'
        f'\t\t\t(uuid "00000000-0000-0000-0000-0000000001{suffix}")\n'
        f"\t\t)\n"
        f"\t)\n"
    )


def _write_stub_pcb(path: Path, footprints: str) -> Path:
    """Write a minimal ``.kicad_pcb`` containing *footprints*."""
    path.write_text(
        "(kicad_pcb\n"
        '\t(version 20240108)\n'
        '\t(generator "kproj-test")\n'
        f"{footprints}"
        ")\n",
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    ("footprints", "expected_front", "expected_back"),
    [
        ("", False, False),
        (_minimal_footprint(reference="R1", layer="F.Cu"), True, False),
        (_minimal_footprint(reference="R1", layer="B.Cu"), False, True),
        (
            _minimal_footprint(reference="R1", layer="F.Cu")
            + _minimal_footprint(reference="J1", layer="B.Cu"),
            True,
            True,
        ),
        # Nested pad/graphical layers must not be mistaken for placement side.
        (
            '\t(footprint "Lib:FP"\n'
            '\t\t(layer "F.Cu")\n'
            '\t\t(uuid "00000000-0000-0000-0000-000000000099")\n'
            "\t\t(at 0 0)\n"
            "\t\t(attr smd)\n"
            '\t\t(property "Reference" "R9"\n'
            "\t\t\t(at 0 -1.5 0)\n"
            '\t\t\t(layer "B.Fab")\n'
            '\t\t\t(uuid "00000000-0000-0000-0000-000000000199")\n'
            "\t\t)\n"
            '\t\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "B.Cu")\n'
            '\t\t\t(uuid "00000000-0000-0000-0000-000000000299")\n'
            "\t\t)\n"
            "\t)\n",
            True,
            False,
        ),
        # board_only / exclude_from_bom footprints are ignored for view choice.
        (
            _minimal_footprint(reference="H1", layer="B.Cu", attr="board_only exclude_from_bom")
            + _minimal_footprint(reference="R1", layer="F.Cu"),
            True,
            False,
        ),
    ],
)
def test_detect_pcb_footprint_sides(
    tmp_path: Path,
    footprints: str,
    expected_front: bool,
    expected_back: bool,
) -> None:
    """Footprint placement sides are detected from the footprint's own layer."""
    pcb = _write_stub_pcb(tmp_path / "board.kicad_pcb", footprints)
    has_front, has_back = detect_pcb_footprint_sides(pcb)
    assert has_front is expected_front
    assert has_back is expected_back


@pytest.mark.parametrize(
    ("has_front", "has_back", "expected"),
    [
        (True, False, "F"),
        (False, True, "B"),
        (True, True, "FB"),
        (False, False, "F"),
    ],
)
def test_choose_ibom_layer_view(has_front: bool, has_back: bool, expected: str) -> None:
    """Default layer view prefers the populated side(s) without hiding parts."""
    assert choose_ibom_layer_view(has_front=has_front, has_back=has_back) == expected


@pytest.mark.parametrize(
    ("footprints", "expected_layer_view"),
    [
        (_minimal_footprint(reference="R1", layer="F.Cu"), "F"),
        (_minimal_footprint(reference="R1", layer="B.Cu"), "B"),
        (
            _minimal_footprint(reference="R1", layer="F.Cu")
            + _minimal_footprint(reference="J1", layer="B.Cu"),
            "FB",
        ),
    ],
)
def test_generate_selects_layer_view_from_pcb_sides(
    ibom_script: Path,
    kicad_python: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    footprints: str,
    expected_layer_view: str,
) -> None:
    """``generate`` passes a side-aware ``--layer-view`` so mixed boards open on FB."""
    fake_run, captured = _make_fake_ibom_run()
    monkeypatch.setattr(ibom_generator_module, "subprocess_run", fake_run)

    pcb = _write_stub_pcb(tmp_path / "demo.kicad_pcb", footprints)
    output = tmp_path / "demo.ibom.html"
    IbomGenerator(ibom_script=ibom_script, python_exe=kicad_python).generate(
        pcb_path=pcb,
        output_file=output,
        name_format="demo.ibom",
    )
    argv = captured[0]
    layer_view_idx = argv.index("--layer-view") + 1
    assert argv[layer_view_idx] == expected_layer_view
