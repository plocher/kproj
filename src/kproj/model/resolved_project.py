"""The :class:`ResolvedProject` value object.

kproj-owned wrapper around jBOM's ``ResolvedPcbProject`` per
``docs/DESIGN.md`` § *Project resolution*. All downstream services
accept this shape so they never see jBOM's internal types directly
(ADR 0006 boundary discipline).

The :attr:`ResolvedProject.jbom_resolved` field is typed as ``object``
to avoid a hard runtime dependency on jBOM during the foundation
slice. ``KicadProjectReader.resolve`` will populate it with the real
``jbom.common.types.ResolvedPcbProject`` instance once the jBOM
integration lands; consumers that need it should cast at the call
site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .finding import Finding


@dataclass(frozen=True)
class ResolvedProject:
    """A kproj-owned snapshot of a resolved KiCad project.

    Attributes:
        project_file: Canonical ``.kicad_pro`` path.
        project_dir: Parent directory of ``project_file``.
        pcb_file: Canonical ``.kicad_pcb`` path.
        root_schematic: Root ``.kicad_sch`` path.
        hierarchical_schematics: All ``.kicad_sch`` files referenced
            (transitively) from the root.
        jbom_resolved: The underlying jBOM artifact (or ``None`` until
            the jBOM integration lands).
        diagnostics: Resolution-time findings (e.g. ambiguous matches).
    """

    project_file: Path
    project_dir: Path
    pcb_file: Path
    root_schematic: Path
    hierarchical_schematics: tuple[Path, ...]
    jbom_resolved: object | None = None
    diagnostics: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def basename(self) -> str:
        """Return the ``.kicad_pro`` filename stem.

        Used as the canonical ``<P>`` token in asset filenames and
        per-version directory layout.
        """
        return self.project_file.stem
