"""Discovery of project-global documentation (per the EAGLE content model).

A KiCad project's *global* identity (constant across versions) includes
prose docs (``README.md``, an optional ``DESCRIPTION``) and reference
datasheet PDFs that live in the project directory. These are distinct
from the per-version sources + derived artifacts.

This module surfaces the project-global docs so the publish workflow can
list them on the project section index (``content/versions/<P>/_index.md``).

v1 (grey-scale) scope: **discovery only** — return the datasheet
filenames and the DESCRIPTION text. Rendering is a plain name list in the
index body (see ``SitePublisher``); copying the PDFs to the site and
linking/preview UX are deferred follow-ups.
"""

from __future__ import annotations

import os
from pathlib import Path

# Candidate DESCRIPTION filenames, in preference order. The first that
# exists wins. Mirrors the README-style project-global prose convention.
_DESCRIPTION_NAMES: tuple[str, ...] = ("DESCRIPTION.md", "DESCRIPTION.txt", "DESCRIPTION")

# Directory names pruned from the recursive datasheet scan. These hold
# generated output rather than maintainer-curated reference PDFs.
_PRUNED_DIR_NAMES: frozenset[str] = frozenset({"production"})


def _is_pruned_dir(name: str) -> bool:
    """Return whether a directory should be skipped during discovery.

    Prunes hidden directories (``.git``, ``.history``, ...), KiCad
    ``*-backups`` directories, and known generated-output trees so the
    scan surfaces only maintainer-curated datasheets.

    Args:
        name: A single directory name (not a path).

    Returns:
        ``True`` when the directory (and its subtree) should be skipped.
    """
    return name.startswith(".") or name.endswith("-backups") or name in _PRUNED_DIR_NAMES


def discover_datasheets(project_dir: Path) -> tuple[str, ...]:
    """Return the project-global datasheet PDF filenames.

    Recursively scans ``project_dir`` for ``*.pdf`` files so datasheets are
    found wherever the maintainer stores them (project root, ``docs/``,
    ``ds-downloads/``, ...). Directories that hold generated output, VCS
    internals, or tool backups are pruned (see :func:`_is_pruned_dir`):
    hidden directories such as ``.git`` / ``.history``, KiCad ``*-backups``
    directories, and the fab ``production/`` tree.

    Args:
        project_dir: The resolved project directory.

    Returns:
        A case-insensitively sorted tuple of unique PDF basenames (stable
        output for reproducible publishes). Empty when the project has none.
    """
    if not project_dir.is_dir():
        return ()
    names: set[str] = set()
    for _root, dirs, files in os.walk(project_dir):
        # Prune excluded subtrees in place so os.walk does not descend them.
        dirs[:] = [d for d in dirs if not _is_pruned_dir(d)]
        for fname in files:
            if fname.lower().endswith(".pdf"):
                names.add(fname)
    return tuple(sorted(names, key=str.lower))


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
