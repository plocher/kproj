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
from .library_ref import LibraryRef, LibrarySource
from .project_info import ProjectInfo, Status
from .publication import AssetRef, Publication
from .publish_request import PublishRequest
from .publish_result import Outcome, PublishResult, compute_exit_code
from .raw_title_block import RawTitleBlock
from .resolved_project import ResolvedProject
from .severity import Severity
from .site_management import (
    DeleteOutcome,
    DeleteRequest,
    DeleteResult,
    ProjectListResult,
    PublishedProject,
)

__all__ = [
    "AnalysisInfo",
    "AssetRef",
    "DeleteOutcome",
    "DeleteRequest",
    "DeleteResult",
    "ExportResult",
    "Finding",
    "LibraryRef",
    "LibrarySource",
    "Outcome",
    "ProjectInfo",
    "ProjectListResult",
    "Publication",
    "PublishRequest",
    "PublishResult",
    "PublishedProject",
    "RawTitleBlock",
    "ResolvedProject",
    "Severity",
    "Status",
    "compute_exit_code",
]
