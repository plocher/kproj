"""The :class:`RawTitleBlock` value object.

A kproj-owned, frozen-dataclass mirror of jBOM's
:class:`jbom.common.types.TitleBlockMetadata`.  ``KicadProjectReader.read``
populates one of these for each side (SCH + PCB) on
:class:`ProjectInfo` so the audit layer can compare values without
re-reading the files and without leaking jBOM's types across the
service boundary (ADR 0006).

The dataclass is intentionally minimal: only the title-block fields the
audit semantics consume.  ``comments`` is a mapping rather than a fixed
tuple of nine slots so present-but-empty (``""``) and absent (key not
in the mapping) remain distinguishable - the same distinction jBOM
preserves on its own ``TitleBlockMetadata.comments``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

_EMPTY_COMMENTS: Mapping[int, str] = MappingProxyType({})
"""Sentinel mapping used as the default when no comments were parsed."""


@dataclass(frozen=True)
class RawTitleBlock:
    """Raw title-block values read from a single KiCad file (SCH or PCB).

    Attributes:
        title: ``(title "...")`` value; empty when absent.
        company: ``(company "...")`` value; empty when absent.
        revision: ``(rev "...")`` value; empty when absent.
        date: ``(date "...")`` value; empty when absent.
        comments: 1-based ``(comment N "...")`` map.  An absent
            ``${COMMENTN}`` is reflected by the key being missing from
            this mapping (NOT by an empty string).  An empty-but-present
            comment is reflected as ``N: ""``.
        present: ``True`` when the file contained a non-empty
            ``(title_block ...)`` stanza.  Drives the audit's
            ``sch_titleblock_empty`` / ``pcb_titleblock_empty`` rules
            even when all individual fields happen to be empty.
    """

    title: str = ""
    company: str = ""
    revision: str = ""
    date: str = ""
    comments: Mapping[int, str] = field(default_factory=lambda: _EMPTY_COMMENTS)
    present: bool = False

    @property
    def is_empty(self) -> bool:
        """Return ``True`` iff the title-block has no populated fields.

        Used by the ``*_titleblock_empty`` audit rules.  A title-block
        whose stanza was present but contained only empty values still
        reports as empty here - KiCad's GUI shows the same.
        """
        if any((self.title, self.company, self.revision, self.date)):
            return False
        return not any(value for value in self.comments.values())
