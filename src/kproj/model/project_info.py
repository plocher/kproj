"""Per-project metadata dataclass + lifecycle :class:`Status` enum.

The :class:`ProjectInfo` shape holds the point-in-time facts that
``KicadProjectReader`` extracts from a KiCad project's title block
(``${TITLE}``, ``${REVISION}``, ``${COMPANY}``, ``${ISSUE_DATE}``,
``${COMMENT1..9}``) plus any kproj-derived bookkeeping (tags, status,
fabrication state).

Per ``docs/GLOSSARY.md`` § *ProjectInfo* this is pure data: no I/O, no
Jekyll-specific rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(Enum):
    """A release's lifecycle attribute (closed taxonomy).

    Sourced from ``${COMMENT9}`` per ``docs/GLOSSARY.md`` § *status*.
    ``REPLACED_BY`` is parameterised — the actual target directory name
    lives in :attr:`ProjectInfo.replaced_by_target`.
    """

    EXPERIMENTAL = "experimental"
    ACTIVE = "active"
    RETIRED = "retired"
    BROKEN = "broken"
    REPLACED_BY = "replaced-by"
    PRIVATE = "private"


@dataclass(frozen=True)
class ProjectInfo:
    """Facts about a project at a point in time.

    Attributes:
        project: Project basename (matches ``.kicad_pro`` filename
            stem; never the directory name when those differ).
        title: PCB-canonical title (falls back to SCH per the
            per-field precedence in ``docs/DESIGN.md`` § *Metadata
            precedence*).
        company: PCB-canonical company; SCH fallback.
        design_rev: SCH ``${REVISION}`` (the ``<DESIGN>`` form, e.g.
            ``3.0``).
        board_rev: PCB ``${REVISION}`` (the ``<DESIGN><LETTER>`` form,
            e.g. ``3.0B``).
        date: PCB title-block date in ``YYYY.MM`` form.
        designer: Comment-1 (per SPCoast convention).
        tagline: Comment-2 (SCH-canonical, PCB fallback).
        overview: Comment-2 ⨁ Comment-3 (SCH-canonical, PCB fallback).
        status: Lifecycle status from Comment-9 (SCH-canonical).
        fabricated: ``True`` when this snapshot represents a board that
            has been physically fabricated.
        fab_date: Optional explicit fabrication date (``YYYY-MM``);
            defaults to title-block date when empty.
        replaced_by_target: When ``status == REPLACED_BY``, the
            successor project directory name; ``None`` otherwise.
        tags: Tag set kproj will emit into front-matter ``tags:``.
    """

    project: str
    title: str
    company: str
    design_rev: str
    board_rev: str
    date: str
    designer: str
    tagline: str
    overview: str
    status: Status
    fabricated: bool = False
    fab_date: str = ""
    replaced_by_target: str | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
