"""Stub :class:`SourcePackager` (docs/DESIGN.md § SourcePackager)."""

from __future__ import annotations

from pathlib import Path

from ..model.export_result import ExportResult
from .zip_archiver import ZipArchiver


class SourcePackager:
    """Assembles ``<P>-<R>.source.zip`` from non-derived KiCad files (stub)."""

    def __init__(self, zip_archiver: ZipArchiver) -> None:
        """Construct a source packager.

        Args:
            zip_archiver: The shared :class:`ZipArchiver` instance.
        """
        self._zip_archiver = zip_archiver

    def package(self, project_dir: Path, output: Path) -> ExportResult:
        """Assemble the source.zip from *project_dir*.

        Raises:
            NotImplementedError: Always, in the foundation slice.
        """
        raise NotImplementedError(
            "SourcePackager.package is not implemented in the foundation slice; "
            "see docs/DESIGN.md § SourcePackager."
        )
