"""Severity levels for kproj :class:`Finding` objects.

Per ``docs/GLOSSARY.md`` § *Severity*, the metadata audit itself uses
only ``error`` and ``warning``; DRC/ERC findings additionally use
``exclusion`` to preserve KiCad's GUI-marked exclusions.

The enum is intentionally orderable so callers can compare and rank
findings without lookup tables (e.g. ``max(f.severity for f in
findings)``).
"""

from __future__ import annotations

from enum import Enum
from functools import total_ordering


@total_ordering
class Severity(Enum):
    """Closed taxonomy of kproj finding severity levels.

    Ordering (most severe to least severe): ``ERROR > WARNING >
    EXCLUSION``. ``EXCLUSION`` represents a finding KiCad's GUI has
    marked as intentionally suppressed and ranks below ``WARNING`` so
    that ``max(...)`` over a mixed set returns the loudest level.
    """

    ERROR = "error"
    WARNING = "warning"
    EXCLUSION = "exclusion"

    def __lt__(self, other: object) -> bool:
        """Return ``True`` when *self* is less severe than *other*.

        Implemented as the inverse of the declaration order above so
        ``ERROR`` sorts highest.
        """
        if not isinstance(other, Severity):
            return NotImplemented
        order = (Severity.EXCLUSION, Severity.WARNING, Severity.ERROR)
        return order.index(self) < order.index(other)
