"""kproj output formatters (stderr / Markdown table / front-matter summary).

Foundation-slice stubs; the real implementations land in subsequent
issues. Exported here so :class:`PublishWorkflow` can depend on a stable
import surface.
"""

from __future__ import annotations

from .front_matter_summary_formatter import FrontMatterSummaryFormatter
from .markdown_table_formatter import MarkdownTableFormatter
from .stderr_formatter import StderrFormatter

__all__ = [
    "FrontMatterSummaryFormatter",
    "MarkdownTableFormatter",
    "StderrFormatter",
]
