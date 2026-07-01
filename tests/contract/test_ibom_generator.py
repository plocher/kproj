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

from kproj.common.kicad_install import (
    KicadNotFoundError,
    find_ibom_script,
    find_kicad_python,
)
from kproj.services.ibom_generator import IbomGenerator


def _ibom_runnable() -> bool:
    """Return ``True`` iff both the iBOM script and KiCad's Python resolve.

    kproj#10: the iBOM script needs KiCad's bundled Python (the one that
    can ``import pcbnew``) - never kproj's own venv interpreter.  This
    gate probes the *real* runtime path kproj uses in production
    (:func:`find_ibom_script` + :func:`find_kicad_python`) rather than
    whether ``pcbnew`` happens to import in the test interpreter (it
    never does under the uv venv).  When both resolve, the contract
    test runs iBOM end-to-end exactly as the workflow would.
    """
    try:
        find_ibom_script()
        find_kicad_python()
    except KicadNotFoundError:
        return False
    return True


_MINIMAL_PCB = Path(__file__).parent.parent / "fixtures" / "minimal" / "minimal.kicad_pcb"

pytestmark = pytest.mark.contract


@pytest.mark.skipif(
    not _ibom_runnable(),
    reason="iBOM script or KiCad-bundled Python not locatable locally (kproj#10)",
)
def test_ibom_generate_produces_html_file(tmp_path: Path) -> None:
    """``IbomGenerator.generate()`` produces a real HTML file from a minimal PCB.

    Exercises the production interpreter path: iBOM runs under KiCad's
    bundled Python (:func:`find_kicad_python`), which is the fix for
    kproj#10.
    """
    output = tmp_path / "minimal-1.0.ibom.html"
    result = IbomGenerator(
        ibom_script=find_ibom_script(),
        python_exe=find_kicad_python(),
    ).generate(
        pcb_path=_MINIMAL_PCB,
        output_file=output,
        name_format="minimal-1.0.ibom",
    )
    assert result.path == output
    assert output.exists()
    # iBOM HTML carries an unmistakable token in the head.
    text = output.read_text(errors="ignore")
    assert "InteractiveHtmlBom" in text or "<title>" in text.lower()
