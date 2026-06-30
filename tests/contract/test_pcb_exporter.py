"""Contract test for :class:`kproj.services.pcb_exporter.PcbExporter`.

Runs the real local ``kicad-cli`` against ``tests/fixtures/minimal``
to validate that the PCB-render + STEP-export commands kproj emits
actually produce the expected output shapes. Skipped automatically
when ``kicad-cli`` is not installed locally (CI / non-developer
machines), per ``docs/DESIGN.md`` § *Contract tests*.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kproj.common.kicad_install import KicadNotFoundError, find_kicad_cli
from kproj.services.pcb_exporter import PcbExporter


def _kicad_cli_available() -> bool:
    """Return ``True`` iff :func:`find_kicad_cli` resolves a real binary."""
    try:
        find_kicad_cli()
    except KicadNotFoundError:
        return False
    return True


_MINIMAL_PCB = Path(__file__).parent.parent / "fixtures" / "minimal" / "minimal.kicad_pcb"

pytestmark = pytest.mark.contract


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_pcb_render_top_produces_png(tmp_path: Path) -> None:
    """``PcbExporter.export_render('top')`` produces a real PNG via kicad-cli."""
    output = tmp_path / "minimal-1.0.top.png"
    result = PcbExporter(kicad_cli=find_kicad_cli()).export_render(_MINIMAL_PCB, "top", output)
    assert result.path == output
    assert output.exists()
    # PNG magic bytes per ISO/IEC 15948.
    assert output.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_pcb_render_bottom_produces_png(tmp_path: Path) -> None:
    """``PcbExporter.export_render('bottom')`` also produces a real PNG."""
    output = tmp_path / "minimal-1.0.bottom.png"
    PcbExporter(kicad_cli=find_kicad_cli()).export_render(_MINIMAL_PCB, "bottom", output)
    assert output.exists()
    assert output.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_pcb_export_step_produces_step_file(tmp_path: Path) -> None:
    """``PcbExporter.export_step()`` produces a STEP file (ASCII ``ISO-10303-21`` header)."""
    output = tmp_path / "minimal-1.0.step"
    result = PcbExporter(kicad_cli=find_kicad_cli()).export_step(_MINIMAL_PCB, output)
    assert result.path == output
    assert output.exists()
    head = output.read_bytes()[:20]
    assert head.startswith(b"ISO-10303-21")
