"""Unit tests for :class:`kproj.formatters.stderr_formatter.StderrFormatter`.

Per ``docs/DESIGN.md`` § *Verbosity* + ADR 0004, :class:`StderrFormatter`
renders :class:`Finding` objects to human-readable stderr text, one
finding per line:

    <severity> [<field>] <project>:<field>: <reason> (value: <value>)

The ``(value: …)`` segment is omitted when :attr:`Finding.value` is
empty. The ``<project>:`` prefix is omitted when
:attr:`Finding.project` is empty.
"""

from __future__ import annotations

from kproj.formatters.stderr_formatter import StderrFormatter
from kproj.model.finding import Finding
from kproj.model.severity import Severity


# ──────────────────────────── helpers ────────────────────────────


def _f(**kwargs: object) -> Finding:
    """Build a Finding with sane defaults; any field can be overridden."""
    defaults: dict[str, object] = {
        "severity": Severity.WARNING,
        "field": "test_rule",
        "value": "",
        "reason": "A test reason",
        "project": "",
        "location_hint": "",
    }
    defaults.update(kwargs)
    return Finding(**defaults)  # type: ignore[arg-type]


# ──────────────────────────── tests ─────────────────────────────


def test_empty_findings_returns_empty_string() -> None:
    """No findings → empty string."""
    fmt = StderrFormatter()
    assert fmt.format_findings([]) == ""


def test_single_warning_appears_on_one_line() -> None:
    """A single finding renders as one non-empty line."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(reason="Something broken")])
    lines = [ln for ln in result.splitlines() if ln.strip()]
    assert len(lines) == 1


def test_severity_label_present_warning() -> None:
    """WARNING severity label appears in the output."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(severity=Severity.WARNING, reason="warn")])
    assert "warning" in result.lower()


def test_severity_label_present_error() -> None:
    """ERROR severity label appears in the output."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(severity=Severity.ERROR, reason="err")])
    assert "error" in result.lower()


def test_field_name_included() -> None:
    """The rule/field name appears in the output."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(field="comment9_missing", reason="r")])
    assert "comment9_missing" in result


def test_reason_included() -> None:
    """The human-readable reason appears in the output."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(reason="COMMENT9 is absent")])
    assert "COMMENT9 is absent" in result


def test_value_included_when_non_empty() -> None:
    """A non-empty value appears in the output."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(value="BAD_VALUE", reason="r")])
    assert "BAD_VALUE" in result


def test_value_omitted_when_empty() -> None:
    """An empty value does NOT emit a ``(value: …)`` segment."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(value="", reason="r")])
    assert "(value:" not in result


def test_project_included_when_non_empty() -> None:
    """A non-empty project name appears in the output."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(project="MyProject", reason="r")])
    assert "MyProject" in result


def test_multiple_findings_one_per_line() -> None:
    """Multiple findings → one line per finding."""
    fmt = StderrFormatter()
    findings = [
        _f(reason="First finding"),
        _f(reason="Second finding"),
        _f(reason="Third finding"),
    ]
    result = fmt.format_findings(findings)
    lines = [ln for ln in result.splitlines() if ln.strip()]
    assert len(lines) == 3
    assert "First finding" in lines[0]
    assert "Second finding" in lines[1]
    assert "Third finding" in lines[2]


def test_exclusion_severity_renders() -> None:
    """EXCLUSION severity produces a line (not omitted)."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(severity=Severity.EXCLUSION, reason="exc")])
    assert result.strip()
