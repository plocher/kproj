"""Stub :class:`SchematicExporter` (docs/DESIGN.md § SchematicExporter)."""

from __future__ import annotations

from pathlib import Path

from ..model.export_result import ExportResult


class SchematicExporter:
    """Schematic → SVG / PDF exporter (stub)."""

    def __init__(self, kicad_cli: Path) -> None:
        """Construct a schematic exporter.

        Args:
            kicad_cli: Path to the discovered ``kicad-cli`` executable.
        """
        self._kicad_cli = kicad_cli

    def export_svg(self, sch_path: Path, output_file: Path, root_only: bool = True) -> ExportResult:
        """Export the schematic root sheet as SVG.

        Raises:
            NotImplementedError: Always, in the foundation slice.
        """
        raise NotImplementedError(
            "SchematicExporter.export_svg is not implemented in the foundation slice."
        )

    def export_pdf(
        self, sch_path: Path, output_file: Path, all_sheets: bool = True
    ) -> ExportResult:
        """Export the schematic as a multi-sheet PDF.

        Raises:
            NotImplementedError: Always, in the foundation slice.
        """
        raise NotImplementedError(
            "SchematicExporter.export_pdf is not implemented in the foundation slice."
        )
