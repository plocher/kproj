"""The :class:`ZipArchiver` low-level zip primitive.

Per ``docs/GLOSSARY.md`` § *ZipArchiver* this is the domain-agnostic
zip builder consumed by ``FabPackager`` and ``SourcePackager``. It
takes a list of source paths + an output path + a ``root`` (the
project directory) and produces a zip whose entries are named relative
to ``root``.

The service does **not** invoke a subprocess; the returned
:class:`ExportResult` therefore sets ``command=None``.
"""

from __future__ import annotations

import time
import zipfile
from collections.abc import Iterable
from pathlib import Path

from ..model.export_result import ExportResult


class ZipArchiver:
    """Domain-agnostic zip primitive.

    Methods:
        archive: Build a zip at ``output`` from a list of file or
            directory paths (paths inside directories are added
            recursively).
    """

    def __init__(self) -> None:
        """Construct a :class:`ZipArchiver`.

        No constructor configuration in v1; subclasses or callers can
        be parameterised via :meth:`archive` arguments.
        """

    def archive(
        self,
        source_paths: Iterable[Path],
        output: Path,
        *,
        root: Path,
    ) -> ExportResult:
        """Build a zip file at *output* from *source_paths*.

        Args:
            source_paths: Iterable of files / directories to include.
                Directories are walked recursively. Every path must be
                at or beneath *root*.
            output: Destination zip file path. Parent directories are
                created if missing.
            root: Anchor directory; every archive entry is named
                relative to this path.

        Returns:
            An :class:`ExportResult` with ``path=output``,
            ``command=None``, ``skipped=False``, and
            ``elapsed_seconds`` populated.

        Raises:
            ValueError: When any *source_path* is outside *root*.
        """
        sources = [Path(p) for p in source_paths]
        for path in sources:
            self._validate(path, root)

        output.parent.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in sources:
                for file in self._walk_files(path):
                    arcname = file.relative_to(root)
                    zf.write(file, arcname=str(arcname))
        elapsed = time.monotonic() - started

        return ExportResult(
            path=output,
            command=None,
            elapsed_seconds=elapsed,
        )

    # ----- helpers -----
    @staticmethod
    def _validate(path: Path, root: Path) -> None:
        """Reject *path* if it is outside *root*."""
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"{path!r} is outside root {root!r}") from exc

    @staticmethod
    def _walk_files(path: Path) -> Iterable[Path]:
        """Yield every file at or beneath *path*.

        Directories are walked recursively; symlinks are followed only
        when they point at regular files (zipfile cannot represent
        directory symlinks safely).
        """
        if path.is_file():
            yield path
            return
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    yield child
