"""The :class:`PcbExporter` service.

Per ``docs/DESIGN.md`` § *PcbExporter* + § *Release asset set*, this
service emits the two PCB-derived release artifacts:

- ``<P>-<R>.{top,bottom}.png`` via ``<kicad_cli> pcb render --side
  <side> --output <file> <pcb>``.
- ``<P>-<R>.step`` via ``<kicad_cli> pcb export step --output <file>
  <pcb>``.

Both writes are atomic: kicad-cli is directed at a sibling tempfile,
and the produced file is then atomically moved into the final
*output* via :func:`os.replace`. When a :class:`ChangeJournal` is
supplied, the final *output* path is registered with
:meth:`ChangeJournal.will_create` so workflow-level rollback covers
mid-pipeline failures (ADR 0005).
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from ..common.subprocess_runner import DEFAULT_KICAD_TIMEOUT
from ..common.subprocess_runner import run as subprocess_run
from ..model.export_result import ExportResult
from .change_journal import ChangeJournal

PcbSide = Literal["top", "bottom"]
"""The two PCB render sides supported in v1."""

_VALID_SIDES: frozenset[str] = frozenset({"top", "bottom"})

_CommandBuilder = Callable[[Path, Path], list[str]]
"""Builds the kicad-cli argv given (staging-output-path, source-pcb-path)."""


class PcbExporter:
    """PCB → PNG / STEP exporter.

    Methods:
        export_render: Render the PCB as a PNG for the given side.
        export_step: Export the PCB as a STEP 3D model.
    """

    def __init__(self, kicad_cli: Path) -> None:
        """Construct a PCB exporter.

        Args:
            kicad_cli: Path to the discovered ``kicad-cli`` executable
                (resolved by
                :func:`kproj.common.kicad_install.find_kicad_cli`).
        """
        self._kicad_cli = kicad_cli

    def export_render(
        self,
        pcb_path: Path,
        side: PcbSide,
        output: Path,
        *,
        journal: ChangeJournal | None = None,
    ) -> ExportResult:
        """Render the PCB as a PNG for *side*.

        Args:
            pcb_path: Path to the source ``.kicad_pcb``.
            side: ``"top"`` or ``"bottom"``.
            output: Final PNG path. Parent directories are created.
            journal: Optional open :class:`ChangeJournal`. When
                supplied, *output* is registered via
                :meth:`ChangeJournal.will_create` so workflow rollback
                covers this artifact.

        Returns:
            An :class:`ExportResult` populated with the invoked argv,
            elapsed time, and the final *output* path.

        Raises:
            ValueError: When *side* is not one of ``{"top", "bottom"}``.
            SubprocessFailedError: When kicad-cli exits non-zero.
            SubprocessTimeoutError: When kicad-cli exceeds the
                ``DEFAULT_KICAD_TIMEOUT``.
        """
        if side not in _VALID_SIDES:
            raise ValueError(f"side must be 'top' or 'bottom' (got {side!r})")
        return self._invoke_with_atomic_write(
            pcb_path=pcb_path,
            output=output,
            command_builder=self._render_command_for(side),
            journal=journal,
        )

    def export_step(
        self,
        pcb_path: Path,
        output: Path,
        *,
        journal: ChangeJournal | None = None,
    ) -> ExportResult:
        """Export the PCB as a STEP 3D model.

        Args:
            pcb_path: Path to the source ``.kicad_pcb``.
            output: Final STEP path. Parent directories are created.
            journal: Optional open :class:`ChangeJournal`.

        Returns:
            A populated :class:`ExportResult`.

        Raises:
            SubprocessFailedError: When kicad-cli exits non-zero.
            SubprocessTimeoutError: When kicad-cli exceeds the
                ``DEFAULT_KICAD_TIMEOUT``.
        """
        return self._invoke_with_atomic_write(
            pcb_path=pcb_path,
            output=output,
            command_builder=self._step_command,
            journal=journal,
        )

    # ----- helpers -----
    def _render_command_for(self, side: PcbSide) -> _CommandBuilder:
        """Return a builder that emits the ``pcb render`` argv for *side*."""

        def _build(cli_output: Path, pcb_path: Path) -> list[str]:
            return [
                str(self._kicad_cli),
                "pcb",
                "render",
                "--side",
                side,
                "--output",
                str(cli_output),
                str(pcb_path),
            ]

        return _build

    def _step_command(self, cli_output: Path, pcb_path: Path) -> list[str]:
        """Return the ``pcb export step`` argv."""
        return [
            str(self._kicad_cli),
            "pcb",
            "export",
            "step",
            "--force",
            "--output",
            str(cli_output),
            str(pcb_path),
        ]

    def _invoke_with_atomic_write(
        self,
        *,
        pcb_path: Path,
        output: Path,
        command_builder: _CommandBuilder,
        journal: ChangeJournal | None,
    ) -> ExportResult:
        """Run *command_builder* against a sibling tempfile and atomically replace.

        The journal (when supplied) is updated BEFORE the kicad-cli
        invocation so that even a kicad-cli failure leaves the journal
        able to roll back the planned-but-missing artifact path.
        """
        output.parent.mkdir(parents=True, exist_ok=True)
        if journal is not None:
            journal.will_create(output)

        tempfile_path = _tempfile_sibling(output)
        argv = command_builder(tempfile_path, pcb_path)
        started = time.monotonic()
        try:
            result = subprocess_run(argv, timeout=DEFAULT_KICAD_TIMEOUT, check=True)
        except BaseException:
            tempfile_path.unlink(missing_ok=True)
            raise
        elapsed = time.monotonic() - started

        os.replace(tempfile_path, output)

        return ExportResult(
            path=output,
            command=result.command,
            elapsed_seconds=elapsed,
        )


def _tempfile_sibling(output: Path) -> Path:
    """Return a unique sibling tempfile path for atomic-write staging.

    Using a sibling (same directory) ensures :func:`os.replace` is an
    atomic rename within a single filesystem; cross-filesystem replace
    is undefined. The original suffix is preserved on the tempfile so
    that tools that infer format from extension (e.g. ``kicad-cli pcb
    render``) still see a recognized extension.
    """
    token = uuid.uuid4().hex[:8]
    return output.with_name(f".{output.stem}.{token}.part{output.suffix}")
