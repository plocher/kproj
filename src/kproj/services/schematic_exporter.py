"""The :class:`SchematicExporter` service.

Per ``docs/DESIGN.md`` § *SchematicExporter* + § *Release asset set*,
this service emits the two schematic-derived release artifacts:

- ``<P>-<R>.sch.svg`` via ``<kicad_cli> sch export svg --output
  <tempdir> --pages 1 <sch>``. The local kicad-cli treats
  ``--output`` here as an OUTPUT_DIR (one SVG per sheet), so this
  service uses a private temp directory + discover-and-move
  pattern: kicad-cli writes ``<sheet>.svg`` files into the temp
  directory, the service validates exactly one SVG was produced
  (root-only mode), and the file is atomically moved into the
  final *output_file* via :func:`os.replace`.
- ``<P>-<R>.sch.pdf`` via ``<kicad_cli> sch export pdf --output
  <tempfile.pdf> <sch>``. PDF export's ``--output`` is an
  OUTPUT_FILE on the local kicad-cli build (KiCad 10.0.1; verified
  against ``kicad-cli sch export pdf --help`` during Phase 6
  contract verification), so the implementation directs kicad-cli
  at a sibling tempfile and then atomically replaces the final
  *output_file*.

When a :class:`ChangeJournal` is supplied, the final *output_file*
path is registered via :meth:`ChangeJournal.will_create` so
workflow-level rollback (ADR 0005) covers mid-pipeline failures.
"""

from __future__ import annotations

import os
import tempfile
import time
import uuid
from collections.abc import Iterable
from pathlib import Path

from ..common.subprocess_runner import DEFAULT_KICAD_TIMEOUT
from ..common.subprocess_runner import run as subprocess_run
from ..model.export_result import ExportResult
from .change_journal import ChangeJournal


class SchematicExportError(RuntimeError):
    """Raised when kicad-cli produces an unexpected output shape.

    Examples that trigger this:
    - ``sch export svg`` produced zero SVG files in the temp dir.
    - ``sch export svg --pages 1`` produced multiple SVGs when only
      the root sheet was expected.

    The workflow converts the exception into a ``Finding(severity=
    error, ...)`` and triggers ChangeJournal rollback per
    ``docs/DESIGN.md`` § *SchematicExporter*.
    """


