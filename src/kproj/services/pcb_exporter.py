"""Stub :class:`PcbExporter` (docs/DESIGN.md § PcbExporter)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..model.export_result import ExportResult


class PcbExporter:
    """PCB → PNG / STEP exporter (stub).

    Foundation slice raises; the real subprocess invocations land in a
    subsequent issue per ``docs/DESIGN.md`` § *Release asset set*.
    """

    def __init__(self, kicad_cli: Path) -> None:
        """Construct a PCB exporter.

        Args:
            kicad_cli: Path to the discovered ``kicad-cli`` executable.
        """
        self._kicad_cli = kicad_cli

    def export_render(
        self, pcb_path: Path, side: Literal["top", "bottom"], output: Path
    ) -> ExportResult:
        """Render the PCB as a PNG.

        Raises:
            NotImplementedError: Always, in the foundation slice.
        """
        raise NotImplementedError(
            "PcbExporter.export_render is not implemented in the foundation slice."
        )

    def export_step(self, pcb_path: Path, output: Path) -> ExportResult:
        """Export the PCB as a STEP model.

        Raises:
            NotImplementedError: Always, in the foundation slice.
        """
        raise NotImplementedError(
            "PcbExporter.export_step is not implemented in the foundation slice."
        )
