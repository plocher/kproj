"""Smoke tests confirming all three formatter implementations are live.

The foundation-slice stubs were replaced by real implementations in
kproj#4.  These smoke tests confirm the public API is importable and
callable; deeper behavioural coverage lives in the dedicated
``test_stderr_formatter.py``, ``test_markdown_table_formatter.py``, and
``test_front_matter_summary_formatter.py`` modules.
"""

from __future__ import annotations

from kproj.formatters.front_matter_summary_formatter import FrontMatterSummaryFormatter
from kproj.formatters.markdown_table_formatter import MarkdownTableFormatter
from kproj.formatters.stderr_formatter import StderrFormatter
from kproj.model.analysis_info import AnalysisInfo


def test_stderr_formatter_callable() -> None:
    """:class:`StderrFormatter` is importable and callable."""
    result = StderrFormatter().format_findings([])
    assert result == ""


def test_markdown_table_formatter_callable() -> None:
    """:class:`MarkdownTableFormatter` is importable and callable."""
    result = MarkdownTableFormatter().render([])
    assert isinstance(result, str)


def test_front_matter_summary_formatter_render_audit_callable() -> None:
    """:class:`FrontMatterSummaryFormatter.render_audit` is importable and callable."""
    counts = FrontMatterSummaryFormatter().render_audit(AnalysisInfo(findings=()))
    assert counts["errors"] == 0
    assert counts["warnings"] == 0
