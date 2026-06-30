"""The :class:`ResolvedProject` value object.

kproj-owned wrapper around jBOM's ``ResolvedPcbProject`` per
``docs/DESIGN.md`` § *Project resolution*.  All downstream services
accept this shape so they never see jBOM's internal types directly
(ADR 0006 boundary discipline).

Wave-2 swaps the wave-1 self-contained resolver for a thin-wrap over
:func:`jbom.application.pcb_project_loader.resolve_pcb_input` and
exposes the per-project ``text_variables`` mapping that jBOM 7.3.0
added; v1 does not actively consume the mapping but carrying it on the
kproj-side keeps the boundary forward-compatible.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from .finding import Finding

if TYPE_CHECKING:  # pragma: no cover - import only for type-checkers
    from jbom.application.pcb_project_loader import ResolvedPcbProject

_EMPTY_TEXT_VARIABLES: Mapping[str, str] = MappingProxyType({})
"""Sentinel mapping used as the default when jBOM reports no text variables."""


@dataclass(frozen=True)
class ResolvedProject:
    """A kproj-owned snapshot of a resolved KiCad project.

    Attributes:
        project_file: Canonical ``.kicad_pro`` path.
        project_dir: Parent directory of ``project_file``.
        pcb_file: Canonical ``.kicad_pcb`` path.
        root_schematic: Root ``.kicad_sch`` path.
        hierarchical_schematics: All ``.kicad_sch`` files referenced
            (transitively) from the root.  Always includes
            :attr:`root_schematic`; single-sheet projects therefore have
            a one-element tuple.
        jbom_resolved: The underlying jBOM artifact (see
            :class:`jbom.application.pcb_project_loader.ResolvedPcbProject`).
            ``None`` only in synthetic tests that bypass the real reader;
            production callsites always have it populated.
        text_variables: ``.kicad_pro`` ``${VAR}`` substitution mapping
            sourced from :attr:`ResolvedPcbProject.text_variables`.
            Empty mapping when the project declares no variables.
        diagnostics: Resolution-time findings (e.g. resolver Notes).
    """

    project_file: Path
    project_dir: Path
    pcb_file: Path
    root_schematic: Path
    hierarchical_schematics: tuple[Path, ...]
    jbom_resolved: ResolvedPcbProject | None = None
    text_variables: Mapping[str, str] = field(default_factory=lambda: _EMPTY_TEXT_VARIABLES)
    diagnostics: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def basename(self) -> str:
        """Return the ``.kicad_pro`` filename stem.

        Used as the canonical ``<P>`` token in asset filenames and
        per-version directory layout.
        """
        return self.project_file.stem
