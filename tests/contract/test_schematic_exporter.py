"""Contract test for :class:`kproj.services.schematic_exporter.SchematicExporter`.

Validates that the SVG dir-discover-and-move pattern + the PDF
direct-file pattern both work against the local kicad-cli build, and
that ``--output``'s actual semantics (OUTPUT_DIR for SVG, OUTPUT_FILE
for PDF) match what ``docs/DESIGN.md`` § *SchematicExporter*
documents. Skipped when kicad-cli is unavailable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kproj.common.kicad_install import KicadNotFoundError, find_kicad_cli
from kproj.services.schematic_exporter import SchematicExporter


def _kicad_cli_available() -> bool:
    """Return ``True`` iff :func:`find_kicad_cli` resolves a real binary."""
    try:
        find_kicad_cli()
    except KicadNotFoundError:
        return False
    return True


_MINIMAL_SCH = Path(__file__).parent.parent / "fixtures" / "minimal" / "minimal.kicad_sch"

pytestmark = pytest.mark.contract


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_export_svg_root_only_produces_single_svg(tmp_path: Path) -> None:
    """``export_svg(root_only=True)`` produces a real SVG that starts with ``<?xml`` or ``<svg``."""
    output = tmp_path / "minimal.sch.svg"
    result = SchematicExporter(kicad_cli=find_kicad_cli()).export_svg(
        _MINIMAL_SCH, output, root_only=True
    )
    assert result.path == output
    assert output.exists()
    head = output.read_bytes()[:80].lstrip()
    assert head.startswith(b"<?xml") or head.startswith(b"<svg")


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_export_pdf_produces_pdf_file(tmp_path: Path) -> None:
    """``export_pdf()`` produces a real PDF (``%PDF-`` header)."""
    output = tmp_path / "minimal.sch.pdf"
    result = SchematicExporter(kicad_cli=find_kicad_cli()).export_pdf(_MINIMAL_SCH, output)
    assert result.path == output
    assert output.exists()
    assert output.read_bytes()[:5] == b"%PDF-"
