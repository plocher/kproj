"""The :class:`StderrFormatter`.

Per ``docs/DESIGN.md`` § *Verbosity* and ADR 0004 (§ *What
"surfaced" means*), every :class:`Finding` is rendered as a
human-readable one-liner on stderr:

    <severity> [<field>] <project>:<field>: <reason> (value: <value>)

The ``(value: …)`` segment is omitted when :attr:`Finding.value` is
empty.  The ``<project>:`` qualifier is omitted when
:attr:`Finding.project` is empty.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..model.finding import Finding


class StderrFormatter:
    """Renders :class:`Finding` objects to stderr-ready text.

    One finding per line.  Format per ADR 0004 § *What "surfaced" means*::

        <severity> [<field>] <project>:<field>: <reason> (value: <value>)

    The ``(value: …)`` trailing segment is suppressed when the finding's
    ``value`` attribute is empty.  The ``<project>:`` qualifier is
    suppressed when ``project`` is empty.
    """

    def __init__(self, *, verbose_level: int = 0) -> None:
        """Construct a stderr formatter.

        Args:
            verbose_level: 0 = default (findings only), 1 = ``-v``
                (adds subprocess + git command lines), 2 = ``-v -d``
                (adds implementation-private debug output).
        """
        self._verbose_level = verbose_level

    def format_findings(self, findings: Sequence[Finding]) -> str:
        """Render *findings* as a newline-separated stderr-ready string.

        Args:
            findings: The sequence of :class:`Finding` objects to render.

        Returns:
            A string with one line per finding; an empty string when
            *findings* is empty.
        """
        if not findings:
            return ""
        lines = [self._format_one(f) for f in findings]
        return "\n".join(lines)

    # ----- private helpers -----

    @staticmethod
    def _format_one(finding: Finding) -> str:
        """Format a single :class:`Finding` as a one-line stderr entry."""
        sev = finding.severity.value.lower()  # "warning", "error", "exclusion"
        field = finding.field

        # Build the subject portion: "<project>:<field>" or just "<field>"
        subject = f"{finding.project}:{field}" if finding.project else field

        # Optional value trailer
        value_part = f" (value: {finding.value})" if finding.value else ""

        return f"{sev} [{field}] {subject}: {finding.reason}{value_part}"
