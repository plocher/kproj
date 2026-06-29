"""Stub :class:`MetadataAnalyzer` (docs/DESIGN.md § MetadataAnalyzer).

The full audit heuristic list lands in a subsequent issue; the
foundation slice exists only so :class:`PublishWorkflow` has a stable
type to inject.
"""

from __future__ import annotations

from pathlib import Path

from ..model.analysis_info import AnalysisInfo
from ..model.project_info import ProjectInfo


class MetadataAnalyzer:
    """Metadata-quality lint pass (stub).

    Methods:
        analyze: Will produce metadata Findings per the audit heuristic
            list in ``docs/DESIGN.md`` § *Audit heuristic list*. Raises
            :class:`NotImplementedError` until the heuristic slice lands.
    """

    def __init__(self) -> None:
        """Construct a metadata analyzer."""

    def analyze(self, project_info: ProjectInfo, project_path: Path) -> AnalysisInfo:
        """Run the metadata audit on *project_info* and adjacent files.

        Args:
            project_info: The project's title-block-derived facts.
            project_path: Path to the project directory.

        Raises:
            NotImplementedError: Always, in the foundation slice.
        """
        raise NotImplementedError(
            "MetadataAnalyzer.analyze is not implemented in the foundation slice; "
            "see docs/DESIGN.md § Audit heuristic list."
        )
