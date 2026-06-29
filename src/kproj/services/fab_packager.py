"""Stub :class:`FabPackager` (docs/DESIGN.md § FabPackager)."""

from __future__ import annotations

from pathlib import Path

from ..model.export_result import ExportResult
from .zip_archiver import ZipArchiver


class FabPackager:
    """Assembles ``<P>-<R>.fab.zip`` from ``<project_dir>/production/`` (stub)."""

    def __init__(self, zip_archiver: ZipArchiver) -> None:
        """Construct a fab packager.

        Args:
            zip_archiver: The shared :class:`ZipArchiver` instance.
        """
        self._zip_archiver = zip_archiver

    def package(self, production_dir: Path, output: Path) -> ExportResult:
        """Assemble the fab.zip from *production_dir*.

        Raises:
            NotImplementedError: Always, in the foundation slice.
        """
        raise NotImplementedError(
            "FabPackager.package is not implemented in the foundation slice; "
            "see docs/DESIGN.md § FabPackager."
        )
