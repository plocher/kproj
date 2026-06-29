"""Stub :class:`StderrFormatter` (docs/DESIGN.md § Verbosity)."""

from __future__ import annotations

from collections.abc import Sequence

from ..model.finding import Finding


class StderrFormatter:
    """Renders :class:`Finding` objects to stderr-ready text (stub)."""

    def __init__(self, *, verbose_level: int = 0) -> None:
        """Construct a stderr formatter.

        Args:
            verbose_level: 0 = quiet, 1 = ``-v``, 2 = ``-v -d``.
        """
        self._verbose_level = verbose_level

    def format_findings(self, findings: Sequence[Finding]) -> str:
        """Render *findings* as a stderr-ready string.

        Raises:
            NotImplementedError: Always, in the foundation slice.
        """
        raise NotImplementedError(
            "StderrFormatter.format_findings is not implemented in the foundation slice."
        )
