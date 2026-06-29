"""Stub :class:`DesignAnalyzer` (docs/DESIGN.md § DesignAnalyzer)."""

from __future__ import annotations

from pathlib import Path

from ..model.analysis_info import AnalysisInfo
from ..model.resolved_project import ResolvedProject


class DesignAnalyzer:
    """DRC + ERC analyzer (stub).

    Will invoke ``kicad-cli pcb drc`` and ``kicad-cli sch erc`` and
    parse JSON output into Findings per ``docs/DESIGN.md`` §
    *DesignAnalyzer*. Foundation slice raises.
    """

    def __init__(self, kicad_cli: Path) -> None:
        """Construct a design analyzer.

        Args:
            kicad_cli: Path to the discovered ``kicad-cli`` executable.
        """
        self._kicad_cli = kicad_cli

    def analyze(self, resolved: ResolvedProject) -> AnalysisInfo:
        """Run DRC + ERC against *resolved*.

        Raises:
            NotImplementedError: Always, in the foundation slice.
        """
        raise NotImplementedError(
            "DesignAnalyzer.analyze is not implemented in the foundation slice; "
            "see docs/DESIGN.md § DesignAnalyzer."
        )
