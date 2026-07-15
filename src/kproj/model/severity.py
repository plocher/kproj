"""Severity levels for kproj :class:`Finding` objects.

The metadata audit itself uses only ``error`` and ``warning``; DRC/ERC
findings additionally use ``exclusion`` to preserve KiCad's GUI-marked
exclusions.

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
    EXCLUSION > INFO``. ``INFO`` describes exit-neutral environment
    diagnostics.
    """

    ERROR = "error"
    WARNING = "warning"
    EXCLUSION = "exclusion"
    INFO = "info"

    def __lt__(self, other: object) -> bool:
        """Return ``True`` when *self* is less severe than *other*.

        Implemented as the inverse of the declaration order above so
        ``ERROR`` sorts highest.
        """
        if not isinstance(other, Severity):
            return NotImplemented
        order = (Severity.INFO, Severity.EXCLUSION, Severity.WARNING, Severity.ERROR)
        return order.index(self) < order.index(other)
