"""Stub :class:`IbomGenerator` (docs/DESIGN.md § IbomGenerator, ADR 0008)."""

from __future__ import annotations

from pathlib import Path

from ..model.export_result import ExportResult


class IbomGenerator:
    """Interactive HTML BOM generator (stub).

    Will invoke the iBOM ``generate_interactive_bom.py`` script
    directly per ADR 0008. Foundation slice raises.
    """

    def __init__(self, ibom_script: Path) -> None:
        """Construct an iBOM generator.

        Args:
            ibom_script: Path to ``generate_interactive_bom.py`` as
                resolved by :func:`kproj.common.kicad_install.find_ibom_script`.
        """
        self._ibom_script = ibom_script

    def generate(self, pcb_path: Path, output_dir: Path, name_format: str) -> ExportResult:
        """Generate the interactive HTML BOM.

        Raises:
            NotImplementedError: Always, in the foundation slice.
        """
        raise NotImplementedError(
            "IbomGenerator.generate is not implemented in the foundation slice; "
            "see ADR 0008 + docs/DESIGN.md § IbomGenerator."
        )
