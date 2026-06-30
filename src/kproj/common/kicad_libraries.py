"""Library enumeration for a KiCad project.

This utility scans a project's ``fp-lib-table`` + ``sym-lib-table``
plus its ``*.kicad_sch`` / ``*.kicad_pcb`` / ``*.kicad_sym`` files and
returns the libraries the project references, each tagged with a
classification (:data:`kproj.model.library_ref.LibrarySource`):

- ``internal`` - the library ships inside the source.zip via the
  ``Include`` rules.  Identified by a lib-table entry whose URI starts
  with ``${KIPRJMOD}`` and whose tail does not contain a ``..``
  segment that escapes the project root.
- ``external`` - the library lives outside the project.  Identified
  by a lib-table entry whose URI is absolute, ``${KISYSMOD}``-prefixed,
  ``${KIPRJMOD}/../...``, a URL, or anything else that doesn't resolve
  inside the project directory.
- ``ambiguous`` - the library is referenced by a
  ``(lib_id "<lib>:<name>")`` or ``(footprint "<lib>:<name>")``
  somewhere in the design but has no matching ``fp-lib-table`` /
  ``sym-lib-table`` entry, so we cannot authoritatively classify it.

Classification precedence: a lib-table entry wins over a bare
``(lib_id ...)`` reference for the same library name.  This means a
project that ships a project-local ``fp-lib-table`` entry for a lib
and also references it from a schematic will report that lib once,
as ``internal``.

The result is sorted by ``(name, source)`` for reproducibility.  No
filesystem or network I/O beyond reading the lib-tables + KiCad
design files in ``project_dir``.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..model.library_ref import LibraryRef, LibrarySource

_LIB_TABLE_ENTRY: re.Pattern[str] = re.compile(
    r'\(lib\s+\(name\s+"?(?P<name>[^"\)]+)"?\s*\)\s*'
    r"(?:\([^)]*\)\s*)*?"
    r'\(uri\s+"?(?P<uri>[^"\)]+)"?\s*\)'
)
"""Match ``(lib (name <NAME>) ... (uri <URI>))`` lib-table entries."""

_LIB_ID_REF: re.Pattern[str] = re.compile(
    r'\((?:lib_id|footprint)\s+"(?P<token>[^"\:]+:[^"]+)"\s*\)'
)
"""Match ``(lib_id "lib:name")`` and ``(footprint "lib:name")`` refs."""

_KIPRJMOD_PREFIX: str = "${KIPRJMOD}"
"""KiCad project-relative path prefix used in lib-table URIs."""

_SCAN_SUFFIXES: frozenset[str] = frozenset({".kicad_sch", ".kicad_pcb", ".kicad_sym"})
"""File suffixes whose contents are scanned for ``(lib_id ...)`` refs."""


def enumerate_libraries(project_dir: Path) -> tuple[LibraryRef, ...]:
    """Return all libraries the project references, classified.

    Walks the lib-tables first to build an authoritative name → source
    map, then scans every ``.kicad_sch`` / ``.kicad_pcb`` /
    ``.kicad_sym`` under *project_dir* for ``(lib_id ...)`` /
    ``(footprint ...)`` references.  References whose ``<lib>`` prefix
    is not in the lib-table map are added as ``ambiguous``.

    Args:
        project_dir: The KiCad project directory.  Need not exist - a
            missing directory yields ``()``.

    Returns:
        A stable-sorted tuple of :class:`LibraryRef` instances (sorted
        by ``(name, source)``).  Reproducible for the same input.
    """
    if not project_dir.is_dir():
        return ()

    classifications: dict[str, LibrarySource] = {}

    # Pass 1: lib-tables are authoritative.
    for table_name in ("fp-lib-table", "sym-lib-table"):
        table = project_dir / table_name
        if not table.is_file():
            continue
        for match in _LIB_TABLE_ENTRY.finditer(table.read_text(errors="replace")):
            name = match.group("name").strip()
            if not name:
                continue
            source = _classify_uri(match.group("uri").strip())
            # If both lib-tables list the same name with conflicting
            # classifications, prefer "external" - safer-to-warn.
            existing = classifications.get(name)
            if existing is None or (existing == "internal" and source == "external"):
                classifications[name] = source

    # Pass 2: lib_id / footprint refs.  Anything not already in the
    # lib-table map is "ambiguous" - present in the design but we
    # cannot tell where the KiCad install would look for it.
    for path in sorted(project_dir.rglob("*")):
        if not (path.is_file() and path.suffix in _SCAN_SUFFIXES):
            continue
        for match in _LIB_ID_REF.finditer(path.read_text(errors="replace")):
            token = match.group("token")
            lib_name = token.split(":", 1)[0]
            if lib_name and lib_name not in classifications:
                classifications[lib_name] = "ambiguous"

    refs = tuple(LibraryRef(name=name, source=source) for name, source in classifications.items())
    return tuple(sorted(refs))


def _classify_uri(uri: str) -> LibrarySource:
    """Return ``"internal"`` or ``"external"`` for a lib-table URI.

    A ``${KIPRJMOD}``-prefixed URI is project-local (``"internal"``)
    unless the tail contains a ``..`` segment that escapes the project
    root.  Everything else (absolute paths, ``${KISYSMOD}``,
    network URLs) is treated as ``"external"``.
    """
    if uri.startswith(_KIPRJMOD_PREFIX):
        tail = uri[len(_KIPRJMOD_PREFIX) :]
        if ".." in tail.split("/"):
            return "external"
        return "internal"
    return "external"
