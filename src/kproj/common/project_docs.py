"""Discovery of project-global prose docs (per the EAGLE content model).

A KiCad project's *global* identity (constant across versions) includes
prose docs (``README.md``, an optional ``DESCRIPTION``). These are
distinct from the per-version sources + derived artifacts.

This module surfaces the project-global DESCRIPTION prose so the
publish workflow can render it on the project section index
(``content/versions/<P>/_index.md``).

kproj#29: the sibling per-project ``*.pdf`` disk-walk
(``discover_datasheets`` / ``discover_datasheet_files``) that used to
live here is retired. The project-index Documentation list now derives
solely from the BOM's ``Datasheet Name`` column
(``production/jbom.csv``) via :mod:`kproj.common.datasheet_library`,
per the datasheet document library's publish-mechanics resolution
(``plocher/jBOM#350``) — kproj never copies or walks for datasheet
PDFs in a project directory.
"""

from __future__ import annotations

from pathlib import Path

# Candidate DESCRIPTION filenames, in preference order. The first that
# exists wins. Mirrors the README-style project-global prose convention.
_DESCRIPTION_NAMES: tuple[str, ...] = ("DESCRIPTION.md", "DESCRIPTION.txt", "DESCRIPTION")


def read_description(project_dir: Path) -> str:
    """Return the project's ``DESCRIPTION`` prose, or an empty string.

    Looks for ``DESCRIPTION.md`` / ``DESCRIPTION.txt`` / ``DESCRIPTION``
    (first match wins) at the project root. This is project-global prose
    that complements ``README.md`` on the project index page.

    Args:
        project_dir: The resolved project directory.

    Returns:
        The file's text content, or ``""`` when no DESCRIPTION exists.
    """
    for name in _DESCRIPTION_NAMES:
        candidate = project_dir / name
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    return ""
