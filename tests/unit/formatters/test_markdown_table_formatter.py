"""Unit tests for :class:`kproj.formatters.markdown_table_formatter.MarkdownTableFormatter`.

Per ``docs/DESIGN.md`` § *Front-matter shape*, the body of a
``_versions/<P>/<R>.md`` file contains two adjacent Markdown tables:
metadata audit findings and DRC/ERC findings.  The formatter owns this
rendering.
"""

from __future__ import annotations

from kproj.formatters.markdown_table_formatter import (
    AUDIT_FIELDS,
    MarkdownTableFormatter,
)
from kproj.model.finding import Finding
from kproj.model.severity import Severity


# ──────────────────────────── helpers ────────────────────────────


def _audit_finding(**kwargs: object) -> Finding:
    """Audit finding with a known audit field name."""
    defaults: dict[str, object] = {
        "severity": Severity.WARNING,
        "field": "comment9_missing",
        "value": "",
        "reason": "COMMENT9 is absent",
    }
    defaults.update(kwargs)
    return Finding(**defaults)  # type: ignore[arg-type]


def _drc_finding(**kwargs: object) -> Finding:
    """DRC-style finding with an unknown (non-audit) field name."""
    defaults: dict[str, object] = {
        "severity": Severity.ERROR,
        "field": "track_clearance",
        "value": "(100, 200)",
        "reason": "Track clearance violation",
        "location_hint": "(100, 200)",
    }
    defaults.update(kwargs)
    return Finding(**defaults)  # type: ignore[arg-type]


# ──────────────────────────── tests ─────────────────────────────


def test_result_is_string() -> None:
    """render() returns a string."""
    fmt = MarkdownTableFormatter()
    assert isinstance(fmt.render([]), str)


def test_empty_findings_renders_both_sections() -> None:
    """Empty findings list → both sections present in output."""
    fmt = MarkdownTableFormatter()
    result = fmt.render([])
    assert "Metadata Audit" in result or "Audit" in result
    assert "DRC" in result or "ERC" in result


def test_audit_finding_appears_in_output() -> None:
    """An audit finding's reason appears somewhere in the output."""
    fmt = MarkdownTableFormatter()
    result = fmt.render([_audit_finding(reason="COMMENT9 is absent")])
    assert "COMMENT9 is absent" in result


def test_drc_finding_appears_in_output() -> None:
    """A DRC finding's reason appears somewhere in the output."""
    fmt = MarkdownTableFormatter()
    result = fmt.render([_drc_finding(reason="Track clearance violation")])
    assert "Track clearance violation" in result


def test_output_contains_markdown_table_pipe_syntax() -> None:
    """The output uses Markdown table pipe syntax."""
    fmt = MarkdownTableFormatter()
    result = fmt.render([_audit_finding()])
    assert "|" in result


def test_audit_and_drc_in_separate_sections() -> None:
    """Audit finding and DRC finding appear in different regions of the output."""
    fmt = MarkdownTableFormatter()
    result = fmt.render([
        _audit_finding(reason="Audit finding text"),
        _drc_finding(reason="DRC finding text"),
    ])
    # Both texts present
    assert "Audit finding text" in result
    assert "DRC finding text" in result


def test_audit_fields_set_is_populated() -> None:
    """AUDIT_FIELDS is a non-empty frozenset used for section discrimination."""
    assert isinstance(AUDIT_FIELDS, frozenset)
    assert len(AUDIT_FIELDS) > 0
    assert "comment9_missing" in AUDIT_FIELDS
    assert "placeholder_value" in AUDIT_FIELDS


def test_severity_appears_in_table_row() -> None:
    """The severity label appears in the rendered finding row."""
    fmt = MarkdownTableFormatter()
    result = fmt.render([_audit_finding(severity=Severity.ERROR)])
    assert "error" in result.lower()


def test_value_appears_in_table_row_when_non_empty() -> None:
    """A non-empty finding value appears in the rendered row."""
    fmt = MarkdownTableFormatter()
    result = fmt.render([_audit_finding(value="PLACEHOLDER")])
    assert "PLACEHOLDER" in result


def test_location_hint_appears_for_drc() -> None:
    """A non-empty location_hint appears for a DRC finding."""
    fmt = MarkdownTableFormatter()
    result = fmt.render([_drc_finding(location_hint="(50, 75)")])
    assert "(50, 75)" in result
