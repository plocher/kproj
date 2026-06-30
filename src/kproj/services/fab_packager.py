"""The :class:`FabPackager` service.

Per ``docs/DESIGN.md`` § *FabPackager* + ``docs/adr/0003-jbom-
separation-read-not-invoke.md``, kproj does NOT invoke jBOM. The
user runs ``jbom fab`` separately and jBOM writes a gerber pack + a
``bom.csv`` + a ``pos.csv`` into ``<project_dir>/production/``.
kproj's job is to read those existing files and assemble a tidy
``<P>-<R>.fab.zip`` for the site download.

Discovery rules (per DESIGN):

1. Prefer ``<production_dir>/<title>_<rev>.zip`` when ``title`` +
   ``rev`` are supplied.
2. Otherwise: the single ``*.zip`` in ``production_dir``. Warn if
   zero or more than one.

The discovered gerber zip is added to the produced fab.zip under the
normalized entry name ``gerbers.zip`` (regardless of its source
filename), alongside ``bom.csv`` and ``pos.csv``.

Skipped semantics: ``ExportResult.skipped=True`` when ``production_dir``
is missing or empty (or when required pieces are missing such that
no valid fab.zip can be assembled). The publish continues without
this artifact per Story 1's note + ADR 0003.

Staleness warning: when the *youngest* file in ``production_dir`` is
older than ``pcb_path``'s mtime, the production outputs are flagged
as stale (user probably forgot to re-run ``jbom fab``). The fab.zip
is still assembled — the warning is surfaced for the audit table.
"""

from __future__ import annotations

import os
import time
import uuid
import zipfile
from pathlib import Path

from ..model.export_result import ExportResult
from ..model.finding import Finding
from ..model.severity import Severity
from .change_journal import ChangeJournal
from .zip_archiver import ZipArchiver

_REQUIRED_CSV_NAMES: tuple[str, ...] = ("bom.csv", "pos.csv")
_GERBER_ENTRY_NAME: str = "gerbers.zip"
"""Normalized entry name for the inner gerber pack inside ``<P>-<R>.fab.zip``."""


