"""The :class:`ExportResult` value object.

The uniform return type for any kproj service that writes a file via a
subprocess or via in-process zip assembly. Per ``docs/DESIGN.md`` §
*ExportResult*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .finding import Finding


@dataclass(frozen=True)
class ExportResult:
    """Result of a side-effecting service invocation.

    Attributes:
        path: Produced artifact path; ``None`` when ``skipped`` is
            ``True``.
        diagnostics: Findings emitted while producing the artifact
            (warnings + info only; errors raise instead).
        command: Subprocess argv when the service invoked an external
            tool; ``None`` for pure-Python services (e.g. ``ZipArchiver``).
        elapsed_seconds: Wall-clock time the service's primary method
            consumed, populated by the subprocess runner where applicable.
        skipped: ``True`` when the service intentionally produced no
            output (e.g. ``FabPackager`` with an empty ``production/``).
    """

    path: Path | None
    diagnostics: tuple[Finding, ...] = field(default_factory=tuple)
    command: tuple[str, ...] | None = None
    elapsed_seconds: float = 0.0
    skipped: bool = False
