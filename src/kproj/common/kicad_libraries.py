"""Library enumeration for a KiCad project.

The scanner is project-centric and deterministic:

1. Resolve the project basename from the single ``*.kicad_pro`` file
   in ``project_dir``.
2. Read root files ``<project>.kicad_sch`` and ``<project>.kicad_pcb``.
3. Walk the schematic hierarchy via each sheet's ``(sheetfile "...")``
   references.

No broad recursive filesystem walk is performed. Backup/history paths
(``.history``, ``*-backups``, ``production``) are ignored.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..model.library_ref import (
    LibraryDistribution,
    LibraryKind,
    LibraryRef,
    LibrarySource,
)

_LIB_TABLE_ENTRY: re.Pattern[str] = re.compile(
    r'\(lib\s+\(name\s+"?(?P<name>[^"\)]+)"?\s*\)\s*'
    r"(?:\([^)]*\)\s*)*?"
    r'\(uri\s+"?(?P<uri>[^"\)]+)"?\s*\)'
)
"""Match ``(lib (name <NAME>) ... (uri <URI>))`` lib-table entries."""

_LIB_ID_REF: re.Pattern[str] = re.compile(r'\(lib_id\s+"(?P<token>[^"\:]+:[^"]+)"\s*\)')
"""Match ``(lib_id "lib:name")`` references."""

_FOOTPRINT_REF: re.Pattern[str] = re.compile(r'\(footprint\s+"(?P<token>[^"\:]+:[^"]+)"')
"""Match PCB footprint blocks beginning with ``(footprint "lib:name"``."""

_SHEETFILE_REF: re.Pattern[str] = re.compile(r'\(sheetfile\s+"(?P<sheet>[^"]+)"\)')
"""Match schematic child-sheet references."""

_DEFAULT_KICAD_SYMBOL_LIBS: frozenset[str] = frozenset({"power"})
"""Common stock KiCad symbol libraries when no explicit lib-table exists."""

_IGNORED_PATH_PARTS: frozenset[str] = frozenset({".history", "production"})
"""Directory names ignored when traversing schematic hierarchy."""

_IGNORED_PATH_SUFFIXES: tuple[str, ...] = ("-backups",)
"""Directory-name suffixes ignored when traversing schematic hierarchy."""


class _LibraryAccumulator:
    """Mutable aggregation state for one ``(name, kind)`` library entry."""

    def __init__(
        self,
        *,
        source: LibrarySource,
        distribution: LibraryDistribution,
    ) -> None:
        self.source = source
        self.distribution = distribution

    def merge_from_table(
        self,
        *,
        source: LibrarySource,
        distribution: LibraryDistribution,
    ) -> None:
        """Merge table-derived data, with conservative precedence."""
        if self.source == "internal" and source == "external":
            self.source = "external"
        if _distribution_rank(distribution) > _distribution_rank(self.distribution):
            self.distribution = distribution

    def merge_from_reference(self) -> None:
        """No-op today: table data remains authoritative."""
        return


def enumerate_libraries(project_dir: Path) -> tuple[LibraryRef, ...]:
    """Return all symbol/footprint libraries the project references.

    Uses deterministic project traversal rooted at ``*.kicad_pro`` and
    the root schematic hierarchy. This intentionally avoids broad
    recursive scans that can pick up stale history/backup artifacts.

    Args:
        project_dir: KiCad project directory. Missing/non-directory
            inputs return ``()``.

    Returns:
        Stable-sorted tuple of :class:`LibraryRef` values.
    """
    if not project_dir.is_dir():
        return ()

    project_name = _project_name(project_dir)
    if project_name is None:
        return ()

    symbol_classifications: dict[str, _LibraryAccumulator] = {}
    footprint_classifications: dict[str, _LibraryAccumulator] = {}

    _ingest_lib_table(
        table=project_dir / "sym-lib-table",
        kind="symbol",
        target=symbol_classifications,
    )
    _ingest_lib_table(
        table=project_dir / "fp-lib-table",
        kind="footprint",
        target=footprint_classifications,
    )

    root_sch = project_dir / f"{project_name}.kicad_sch"
    root_pcb = project_dir / f"{project_name}.kicad_pcb"

    for sch_path in _walk_schematic_tree(root_sch):
        text = sch_path.read_text(errors="replace")
        for match in _LIB_ID_REF.finditer(text):
            lib_name = match.group("token").split(":", 1)[0].strip()
            if not lib_name:
                continue
            existing = symbol_classifications.get(lib_name)
            if existing is None:
                symbol_classifications[lib_name] = _LibraryAccumulator(
                    source="ambiguous",
                    distribution=_distribution_from_ambiguous_symbol(lib_name),
                )
            else:
                existing.merge_from_reference()

    if root_pcb.is_file():
        text = root_pcb.read_text(errors="replace")
        for match in _FOOTPRINT_REF.finditer(text):
            lib_name = match.group("token").split(":", 1)[0].strip()
            if not lib_name:
                continue
            existing = footprint_classifications.get(lib_name)
            if existing is None:
                footprint_classifications[lib_name] = _LibraryAccumulator(
                    source="ambiguous",
                    distribution="unknown",
                )
            else:
                existing.merge_from_reference()

    refs: list[LibraryRef] = []
    for name, acc in symbol_classifications.items():
        refs.append(
            LibraryRef(
                name=name,
                source=acc.source,
                kind="symbol",
                distribution=acc.distribution,
            )
        )
    for name, acc in footprint_classifications.items():
        refs.append(
            LibraryRef(
                name=name,
                source=acc.source,
                kind="footprint",
                distribution=acc.distribution,
            )
        )
    return tuple(sorted(refs))


def _project_name(project_dir: Path) -> str | None:
    """Return project basename from a single ``*.kicad_pro`` file."""
    kicad_pros = sorted(project_dir.glob("*.kicad_pro"))
    if len(kicad_pros) != 1:
        return None
    return kicad_pros[0].stem


def _walk_schematic_tree(root_sch: Path) -> tuple[Path, ...]:
    """Return deterministic DFS order of schematic files from root."""
    if not root_sch.is_file():
        return ()
    ordered: list[Path] = []
    stack: list[Path] = [root_sch]
    seen: set[Path] = set()
    while stack:
        current = stack.pop()
        if current in seen or not current.is_file():
            continue
        if _is_ignored_path(current):
            continue
        seen.add(current)
        ordered.append(current)
        text = current.read_text(errors="replace")
        children: list[Path] = []
        for match in _SHEETFILE_REF.finditer(text):
            child_rel = match.group("sheet").strip()
            if not child_rel:
                continue
            child = (current.parent / child_rel).resolve()
            if _is_ignored_path(child):
                continue
            children.append(child)
        for child in reversed(children):
            stack.append(child)
    return tuple(ordered)


def _is_ignored_path(path: Path) -> bool:
    """Return whether *path* includes ignored history/backup segments."""
    parts = set(path.parts)
    if parts.intersection(_IGNORED_PATH_PARTS):
        return True
    for part in path.parts:
        for suffix in _IGNORED_PATH_SUFFIXES:
            if part.endswith(suffix):
                return True
    return False


def _ingest_lib_table(
    *,
    table: Path,
    kind: LibraryKind,
    target: dict[str, _LibraryAccumulator],
) -> None:
    """Parse one KiCad lib-table into an accumulator map."""
    if not table.is_file():
        return
    for match in _LIB_TABLE_ENTRY.finditer(table.read_text(errors="replace")):
        name = match.group("name").strip()
        if not name:
            continue
        uri = match.group("uri").strip()
        source = _classify_uri(uri)
        distribution = _distribution_from_uri(uri, kind=kind)
        existing = target.get(name)
        if existing is None:
            target[name] = _LibraryAccumulator(
                source=source,
                distribution=distribution,
            )
        else:
            existing.merge_from_table(source=source, distribution=distribution)


def _distribution_from_uri(uri: str, *, kind: LibraryKind) -> LibraryDistribution:
    """Classify URI as likely stock KiCad vs project-added."""
    upper = uri.upper()
    if upper.startswith("${KISYSMOD}"):
        return "kicad"
    if kind == "symbol" and upper.startswith("${KICAD_SYMBOL_DIR}"):
        return "kicad"
    if kind == "footprint" and upper.startswith("${KICAD_FOOTPRINT_DIR}"):
        return "kicad"
    if upper.startswith("${KIPRJMOD}"):
        return "added"
    return "added"


def _distribution_from_ambiguous_symbol(lib_name: str) -> LibraryDistribution:
    """Best-effort fallback for symbol refs lacking a table mapping."""
    if lib_name in _DEFAULT_KICAD_SYMBOL_LIBS:
        return "kicad"
    return "unknown"


def _distribution_rank(value: LibraryDistribution) -> int:
    """Priority order when merging conflicting distribution evidence."""
    if value == "added":
        return 3
    if value == "kicad":
        return 2
    return 1


def _classify_uri(uri: str) -> LibrarySource:
    """Return ``"internal"`` or ``"external"`` for a lib-table URI.

    A ``${KIPRJMOD}``-prefixed URI is project-local (``"internal"``)
    unless the tail contains a ``..`` segment that escapes the project
    root. Everything else is treated as ``"external"``.
    """
    if uri.startswith("${KIPRJMOD}"):
        tail = uri[len("${KIPRJMOD}") :]
        if ".." in tail.split("/"):
            return "external"
        return "internal"
    return "external"
