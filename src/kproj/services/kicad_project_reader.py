"""The :class:`KicadProjectReader` service.

Per ``docs/DESIGN.md`` § *Project resolution*, the eventual contract is
``KicadProjectReader.resolve(path) -> ResolvedProject`` that wraps
:func:`jbom.application.pcb_project_loader.resolve_pcb_input`. The
foundation walking-skeleton implements a self-contained resolver
adequate for v1's CLI surface (``.``, ``<dir>/``, ``<basename>``,
``<path>/<file>.kicad_{pro,sch,pcb}``) without taking a hard runtime
dependency on jBOM. The jBOM integration lands in a subsequent issue;
:attr:`ResolvedProject.jbom_resolved` is set to ``None`` until then.

:meth:`KicadProjectReader.read` is stubbed (raises
:class:`NotImplementedError`) — title-block parsing lands in a later
slice.
"""

from __future__ import annotations

from pathlib import Path

from ..model.finding import Finding
from ..model.project_info import ProjectInfo
from ..model.resolved_project import ResolvedProject

_DEFAULT_PROJECTS_ROOT = Path.home() / "Dropbox" / "KiCad" / "projects"
"""SPCoast convention: KiCad project root used for basename lookup."""

_KICAD_EXTENSIONS = {".kicad_pro", ".kicad_pcb", ".kicad_sch"}


class ProjectResolutionError(RuntimeError):
    """Raised by :meth:`KicadProjectReader.resolve` on unresolvable input.

    The message is suitable for direct stderr surfacing; the workflow
    converts the exception into a ``failed``/``exit_code=2``
    :class:`PublishResult`.
    """


class KicadProjectReader:
    """Reads KiCad project files on disk into kproj domain dataclasses.

    Methods:
        resolve: Locate a project given a CLI positional argument.
        read: Parse title-block metadata into :class:`ProjectInfo`
            (not yet implemented; downstream slices populate this).
    """

    def __init__(self, *, projects_root: Path | None = None) -> None:
        """Construct a reader.

        Args:
            projects_root: Optional override for the basename-lookup
                root. Defaults to :data:`_DEFAULT_PROJECTS_ROOT` for
                the SPCoast convention.
        """
        self._projects_root = projects_root or _DEFAULT_PROJECTS_ROOT

    def resolve(self, path_or_basename: str | Path) -> ResolvedProject:
        """Resolve *path_or_basename* into a :class:`ResolvedProject`.

        Handles four input shapes per ``docs/DESIGN.md`` § *Project
        resolution*:

        - ``"."`` / empty / current directory → look in CWD.
        - ``<dir>/`` / directory path → look in that directory.
        - ``<basename>`` (no path separator, doesn't exist as a path)
          → search ``<projects_root>/<basename>/``.
        - ``<path>/<file>.kicad_{pro,sch,pcb}`` → use that file's
          parent directory.

        Args:
            path_or_basename: The user's CLI positional argument.

        Returns:
            A populated :class:`ResolvedProject`.

        Raises:
            ProjectResolutionError: When the directory cannot be
                located, no ``.kicad_pro`` is found, more than one
                ``.kicad_pro`` matches, or the expected adjacent
                ``.kicad_pcb`` / root ``.kicad_sch`` is missing.
        """
        project_dir = self._resolve_directory(path_or_basename)
        project_file = self._find_project_file(project_dir)
        pcb_file = project_dir / f"{project_file.stem}.kicad_pcb"
        if not pcb_file.exists():
            raise ProjectResolutionError(
                f"expected adjacent PCB {pcb_file.name} not found in {project_dir}"
            )
        root_schematic = project_dir / f"{project_file.stem}.kicad_sch"
        if not root_schematic.exists():
            raise ProjectResolutionError(
                f"expected root schematic {root_schematic.name} not found in {project_dir}"
            )
        hierarchical = tuple(sorted(project_dir.glob("*.kicad_sch")))
        return ResolvedProject(
            project_file=project_file,
            project_dir=project_dir,
            pcb_file=pcb_file,
            root_schematic=root_schematic,
            hierarchical_schematics=hierarchical,
            jbom_resolved=None,
            diagnostics=(),
        )

    def read(self, resolved: ResolvedProject) -> tuple[ProjectInfo, tuple[Finding, ...]]:
        """Parse title-block metadata from *resolved* into a ProjectInfo.

        Not implemented in the foundation slice. The metadata reader
        (sexp-walking the ``.kicad_sch`` and ``.kicad_pcb``) lands in
        a subsequent issue per ``docs/DESIGN.md`` § *KicadProjectReader*.

        Args:
            resolved: The :class:`ResolvedProject` produced by :meth:`resolve`.

        Raises:
            NotImplementedError: Always, in the foundation slice.
        """
        raise NotImplementedError(
            "KicadProjectReader.read is not implemented in the foundation slice; "
            "see docs/DESIGN.md § KicadProjectReader."
        )

    # ----- internal helpers -----
    def _resolve_directory(self, path_or_basename: str | Path) -> Path:
        """Resolve the user's CLI positional argument into a project directory."""
        if not path_or_basename or str(path_or_basename) == ".":
            return Path.cwd()
        candidate = Path(path_or_basename)
        if candidate.is_dir():
            return candidate
        if candidate.is_file() and candidate.suffix in _KICAD_EXTENSIONS:
            return candidate.parent
        # Basename lookup: only meaningful when the input has no path separator.
        if "/" not in str(path_or_basename) and "\\" not in str(path_or_basename):
            basename_dir = self._projects_root / str(path_or_basename)
            if basename_dir.is_dir():
                return basename_dir
        raise ProjectResolutionError(
            f"unable to resolve {path_or_basename!r} to a KiCad project directory"
        )

    @staticmethod
    def _find_project_file(project_dir: Path) -> Path:
        """Locate the single ``.kicad_pro`` inside *project_dir*."""
        candidates = sorted(project_dir.glob("*.kicad_pro"))
        if not candidates:
            raise ProjectResolutionError(f"no .kicad_pro found in {project_dir}")
        if len(candidates) > 1:
            names = ", ".join(c.name for c in candidates)
            raise ProjectResolutionError(
                f"multiple .kicad_pro candidates in {project_dir}: {names}"
            )
        return candidates[0]
