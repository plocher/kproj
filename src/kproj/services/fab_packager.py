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

Staleness: the ``production_stale`` heuristic (are the production/
outputs older than the PCB?) is owned by
``MetadataAnalyzer._production_rules`` — the single policy
implementation, including its happy-path mtime tolerance. FabPackager
deliberately emits no duplicate.
"""

from __future__ import annotations

import logging
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

_log = logging.getLogger(__name__)

_BOM_CANDIDATES: tuple[str, ...] = ("jbom.csv", "bom.csv")
"""Accepted BOM filenames in preference order.  ``jbom.csv`` is the modern
jbom convention; ``bom.csv`` is the older-toolchain fallback.  When both
exist we pick the one whose mtime is closest to the gerber zip (i.e. the
one jbom's current run produced alongside the gerbers)."""

_POS_CANDIDATES: tuple[str, ...] = ("cpl.csv", "pos.csv")
"""Accepted position-file names in preference order.  ``cpl.csv`` is the
modern name; ``pos.csv`` is the older-toolchain fallback.  Closest-mtime
tie-break as with BOM candidates."""

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
                    value="production/",
                    reason=(
                        "./production is missing or empty; run `jbom fab` to populate it. "
                        "Fabrication artifacts will not be published."
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

        # BOM + POS files are required for the fab.zip's documented contents.
        # Modern jbom writes jbom.csv + cpl.csv; older toolchains write
        # bom.csv + pos.csv.  When both variants coexist, prefer the one
        # whose mtime is closest to the gerber zip's mtime (same-tool batch).
        bom_path = _pick_by_mtime(production_dir, _BOM_CANDIDATES, gerber)
        pos_path = _pick_by_mtime(production_dir, _POS_CANDIDATES, gerber)
        missing_labels: list[str] = []
        if bom_path is None:
            missing_labels.append(_or_form(_BOM_CANDIDATES))
        if pos_path is None:
            missing_labels.append(_or_form(_POS_CANDIDATES))
        if missing_labels:
            diagnostics.append(
                Finding(
                    severity=Severity.WARNING,
                    field="production_incomplete",
                    value=", ".join(missing_labels),
                    reason=(
                        f"production/ missing {', '.join(missing_labels)}; cannot "
                        f"assemble fab.zip. Re-run `jbom fab` to regenerate the "
                        f"BOM/POS outputs."
                    ),
                )
            )
            return ExportResult(
                path=None,
                diagnostics=tuple(diagnostics),
                command=None,
                skipped=True,
            )
        assert bom_path is not None and pos_path is not None  # for type checker
        _log.debug(
            "fab.zip inputs: gerbers=%s bom=%s pos=%s",
            gerber.name,
            bom_path.name,
            pos_path.name,
        )

        # Assemble the fab.zip atomically via a sibling tempfile.
        output.parent.mkdir(parents=True, exist_ok=True)
        if journal is not None:
            # BLOCKER 3: pre-existing asset → will_modify so rollback
            # restores the prior bytes via git checkout.
            journal.register_output(output)

        tempfile_path = _tempfile_sibling(output)
        started = time.monotonic()
        try:
            with zipfile.ZipFile(tempfile_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                # Preserve the source basenames (jbom.csv vs bom.csv, cpl.csv
                # vs pos.csv) so consumers see which toolchain produced the
                # batch.  The gerber pack keeps the normalized entry name.
                zf.write(bom_path, arcname=bom_path.name)
                zf.write(pos_path, arcname=pos_path.name)
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


def _pick_by_mtime(
    production_dir: Path,
    candidates: tuple[str, ...],
    reference: Path,
) -> Path | None:
    """Return the candidate in *production_dir* closest in mtime to *reference*.

    Multiple candidates (jbom.csv + bom.csv; cpl.csv + pos.csv) can coexist
    when a maintainer has kept older-toolchain outputs alongside a fresh
    ``jbom fab`` batch.  Picking the file whose mtime is closest to the
    gerber zip's mtime selects the file jbom (or the older tool) produced
    in the SAME run as the gerbers - which is what fab.zip should ship.

    Args:
        production_dir: The project's ``production/`` directory.
        candidates: Accepted basenames in preference order.  When exactly
            one exists it is picked without consulting the mtime.
        reference: The gerber zip (or any anchor file) whose mtime the
            candidates are compared against.

    Returns:
        The chosen candidate path, or ``None`` when none exist.
    """
    present = [production_dir / name for name in candidates if (production_dir / name).is_file()]
    if not present:
        return None
    if len(present) == 1:
        return present[0]
    ref_mtime = reference.stat().st_mtime
    return min(present, key=lambda p: abs(p.stat().st_mtime - ref_mtime))


def _or_form(candidates: tuple[str, ...]) -> str:
    """Render *candidates* as ``a (or b, or c)`` for a diagnostic value."""
    if len(candidates) == 1:
        return candidates[0]
    head, *rest = candidates
    return f"{head} (or {', or '.join(rest)})"


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
                    value="production/",
                    reason="no gerber zip found in ./production; run `jbom fab` to populate it.",
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
