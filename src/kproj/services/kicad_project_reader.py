"""The :class:`KicadProjectReader` service.

Wave-2 rewrites the wave-1 self-contained walking-skeleton resolver as
a thin wrapper over jBOM's
:func:`jbom.application.pcb_project_loader.resolve_pcb_input` (per
``docs/DESIGN.md`` § *Project resolution* and ADR 0003).  The wrapper:

- Preserves kproj's SPCoast-specific ``<basename>`` lookup against
  ``~/Dropbox/KiCad/projects/`` when the bare basename does not exist
  relative to the CWD.
- Translates jBOM's :class:`FileNotFoundError` / :class:`ValueError`
  into a single :class:`ProjectResolutionError` carrying a stderr-ready
  message so :class:`PublishWorkflow` can convert it to a
  ``failed``/``exit_code=2`` :class:`PublishResult`.
- Captures jBOM's resolver ``Diagnostic`` notes as kproj
  :class:`Finding` objects.
- Reads title-block metadata from both the SCH and PCB via jBOM's
  :class:`DefaultKiCadReaderService` / :class:`SchematicReader` and
  applies the per-field metadata precedence locked in
  ``docs/DESIGN.md`` § *Metadata precedence*.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path

from jbom.application.pcb_project_loader import (
    list_hierarchical_schematic_files,
    resolve_pcb_input,
)
from jbom.common.types import Diagnostic, TitleBlockMetadata
from jbom.services.pcb_reader import DefaultKiCadReaderService
from jbom.services.schematic_reader import SchematicReader

from ..model.finding import Finding
from ..model.project_info import ProjectInfo, Status
from ..model.raw_title_block import RawTitleBlock
from ..model.resolved_project import ResolvedProject
from ..model.severity import Severity

_DEFAULT_PROJECTS_ROOT = Path.home() / "Dropbox" / "KiCad" / "projects"
"""SPCoast convention: KiCad project root used for basename lookup."""


_STATUS_BY_TOKEN: Mapping[str, Status] = {
    "experimental": Status.EXPERIMENTAL,
    "active": Status.ACTIVE,
    "retired": Status.RETIRED,
    "broken": Status.BROKEN,
    "private": Status.PRIVATE,
}
"""Closed taxonomy minus the parameterised ``replaced-by:<X>``."""


_REPLACED_BY_RE = re.compile(r"^replaced-by:(?P<target>\S+)$")
"""Pattern locking the ``replaced-by:<successor>`` ${COMMENT9} value shape."""


class ProjectResolutionError(RuntimeError):
    """Raised by :meth:`KicadProjectReader.resolve` on unresolvable input.

    The message is suitable for direct stderr surfacing; the workflow
    converts the exception into a ``failed``/``exit_code=2``
    :class:`PublishResult`.
    """


class KicadProjectReader:
    """Reads KiCad project files on disk into kproj domain dataclasses.

    Methods:
        resolve: Locate a project given a CLI positional argument and
            wrap jBOM's :class:`ResolvedPcbProject` in the kproj
            :class:`ResolvedProject` shape.
        read: Read the SCH + PCB title-blocks and produce a
            :class:`ProjectInfo` whose canonical fields apply the
            per-field metadata precedence.
    """

    def __init__(self, *, projects_root: Path | None = None) -> None:
        """Construct a reader.

        Args:
            projects_root: Optional override for the basename-lookup
                root.  Defaults to ``~/Dropbox/KiCad/projects/`` per the
                SPCoast convention.
        """
        self._projects_root = projects_root or _DEFAULT_PROJECTS_ROOT

    def resolve(self, path_or_basename: str | Path) -> ResolvedProject:
        """Resolve *path_or_basename* into a :class:`ResolvedProject`.

        Thin-wraps :func:`resolve_pcb_input` (jBOM 7.3.0).  The
        resolver inside jBOM handles the four input shapes documented
        in ``docs/DESIGN.md`` § *Project resolution* (``"."``, a
        directory, an explicit ``.kicad_pro/.kicad_sch/.kicad_pcb``,
        and a bare basename resolved against the CWD).  kproj adds a
        SPCoast-specific fallback: a bare basename that does not exist
        relative to the CWD is retried against
        ``<projects_root>/<basename>/`` before jBOM is consulted.

        Args:
            path_or_basename: The user's CLI positional argument.

        Returns:
            A populated :class:`ResolvedProject`.

        Raises:
            ProjectResolutionError: When jBOM cannot resolve the input
                or the resolved project is missing its root schematic
                / PCB file.
        """
        candidate = self._maybe_redirect_basename(path_or_basename)
        try:
            jbom_resolved = resolve_pcb_input(str(candidate), artifact_name="kproj")
        except (FileNotFoundError, ValueError) as exc:
            raise ProjectResolutionError(
                f"unable to resolve {str(path_or_basename)!r}: {exc}"
            ) from exc

        project_context = jbom_resolved.project_context
        project_file = project_context.project_file
        if project_file is None:
            raise ProjectResolutionError(
                f"jBOM resolved {path_or_basename!r} but no .kicad_pro is present"
            )
        project_dir = project_file.parent
        pcb_file = jbom_resolved.pcb_path
        if not pcb_file.exists():
            raise ProjectResolutionError(
                f"expected adjacent PCB {pcb_file.name} not found in {project_dir}"
            )
        root_schematic = project_context.schematic_file
        if root_schematic is None or not root_schematic.exists():
            expected = project_dir / f"{project_file.stem}.kicad_sch"
            raise ProjectResolutionError(
                f"expected root schematic {expected.name} not found in {project_dir}"
            )

        hierarchical_files = list_hierarchical_schematic_files(project_context)
        if root_schematic not in hierarchical_files:
            hierarchical_files = [root_schematic, *hierarchical_files]
        hierarchical = tuple(dict.fromkeys(hierarchical_files))

        diagnostics = tuple(
            _diagnostic_to_finding(d, basename=project_file.stem) for d in jbom_resolved.diagnostics
        )

        return ResolvedProject(
            project_file=project_file,
            project_dir=project_dir,
            pcb_file=pcb_file,
            root_schematic=root_schematic,
            hierarchical_schematics=hierarchical,
            jbom_resolved=jbom_resolved,
            text_variables=jbom_resolved.text_variables,
            diagnostics=diagnostics,
        )

    def read(
        self,
        resolved: ResolvedProject,
    ) -> tuple[ProjectInfo, tuple[Finding, ...]]:
        """Parse title-block metadata from *resolved* into a :class:`ProjectInfo`.

        Reads both the SCH and PCB title-blocks via jBOM's reader
        services, then applies the per-field metadata precedence locked
        in ``docs/DESIGN.md`` § *Metadata precedence*:

        - ``title`` / ``company`` - PCB canonical, SCH fallback.
        - ``rev`` - PCB canonical (board_rev); SCH retained as design_rev.
        - ``date`` - PCB canonical (fab date) when populated; SCH fallback.
        - ``comment1`` (designer) - first non-empty side wins.
        - ``comment2`` / ``comment3`` (tagline + overview continuation)
          - SCH canonical, PCB fallback.
        - ``comment9`` (status) - SCH canonical, PCB fallback; defaults
          to :attr:`Status.ACTIVE` when both are absent (the
          ``comment9_missing`` audit warning surfaces separately).

        Read-time diagnostics returned alongside the :class:`ProjectInfo`
        are pure read-mechanic findings (e.g. an unreadable file); the
        14-rule audit semantics live in :class:`MetadataAnalyzer`.

        Args:
            resolved: The :class:`ResolvedProject` produced by
                :meth:`resolve`.

        Returns:
            A ``(ProjectInfo, findings)`` tuple.  ``findings`` is empty
            when both title-blocks read cleanly.
        """
        sch_metadata, sch_findings = _read_metadata_safely(
            SchematicReader().read_metadata,
            resolved.root_schematic,
            project=resolved.basename,
            label="schematic",
        )
        pcb_metadata, pcb_findings = _read_metadata_safely(
            DefaultKiCadReaderService().read_metadata,
            resolved.pcb_file,
            project=resolved.basename,
            label="PCB",
        )

        title = _pcb_canonical(pcb_metadata.title, sch_metadata.title)
        company = _pcb_canonical(pcb_metadata.company, sch_metadata.company)
        design_rev = sch_metadata.revision
        board_rev = _pcb_canonical(pcb_metadata.revision, sch_metadata.revision)
        date = _pcb_canonical(pcb_metadata.date, sch_metadata.date)

        sch_comments = sch_metadata.comments
        pcb_comments = pcb_metadata.comments
        designer = _first_non_empty(sch_comments.get(1, ""), pcb_comments.get(1, ""))
        tagline = _sch_canonical(sch_comments.get(2, ""), pcb_comments.get(2, ""))
        overview_tail = _sch_canonical(sch_comments.get(3, ""), pcb_comments.get(3, ""))
        overview = _join_overview(tagline, overview_tail)
        status_raw = _sch_canonical(sch_comments.get(9, ""), pcb_comments.get(9, ""))
        status, replaced_by_target = _parse_status(status_raw)

        raw_sch = _snapshot(sch_metadata)
        raw_pcb = _snapshot(pcb_metadata)

        project_info = ProjectInfo(
            project=resolved.basename,
            title=title,
            company=company,
            design_rev=design_rev,
            board_rev=board_rev,
            date=date,
            designer=designer,
            tagline=tagline,
            overview=overview,
            status=status,
            fabricated=bool(pcb_metadata.date),
            fab_date=pcb_metadata.date,
            replaced_by_target=replaced_by_target,
            tags=(),
            raw_sch=raw_sch,
            raw_pcb=raw_pcb,
        )
        return project_info, tuple(sch_findings) + tuple(pcb_findings)

    # ----- internal helpers -----
    def _maybe_redirect_basename(self, path_or_basename: str | Path) -> Path:
        """Redirect a SPCoast-style bare basename to ``<projects_root>/<basename>``.

        jBOM's resolver does CWD-relative basename lookup; kproj
        additionally supports the SPCoast convention of placing all
        KiCad projects under ``~/Dropbox/KiCad/projects/``.  Only the
        case ``no path separator AND no CWD-side match AND no suffix``
        triggers the redirect; everything else is passed through
        unchanged so jBOM owns the resolution semantics.
        """
        if isinstance(path_or_basename, Path):
            return path_or_basename
        text = str(path_or_basename)
        if not text or text == "." or "/" in text or "\\" in text:
            return Path(text or ".")
        candidate_local = Path(text)
        if candidate_local.exists() or candidate_local.suffix:
            return candidate_local
        basename_dir = self._projects_root / text
        if basename_dir.is_dir():
            return basename_dir
        return candidate_local


def _snapshot(metadata: TitleBlockMetadata) -> RawTitleBlock:
    """Convert a jBOM :class:`TitleBlockMetadata` to a kproj snapshot.

    ``present`` is computed from the union of any populated scalar +
    any comment key; the jBOM reader returns an empty mapping for a
    missing ``(title_block ...)`` stanza, so a fully-empty
    :class:`RawTitleBlock` corresponds to that case.
    """
    comments = dict(metadata.comments)
    present = bool(
        metadata.title or metadata.company or metadata.revision or metadata.date or comments
    )
    return RawTitleBlock(
        title=metadata.title,
        company=metadata.company,
        revision=metadata.revision,
        date=metadata.date,
        comments=comments,
        present=present,
    )


def _diagnostic_to_finding(diagnostic: Diagnostic, *, basename: str) -> Finding:
    """Convert a jBOM :class:`Diagnostic` to a kproj :class:`Finding`."""
    severity_map: dict[str, Severity] = {
        "error": Severity.ERROR,
        "warning": Severity.WARNING,
        "info": Severity.WARNING,
    }
    severity = severity_map.get(diagnostic.severity, Severity.WARNING)
    return Finding(
        severity=severity,
        field="resolver_note",
        value="",
        reason=diagnostic.message,
        project=basename,
        source="read",
    )


def _read_metadata_safely(
    reader_fn: Callable[[Path], TitleBlockMetadata],
    path: Path,
    *,
    project: str,
    label: str,
) -> tuple[TitleBlockMetadata, tuple[Finding, ...]]:
    """Call a jBOM reader with a uniform error envelope.

    Returns the parsed metadata plus any read-time findings.  A failure
    to parse the file does NOT propagate; the caller continues with an
    empty :class:`TitleBlockMetadata` and a warning :class:`Finding`
    documents the failure for stderr.
    """
    try:
        metadata = reader_fn(path)
    except Exception as exc:
        finding = Finding(
            severity=Severity.WARNING,
            field=f"{label.lower()}_titleblock_unreadable",
            value=str(path),
            reason=f"failed to read {label} title-block at {path}: {exc}",
            project=project,
            source="read",
        )
        return TitleBlockMetadata(), (finding,)
    return metadata, ()


def _pcb_canonical(pcb_value: str, sch_fallback: str) -> str:
    """Return ``pcb_value`` if non-empty else ``sch_fallback``."""
    return pcb_value if pcb_value else sch_fallback


def _sch_canonical(sch_value: str, pcb_fallback: str) -> str:
    """Return ``sch_value`` if non-empty else ``pcb_fallback``."""
    return sch_value if sch_value else pcb_fallback


def _first_non_empty(*values: str) -> str:
    """Return the first non-empty string from *values*; empty if none."""
    for value in values:
        if value:
            return value
    return ""


def _join_overview(tagline: str, tail: str) -> str:
    """Join comment2 + comment3 with a single separator, skipping empties."""
    parts = [part for part in (tagline, tail) if part]
    return " ".join(parts)


def _parse_status(value: str) -> tuple[Status, str | None]:
    """Map a ``${COMMENT9}`` value to a :class:`Status` + optional target.

    Unknown / empty / out-of-taxonomy values fall through to
    :attr:`Status.ACTIVE` per the locked v1 default; the
    ``comment9_missing`` / ``comment9_taxonomy`` audit rules surface
    the warning separately.

    Args:
        value: Raw ``${COMMENT9}`` string (already trimmed by the
            reader; empty when absent).

    Returns:
        ``(Status, target)`` where ``target`` is the successor project
        directory name only when the value matches ``replaced-by:<X>``;
        ``None`` otherwise.
    """
    trimmed = value.strip()
    if not trimmed:
        return Status.ACTIVE, None
    match = _REPLACED_BY_RE.match(trimmed)
    if match is not None:
        return Status.REPLACED_BY, match.group("target")
    known = _STATUS_BY_TOKEN.get(trimmed)
    if known is not None:
        return known, None
    # Unknown taxonomy: default to ACTIVE; audit rule will warn.
    return Status.ACTIVE, None
