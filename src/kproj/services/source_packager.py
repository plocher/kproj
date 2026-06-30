"""The :class:`SourcePackager` service.

Per ``docs/DESIGN.md`` § *SourcePackager*, this service walks a
``project_dir`` (applying the locked include/exclude rules) and
assembles the non-derived KiCad source files into
``<P>-<R>.source.zip``.

The v1 archive captures **project artifacts** only - the
``*.kicad_pro`` / ``*.kicad_sch`` / ``*.kicad_pcb`` files plus any
sidecar library / drawing-sheet / readme content. External libraries
(SPCoast shared, KiCad bundled, vendor sets) are KiCad-install context
and are NOT vendored. KiCad 6.0+ embeds the symbols + footprints used
in the design into the project files themselves, so opening the
archive in KiCad shows the correct schematic + PCB without the
external libraries; if any link is genuinely missing KiCad's own UI
surfaces the gap when the project is opened.
"""

from __future__ import annotations

import os
import re
import time
import uuid
import zipfile
from collections.abc import Iterable
from pathlib import Path

from ..model.export_result import ExportResult
from .change_journal import ChangeJournal
from .zip_archiver import ZipArchiver

# ----- include / exclude rules from docs/DESIGN.md § SourcePackager -----

_INCLUDE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".kicad_pro",
        ".kicad_sch",
        ".kicad_pcb",
        ".kicad_sym",
        ".kicad_mod",
        ".kicad_dru",
        ".kicad_wks",
    }
)
_INCLUDE_FILENAMES: frozenset[str] = frozenset(
    {
        "fp-lib-table",
        "sym-lib-table",
        "README.md",
        "CHANGELOG.md",
    }
)
_INCLUDE_FILENAME_STEMS: frozenset[str] = frozenset({"LICENSE"})
"""Filename stems that are always included regardless of suffix (e.g. ``LICENSE`` or ``LICENSE.txt``)."""

_EXCLUDE_SUFFIXES: frozenset[str] = frozenset(
    {
        ".kicad_prl",
        ".kicad_lock",
        ".step",
        ".pyc",
    }
)
_EXCLUDE_EXACT_NAMES: frozenset[str] = frozenset({".DS_Store", "release.yaml"})
_EXCLUDE_DIR_NAMES: frozenset[str] = frozenset(
    {
        "production",
        "gerbers",
        "bom",
        ".git",
        ".github",
        ".vscode",
        ".idea",
        "dist",
        "build",
        "node_modules",
        "venv",
        "__pycache__",
    }
)
_EXCLUDE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r".*-bak$"),
    re.compile(r".*~$"),
    re.compile(r"^_autosave-.*"),
    re.compile(r".*\.ibom\.html$"),
    re.compile(r".*\.svg$"),
    re.compile(r"thumbnail\.png"),
    # Render PNGs: any *.png at the root is excluded (kproj-generated).
    re.compile(r".*\.png$"),
)


class SourcePackager:
    """Walks ``project_dir`` and assembles ``<P>-<R>.source.zip``."""

    def __init__(self, zip_archiver: ZipArchiver) -> None:
        """Construct a source packager.

        Args:
            zip_archiver: The shared :class:`ZipArchiver` instance.
                SourcePackager bypasses it for the final assembly so
                paths are stored relative to *project_dir* exactly,
                but accepting it preserves the documented dependency
                graph.
        """
        self._zip_archiver = zip_archiver

    def package(
        self,
        project_dir: Path,
        output: Path,
        *,
        title: str,
        rev: str,
        journal: ChangeJournal | None = None,
    ) -> ExportResult:
        """Assemble ``<P>-<R>.source.zip`` from *project_dir*.

        Walks *project_dir* per the documented include/exclude rules
        and assembles the matching files into *output* via
        :class:`ZipArchiver`-style atomic write.

        Args:
            project_dir: The KiCad project directory to package.
            output: Final ``<P>-<R>.source.zip`` path.
            title: Project title. Carried on the signature for log /
                diagnostic shapes; not currently embedded in the
                archive.
            rev: Board revision. Same as *title* - signature-only
                today.
            journal: Optional open :class:`ChangeJournal`.

        Returns:
            A populated :class:`ExportResult` whose ``path`` is the
            produced zip and whose ``command`` is ``None`` (in-process
            assembly; no subprocess).
        """
        del title, rev  # signature-stable; not consumed by the v1 packager
        output.parent.mkdir(parents=True, exist_ok=True)
        if journal is not None:
            journal.will_create(output)

        included = sorted(_walk_includes(project_dir))

        tempfile_path = _tempfile_sibling(output)
        started = time.monotonic()
        try:
            _write_source_zip(
                tempfile_path,
                project_dir=project_dir,
                included=included,
            )
        except BaseException:
            tempfile_path.unlink(missing_ok=True)
            raise
        elapsed = time.monotonic() - started

        os.replace(tempfile_path, output)

        return ExportResult(
            path=output,
            command=None,
            elapsed_seconds=elapsed,
        )


# ===== include/exclude walker =====


def _walk_includes(project_dir: Path) -> Iterable[Path]:
    """Yield project files to include, respecting the documented rules."""
    for root, dirs, files in os.walk(project_dir):
        root_path = Path(root)
        # Prune excluded subdirectories in-place so os.walk doesn't descend.
        dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIR_NAMES]
        for name in files:
            path = root_path / name
            if _is_included(path):
                yield path


def _is_included(path: Path) -> bool:
    """Return ``True`` when *path* matches an include rule and no exclude rule."""
    name = path.name
    if name in _EXCLUDE_EXACT_NAMES:
        return False
    if path.suffix in _EXCLUDE_SUFFIXES:
        return False
    for pattern in _EXCLUDE_PATTERNS:
        if pattern.match(name):
            return False

    if path.suffix in _INCLUDE_SUFFIXES:
        return True
    if name in _INCLUDE_FILENAMES:
        return True
    # LICENSE / LICENSE.txt / LICENSE.md all qualify.
    return path.stem in _INCLUDE_FILENAME_STEMS


# ===== zip assembly =====


def _write_source_zip(
    output: Path,
    *,
    project_dir: Path,
    included: list[Path],
) -> None:
    """Write the source zip at *output*.

    Project files are stored under their paths relative to
    *project_dir* so the archive opens directly in KiCad.
    """
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in included:
            arcname = str(path.relative_to(project_dir))
            zf.write(path, arcname=arcname)


def _tempfile_sibling(output: Path) -> Path:
    """Sibling tempfile path preserving *output*'s suffix.

    Mirrors :func:`kproj.services.pcb_exporter._tempfile_sibling`.
    """
    token = uuid.uuid4().hex[:8]
    return output.with_name(f".{output.stem}.{token}.part{output.suffix}")