class FabPackager:
    """Read jBOM ``production/`` outputs and assemble ``<P>-<R>.fab.zip``."""

    def __init__(self, zip_archiver: ZipArchiver) -> None:
        """Construct a fab packager.

        Args:
            zip_archiver: The shared :class:`ZipArchiver` instance.
                FabPackager uses it as a low-level primitive but
                pre-assembles the zip directly (since the three entries
                have non-canonical names that ZipArchiver's
                root-relative naming cannot express).
        """
        self._zip_archiver = zip_archiver

    def package(
        self,
        production_dir: Path,
        output: Path,
        *,
        title: str,
        rev: str,
        pcb_path: Path,
        journal: ChangeJournal | None = None,
    ) -> ExportResult:
        """Assemble the fab.zip from *production_dir*.

        Args:
            production_dir: ``<project_dir>/production/`` as produced
                by jBOM (ADR 0003).
            output: Final ``<P>-<R>.fab.zip`` path.
            title: Project title (used to locate
                ``<title>_<rev>.zip``).
            rev: Board revision (used to locate
                ``<title>_<rev>.zip``).
            pcb_path: Path to ``<pcb>.kicad_pcb``. Used to compare
                mtimes for the staleness warning.
            journal: Optional open :class:`ChangeJournal`.

        Returns:
            A populated :class:`ExportResult`. ``skipped=True`` when
            ``production_dir`` is missing/empty or required pieces
            are absent.
        """
        diagnostics: list[Finding] = []

        if not production_dir.is_dir() or _is_empty(production_dir):
            diagnostics.append(
                Finding(
                    severity=Severity.WARNING,
                    field="production_missing",
                    value=str(production_dir),
                    reason=(
                        "production/ missing or empty; run `jbom fab` to populate it. "
                        "Publishing without fab.zip."
                    ),
                )
            )
            return ExportResult(
                path=None,
                diagnostics=tuple(diagnostics),
                command=None,
                skipped=True,
            )

        gerber, gerber_diagnostics, ambiguous = _discover_gerber_zip(
            production_dir, title=title, rev=rev
        )
        diagnostics.extend(gerber_diagnostics)
        if gerber is None or ambiguous:
            # Cannot safely assemble fab.zip; skip.
            return ExportResult(
                path=None,
                diagnostics=tuple(diagnostics),
                command=None,
                skipped=True,
            )

        # bom.csv + pos.csv are required for the fab.zip's documented contents.
        missing_csvs = [
            name for name in _REQUIRED_CSV_NAMES if not (production_dir / name).is_file()
        ]
        if missing_csvs:
            diagnostics.append(
                Finding(
                    severity=Severity.WARNING,
                    field="production_incomplete",
                    value=", ".join(missing_csvs),
                    reason=(
                        f"production/ missing {', '.join(missing_csvs)}; cannot assemble "
                        f"fab.zip. Re-run `jbom fab` to regenerate the BOM/POS outputs."
                    ),
                )
            )
            return ExportResult(
                path=None,
                diagnostics=tuple(diagnostics),
                command=None,
                skipped=True,
            )

        # Staleness check — youngest file in production_dir vs pcb mtime.
        if pcb_path.is_file():
            production_mtime = max(
                p.stat().st_mtime for p in production_dir.iterdir() if p.is_file()
            )
            if production_mtime < pcb_path.stat().st_mtime:
                diagnostics.append(
                    Finding(
                        severity=Severity.WARNING,
                        field="production_stale",
                        value=str(production_dir),
                        reason=(
                            "production/ outputs are older than the PCB; "
                            "re-run `jbom fab` to refresh."
                        ),
                    )
                )

        # Assemble the fab.zip atomically via a sibling tempfile.
        output.parent.mkdir(parents=True, exist_ok=True)
        if journal is not None:
            journal.will_create(output)

        tempfile_path = _tempfile_sibling(output)
        started = time.monotonic()
        try:
            with zipfile.ZipFile(tempfile_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.write(production_dir / "bom.csv", arcname="bom.csv")
                zf.write(production_dir / "pos.csv", arcname="pos.csv")
                zf.write(gerber, arcname=_GERBER_ENTRY_NAME)
        except BaseException:
            tempfile_path.unlink(missing_ok=True)
            raise
        elapsed = time.monotonic() - started

        os.replace(tempfile_path, output)

        return ExportResult(
            path=output,
            diagnostics=tuple(diagnostics),
            command=None,
            elapsed_seconds=elapsed,
        )


def _is_empty(directory: Path) -> bool:
    """Return ``True`` when *directory* has no entries at all."""
    return not any(directory.iterdir())


def _discover_gerber_zip(
    production_dir: Path,
    *,
    title: str,
    rev: str,
) -> tuple[Path | None, list[Finding], bool]:
    """Discover the gerber pack inside *production_dir*.

    Returns a tuple of:
    - The chosen gerber zip path, or ``None`` when none can be picked.
    - A list of diagnostic Findings (empty in the happy path).
    - A boolean indicating *ambiguous* selection (more than one
      candidate when ``<title>_<rev>.zip`` is absent).
    """
    canonical = production_dir / f"{title}_{rev}.zip"
    if canonical.is_file():
        return canonical, [], False

    candidates = sorted(production_dir.glob("*.zip"))
    if not candidates:
        return (
            None,
            [
                Finding(
                    severity=Severity.WARNING,
                    field="production_missing",
                    value=str(production_dir),
                    reason=("no gerber zip found in production/; run `jbom fab` to populate it."),
                )
            ],
            False,
        )
    if len(candidates) > 1:
        names = ", ".join(p.name for p in candidates)
        return (
            None,
            [
                Finding(
                    severity=Severity.WARNING,
                    field="fab_gerber_ambiguous",
                    value=names,
                    reason=(
                        f"multiple *.zip candidates in production/ "
                        f"and no canonical {title}_{rev}.zip; refusing to guess."
                    ),
                )
            ],
            True,
        )
    return candidates[0], [], False


def _tempfile_sibling(output: Path) -> Path:
    """Sibling tempfile path preserving *output*'s suffix.

    Mirrors :func:`kproj.services.pcb_exporter._tempfile_sibling`.
    """
    token = uuid.uuid4().hex[:8]
    return output.with_name(f".{output.stem}.{token}.part{output.suffix}")
