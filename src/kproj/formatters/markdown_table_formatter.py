"""The :class:`MarkdownTableFormatter`.

Per ``docs/DESIGN.md`` § *Front-matter shape*, the body of every
``_versions/<P>/<R>.md`` file contains two adjacent Markdown tables:

1. **Metadata Audit** — findings whose ``field`` is in
   :data:`AUDIT_FIELDS` (the closed set of audit-heuristic rule names
   from ``docs/DESIGN.md`` § *Audit heuristic list*).
2. **DRC / ERC Findings** — all remaining findings (KiCad violation
   types reported by ``kicad-cli pcb drc`` / ``sch erc``).

Both sections are always present, even when empty.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..model.finding import Finding

AUDIT_FIELDS: frozenset[str] = frozenset(
    {
        # Structural / file checks
        "kicad_sch_missing",
        "kicad_pcb_missing",
        # Title-block content rules
        "placeholder_value",
        "comment9_missing",
        "comment9_taxonomy",
        "sch_titleblock_empty",
        "pcb_titleblock_empty",
        "sch_pcb_disagree",
        "date_format",
        "designer_format",
        "rev_relation",
        "replaced_by_target_missing",
        # Production / fab rules
        "production_missing",
        "production_stale",
        "production_incomplete",
        "fab_gerber_ambiguous",
    }
)
"""Closed set of audit-heuristic field names from
``docs/DESIGN.md`` § *Audit heuristic list*.

Findings whose :attr:`Finding.field` is in this set are placed in
the **Metadata Audit** table; all others go into **DRC / ERC Findings**.
"""


class MarkdownTableFormatter:
    """Renders :class:`Finding` lists as Markdown tables.

    Produces two adjacent Markdown tables in the version-page body:
    one for metadata audit findings and one for DRC/ERC findings.
    """

    def __init__(self) -> None:
        """Construct a markdown-table formatter."""

    def render(self, findings: Sequence[Finding]) -> str:
        """Render *findings* as two adjacent Markdown tables.

        Section discrimination (wave-3 M3 fix-up):

        - DRC/ERC table: any finding whose :attr:`Finding.source` is
          ``"drc"`` or ``"erc"``.
        - Metadata Audit table: every other finding (covers ``audit``,
          ``read``, and legacy empty-source findings).  Legacy callers
          that did not set ``source`` but used a non-audit ``field``
          name still fall through to the audit table; the optional
          :data:`AUDIT_FIELDS` heuristic is preserved as a safety net
          for hand-shaped fixtures.

        Args:
            findings: The findings to render.  May be empty.

        Returns:
            A Markdown string with two sections: **Metadata Audit** and
            **DRC / ERC Findings**.  Both sections are always present;
            empty sections show an italicised "no findings" row.
        """
        audit: list[Finding] = []
        design: list[Finding] = []
        for f in findings:
            if f.source in {"drc", "erc"}:
                design.append(f)
            elif f.source in {"audit", "read"} or f.field in AUDIT_FIELDS:
                audit.append(f)
            else:
                # Default for legacy / hand-constructed findings: keep
                # the historical "unknown field name → design table"
                # behaviour from the pre-source contract so existing
                # test fixtures remain valid.
                design.append(f)

        audit_table = _render_audit_table(audit)
        drc_table = _render_drc_table(design)

        return audit_table + "\n\n" + drc_table


# ----- section renderers -----


def _render_audit_table(findings: Sequence[Finding]) -> str:
    """Render the metadata-audit section."""
    header = "## Metadata Audit"
    col_headers = "| Severity | Rule | Value | Reason |"
    separator = "|----------|------|-------|--------|"

    if not findings:
        return f"{header}\n\n{col_headers}\n{separator}\n| | | | _No metadata audit findings._ |"

    rows = [
        f"| {f.severity.value.lower()} "
        f"| {_escape_pipe(f.field)} "
        f"| {_escape_pipe(f.value)} "
        f"| {_escape_pipe(f.reason)} |"
        for f in findings
    ]
    return "\n".join([header, "", col_headers, separator, *rows])


def _render_drc_table(findings: Sequence[Finding]) -> str:
    """Render the DRC/ERC section.

    Wave-3 M3 fix-up: the Location column now renders
    :attr:`Finding.value` (the actual KiCad coordinate / uuid /
    sheet from kicad-cli) rather than :attr:`Finding.location_hint`
    (which previously held the ``"drc"`` / ``"erc"`` source token,
    showing the source in every Location cell).  A new Source column
    surfaces ``drc`` / ``erc`` from :attr:`Finding.source` for users
    who want to group violations by origin.
    """
    header = "## DRC / ERC Findings"
    col_headers = "| Severity | Source | Type | Location | Message |"
    separator = "|----------|--------|------|----------|----------|"

    if not findings:
        return f"{header}\n\n{col_headers}\n{separator}\n| | | | | _No DRC/ERC findings._ |"

    rows = [
        f"| {f.severity.value.lower()} "
        f"| {_escape_pipe(f.source)} "
        f"| {_escape_pipe(f.field)} "
        f"| {_escape_pipe(f.value or f.location_hint)} "
        f"| {_escape_pipe(f.reason)} |"
        for f in findings
    ]
    return "\n".join([header, "", col_headers, separator, *rows])


def _escape_pipe(text: str) -> str:
    """Escape ``|`` characters so they don't break the Markdown table."""
    return text.replace("|", "\\|")
