"""Stub :class:`MarkdownTableFormatter` (docs/DESIGN.md § Front-matter shape)."""

from __future__ import annotations

from collections.abc import Sequence

from ..model.finding import Finding


class MarkdownTableFormatter:
    """Renders :class:`Finding` lists as Markdown tables (stub)."""

    def __init__(self) -> None:
        """Construct a markdown-table formatter."""

    def render(self, findings: Sequence[Finding]) -> str:
        """Render *findings* as a Markdown table.

        Raises:
            NotImplementedError: Always, in the foundation slice.
        """
        raise NotImplementedError(
            "MarkdownTableFormatter.render is not implemented in the foundation slice."
        )
