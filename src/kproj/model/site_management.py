"""Site-management value objects for listing and deleting published content.

These dataclasses model CLI operations that act on published site state
(``kproj list ...`` and ``kproj delete ...``), separate from the
publish pipeline's ``PublishRequest`` / ``PublishResult`` types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..config import KprojConfig

DeleteOutcome = Literal["deleted-version", "deleted-project", "preview", "failed"]
"""Closed set of delete-operation outcomes."""


@dataclass(frozen=True)
class PublishedProject:
    """Published project shape discovered from the site repository.

    Attributes:
        project: Project identifier (directory name under versions/assets roots).
        versions: Sorted tuple of published version identifiers.
    """

    project: str
    versions: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class DeleteRequest:
    """Inputs for a delete operation against published site content.

    Attributes:
        project: Target project identifier.
        version: Optional target version. When ``None``, the operation
            targets the project scope.
        force: Whether destructive project deletion is allowed.
        dry_run: Read-only preview mode.
        config: Effective runtime config (site repo path + push behavior).
    """

    project: str
    version: str | None
    force: bool
    dry_run: bool
    config: KprojConfig


@dataclass(frozen=True)
class DeleteResult:
    """Outcome of a delete operation."""

    outcome: DeleteOutcome
    exit_code: int
    message: str = ""
    deleted_versions: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProjectListResult:
    """Outcome of listing published projects."""

    exit_code: int
    message: str = ""
