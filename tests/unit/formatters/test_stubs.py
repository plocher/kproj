"""Smoke tests for the foundation-slice formatter stubs."""

from __future__ import annotations

import pytest

from kproj.formatters.front_matter_summary_formatter import FrontMatterSummaryFormatter
from kproj.formatters.markdown_table_formatter import MarkdownTableFormatter
from kproj.formatters.stderr_formatter import StderrFormatter
from kproj.model.analysis_info import AnalysisInfo


def test_stderr_formatter_stub_raises() -> None:
    """``StderrFormatter.format_findings`` is unimplemented in the foundation slice."""
    with pytest.raises(NotImplementedError):
        StderrFormatter().format_findings([])


def test_markdown_table_formatter_stub_raises() -> None:
    """``MarkdownTableFormatter.render`` is unimplemented in the foundation slice."""
    with pytest.raises(NotImplementedError):
        MarkdownTableFormatter().render([])


def test_front_matter_summary_formatter_stub_raises() -> None:
    """``FrontMatterSummaryFormatter.render_audit`` is unimplemented in the foundation slice."""
    with pytest.raises(NotImplementedError):
        FrontMatterSummaryFormatter().render_audit(AnalysisInfo(findings=()))
