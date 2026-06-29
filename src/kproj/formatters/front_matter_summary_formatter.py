"""Stub :class:`FrontMatterSummaryFormatter` (docs/DESIGN.md § Front-matter shape)."""

from __future__ import annotations

from ..model.analysis_info import AnalysisInfo


class FrontMatterSummaryFormatter:
    """Renders the ``audit:`` / ``drc:`` / ``erc:`` summary YAML (stub)."""

    def __init__(self) -> None:
        """Construct a front-matter summary formatter."""

    def render_audit(self, analysis_info: AnalysisInfo) -> dict[str, int]:
        """Render the ``audit:`` count summary.

        Raises:
            NotImplementedError: Always, in the foundation slice.
        """
        raise NotImplementedError(
            "FrontMatterSummaryFormatter.render_audit is not implemented in the foundation slice."
        )
