"""Contract test for :class:`kproj.services.ibom_generator.IbomGenerator`.

Runs the real PCM-installed ``generate_interactive_bom.py`` script
against ``tests/fixtures/minimal/minimal.kicad_pcb`` and asserts the
produced HTML exists and looks like an iBOM page. Skipped when the
iBOM script cannot be discovered (developers without the InteractiveHtmlBom
PCM plugin installed).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kproj.common.kicad_install import KicadNotFoundError, find_ibom_script
from kproj.services.ibom_generator import IbomGenerator


def _ibom_available() -> bool:
    """Return ``True`` iff the iBOM script can be located locally."""
    try:
        find_ibom_script()
    except KicadNotFoundError:
        return False
    return True


_MINIMAL_PCB = Path(__file__).parent.parent / "fixtures" / "minimal" / "minimal.kicad_pcb"

pytestmark = pytest.mark.contract


@pytest.mark.skipif(not _ibom_available(), reason="iBOM plugin not installed locally")
def test_ibom_generate_produces_html_file(tmp_path: Path) -> None:
    """``IbomGenerator.generate()`` produces a real HTML file from a minimal PCB."""
    output = tmp_path / "minimal-1.0.ibom.html"
    result = IbomGenerator(ibom_script=find_ibom_script()).generate(
        pcb_path=_MINIMAL_PCB,
        output_file=output,
        name_format="minimal-1.0.ibom",
    )
    assert result.path == output
    assert output.exists()
    # iBOM HTML carries an unmistakable token in the head.
    text = output.read_text(errors="ignore")
    assert "InteractiveHtmlBom" in text or "<title>" in text.lower()