class SchematicExporter:
    """Schematic → SVG / PDF exporter.

    Methods:
        export_svg: Export the schematic root sheet (or all sheets,
            with ``root_only=False``) as SVG.
        export_pdf: Export the full multi-sheet schematic as PDF.
    """

    def __init__(self, kicad_cli: Path) -> None:
        """Construct a schematic exporter.

        Args:
            kicad_cli: Path to the discovered ``kicad-cli`` executable
                (resolved by
                :func:`kproj.common.kicad_install.find_kicad_cli`).
        """
        self._kicad_cli = kicad_cli

    def export_svg(
        self,
        sch_path: Path,
        output_file: Path,
        *,
        root_only: bool = True,
        journal: ChangeJournal | None = None,
    ) -> ExportResult:
        """Export the schematic as SVG.

        Args:
            sch_path: Path to the root ``.kicad_sch``.
            output_file: Final SVG path. Parent directories are
                created on demand.
            root_only: When ``True`` (the v1 default), pass
                ``--pages 1`` so kicad-cli emits only the root
                sheet's SVG. When ``False``, all sheets are
                rendered and the first discovered SVG is moved into
                ``output_file`` (Phase 6+ deepening can refine this).
            journal: Optional open :class:`ChangeJournal`.

        Returns:
            A populated :class:`ExportResult`.

        Raises:
            SchematicExportError: When kicad-cli emits zero SVGs, or
                more than one SVG in ``root_only=True`` mode.
            SubprocessFailedError: When kicad-cli exits non-zero.
            SubprocessTimeoutError: When kicad-cli exceeds the
                ``DEFAULT_KICAD_TIMEOUT``.
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)
        if journal is not None:
            # BLOCKER 3: pre-existing asset → will_modify so rollback
            # restores the prior bytes via git checkout.
            journal.register_output(output_file)

        with tempfile.TemporaryDirectory(prefix="kproj-svg-") as tmpdir:
            tempdir = Path(tmpdir)
            argv = [
                str(self._kicad_cli),
                "sch",
                "export",
                "svg",
                "--output",
                str(tempdir),
            ]
            if root_only:
                argv += ["--pages", "1"]
            argv.append(str(sch_path))

            started = time.monotonic()
            result = subprocess_run(argv, timeout=DEFAULT_KICAD_TIMEOUT, check=True)
            elapsed = time.monotonic() - started

            svgs = sorted(tempdir.glob("*.svg"))
            chosen = _select_root_svg(svgs, root_only=root_only)
            os.replace(chosen, output_file)

        return ExportResult(
            path=output_file,
            command=result.command,
            elapsed_seconds=elapsed,
        )

    def export_pdf(
        self,
        sch_path: Path,
        output_file: Path,
        *,
        all_sheets: bool = True,
        journal: ChangeJournal | None = None,
    ) -> ExportResult:
        """Export the schematic as PDF.

        Args:
            sch_path: Path to the root ``.kicad_sch``.
            output_file: Final PDF path.
            all_sheets: When ``True`` (the v1 default), the entire
                hierarchy is rendered into one multi-sheet PDF.
                ``False`` is currently ignored at this layer (v1
                always emits the full PDF as the download asset);
                kept on the signature for future selectability.
            journal: Optional open :class:`ChangeJournal`.

        Returns:
            A populated :class:`ExportResult`.

        Raises:
            SubprocessFailedError: When kicad-cli exits non-zero.
            SubprocessTimeoutError: When kicad-cli exceeds the
                ``DEFAULT_KICAD_TIMEOUT``.
        """
        del all_sheets  # full PDF is always emitted in v1
        output_file.parent.mkdir(parents=True, exist_ok=True)
        if journal is not None:
            # BLOCKER 3: pre-existing asset → will_modify so rollback
            # restores the prior bytes via git checkout.
            journal.register_output(output_file)

        tempfile_path = _tempfile_sibling(output_file)
        argv = [
            str(self._kicad_cli),
            "sch",
            "export",
            "pdf",
            "--output",
            str(tempfile_path),
            str(sch_path),
        ]
        started = time.monotonic()
        try:
            result = subprocess_run(argv, timeout=DEFAULT_KICAD_TIMEOUT, check=True)
        except BaseException:
            tempfile_path.unlink(missing_ok=True)
            raise
        elapsed = time.monotonic() - started

        os.replace(tempfile_path, output_file)

        return ExportResult(
            path=output_file,
            command=result.command,
            elapsed_seconds=elapsed,
        )


def _select_root_svg(svgs: Iterable[Path], *, root_only: bool) -> Path:
    """Validate the discovered SVG set and return the file to publish.

    Args:
        svgs: Sorted list of SVG paths produced by kicad-cli.
        root_only: When ``True``, exactly one SVG must have been
            produced. When ``False``, the first (alphabetically
            sorted) is treated as the root sheet.

    Returns:
        The chosen SVG path.

    Raises:
        SchematicExportError: When the discovered set is empty, or
            when it has more than one entry while ``root_only=True``.
    """
    svg_list = list(svgs)
    if not svg_list:
        raise SchematicExportError(
            "kicad-cli sch export svg produced no SVG files in the staging dir"
        )
    if root_only and len(svg_list) > 1:
        names = ", ".join(p.name for p in svg_list)
        raise SchematicExportError(
            f"kicad-cli sch export svg produced multiple SVG files in root-only mode: {names}"
        )
    return svg_list[0]


def _tempfile_sibling(output: Path) -> Path:
    """Return a unique sibling tempfile path preserving *output*'s suffix.

    Mirrors :func:`kproj.services.pcb_exporter._tempfile_sibling`; the
    suffix is preserved so kicad-cli's output-format inference (which
    keys on extension) still selects the right format.
    """
    token = uuid.uuid4().hex[:8]
    return output.with_name(f".{output.stem}.{token}.part{output.suffix}")
