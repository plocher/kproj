"""Unit tests for :mod:`kproj.model.analysis_info`."""

from __future__ import annotations

import dataclasses

import pytest

from kproj.model.analysis_info import AnalysisInfo
from kproj.model.finding import Finding
from kproj.model.severity import Severity


def _finding(sev: Severity) -> Finding:
    return Finding(severity=sev, field="silk_overlap", value="", reason="test")


def test_analysis_info_is_frozen() -> None:
    """``AnalysisInfo`` is immutable."""
    info = AnalysisInfo(findings=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.findings = ()  # type: ignore[misc]


def test_analysis_info_counts_per_severity() -> None:
    """:meth:`AnalysisInfo.count` returns the number of findings per severity."""
    info = AnalysisInfo(
        findings=(
            _finding(Severity.ERROR),
            _finding(Severity.ERROR),
            _finding(Severity.WARNING),
            _finding(Severity.EXCLUSION),
        )
    )
    assert info.count(Severity.ERROR) == 2
    assert info.count(Severity.WARNING) == 1
    assert info.count(Severity.EXCLUSION) == 1


def test_analysis_info_has_findings_flag() -> None:
    """``has_findings`` is true iff at least one error or warning exists."""
    empty = AnalysisInfo(findings=())
    excl_only = AnalysisInfo(findings=(_finding(Severity.EXCLUSION),))
    warn = AnalysisInfo(findings=(_finding(Severity.WARNING),))
    assert empty.has_findings is False
    # exclusions are intentionally-suppressed: not "findings" for exit-code purposes
    assert excl_only.has_findings is False
    assert warn.has_findings is True


def test_analysis_info_merge_concatenates_findings() -> None:
    """:meth:`AnalysisInfo.merged_with` concatenates two AnalysisInfo objects."""
    a = AnalysisInfo(findings=(_finding(Severity.ERROR),))
    b = AnalysisInfo(findings=(_finding(Severity.WARNING), _finding(Severity.EXCLUSION)))
    merged = a.merged_with(b)
    assert len(merged.findings) == 3
    assert merged.count(Severity.ERROR) == 1
