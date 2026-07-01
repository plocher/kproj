"""The :class:`ThumbnailGenerator` service.

Per ``docs/DESIGN.md`` § *Release asset set*, every published version
carries a ``<P>-<R>.thumbnail.png`` referenced by the front-matter
``image_path``. The list/card views on the site use it as the project's
representative image.

v1 (grey-scale) recipe: a **deterministic copy of the top render**
(``<P>-<R>.top.png``). This is intentionally the lowest-dependency
implementation that makes ``image_path`` resolve on the built site
without adding a runtime image library. A genuine scaled/cropped
thumbnail (via Pillow, or ``kicad-cli pcb render --width/--height``) is a
tracked follow-up; the seam here — a dedicated producer returning an
:class:`ExportResult` — means that upgrade is a one-method change with no
caller impact.

The write is atomic: the source is copied to a sibling tempfile and then
moved into place via :func:`os.replace`. When a :class:`ChangeJournal` is
supplied, the final path is registered so workflow-level rollback covers
it (ADR 0005).
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from pathlib import Path

from ..model.export_result import ExportResult
from .change_journal import ChangeJournal


class ThumbnailGenerator:
    """Produce a version's ``thumbnail.png`` from its top render.

    Pure-Python (no subprocess): the v1 recipe copies the top-side PNG
    verbatim. :attr:`ExportResult.command` is therefore ``None``.
    """

    def __init__(self) -> None:
        """Construct a thumbnail generator (no configuration in v1)."""

    def generate(
        self,
        source_png: Path,
        output: Path,
        *,
        journal: ChangeJournal | None = None,
    ) -> ExportResult:
        """Produce *output* as the version thumbnail from *source_png*.

        Args:
            source_png: The already-rendered top PNG to derive from.
            output: Final ``<P>-<R>.thumbnail.png`` path. Parent
                directories are created.
            journal: Optional open :class:`ChangeJournal`. When supplied,
                *output* is registered via
                :meth:`ChangeJournal.register_output` so workflow
                rollback covers this artifact.

        Returns:
            An :class:`ExportResult` with ``path=output`` and
            ``command=None`` (pure-Python producer).

        Raises:
            FileNotFoundError: When *source_png* does not exist (the
                workflow converts this into ``outcome="failed"``).
        """
        if not source_png.is_file():
            raise FileNotFoundError(
                f"thumbnail source render not found: {source_png}; "
                "expected the top PNG to be produced before the thumbnail."
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        if journal is not None:
            journal.register_output(output)

        tempfile_path = output.with_name(
            f".{output.stem}.{uuid.uuid4().hex[:8]}.part{output.suffix}"
        )
        started = time.monotonic()
        try:
            shutil.copyfile(source_png, tempfile_path)
            os.replace(tempfile_path, output)
        except BaseException:
            tempfile_path.unlink(missing_ok=True)
            raise
        elapsed = time.monotonic() - started

        return ExportResult(path=output, command=None, elapsed_seconds=elapsed)
