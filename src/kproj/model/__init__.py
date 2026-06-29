"""kproj domain model: frozen, side-effect-free value objects.

Per ``docs/adr/0006-library-shape-boundary-discipline.md``, this layer
has zero file-system or subprocess dependencies. Services + workflows
construct and consume these dataclasses; only the model layer itself
imports from this package.
"""

from __future__ import annotations

from .analysis_info import AnalysisInfo
from .export_result import ExportResult
from .finding import Finding
from .project_info import ProjectInfo, Status
from .publication import AssetRef, Publication
from .resolved_project import ResolvedProject
from .severity import Severity

__all__ = [
    "AnalysisInfo",
    "AssetRef",
    "ExportResult",
    "Finding",
    "ProjectInfo",
    "Publication",
    "ResolvedProject",
    "Severity",
    "Status",
]
