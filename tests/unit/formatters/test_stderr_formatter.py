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


def test_default_mode_uses_human_warning_prefix() -> None:
    """Default stderr is human-oriented and omits machine finding fields."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(severity=Severity.WARNING, reason="warn")])
    assert result == "Warning: warn"
    assert "test_rule" not in result


def test_default_mode_uses_human_error_prefix() -> None:
    """Errors use the standard console prefix."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(severity=Severity.ERROR, reason="err")])
    assert result == "Error: err"


def test_verbose_mode_retains_machine_finding_context() -> None:
    """Finding codes and values remain available under ``-v``."""
    fmt = StderrFormatter(verbose_level=1)
    result = fmt.format_findings([_f(field="comment9_missing", reason="r")])
    assert "comment9_missing" in result


def test_reason_included() -> None:
    """The human-readable reason appears in the output."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(reason="COMMENT9 is absent")])
    assert "COMMENT9 is absent" in result


def test_default_mode_omits_value_and_project_context() -> None:
    """The normal human view does not repeat raw diagnostic metadata."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(value="BAD_VALUE", project="Demo", reason="r")])
    assert result == "Warning: r"


def test_value_omitted_when_empty() -> None:
    """An empty value does NOT emit a ``(value: …)`` segment."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(value="", reason="r")])
    assert "(value:" not in result


def test_project_omitted_in_default_human_mode() -> None:
    """Default stderr does not repeat the known current project path."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(project="MyProject", reason="r")])
    assert result == "Warning: r"


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
    """EXCLUSION severity is a note in the human view."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(severity=Severity.EXCLUSION, reason="exc")])
    assert result == "Note: exc"


def test_info_severity_renders_as_note() -> None:
    """Environment diagnostics use a non-escalating ``Note:`` prefix."""
    fmt = StderrFormatter()
    result = fmt.format_findings([_f(severity=Severity.INFO, reason="info")])
    assert result == "Note: info"
