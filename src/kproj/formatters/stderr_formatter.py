"""The :class:`StderrFormatter`.

Per ``docs/DESIGN.md`` § *Verbosity* and ADR 0004 (§ *What
"surfaced" means*), every :class:`Finding` is rendered as a
human-readable one-liner on stderr.

Verbose format (``verbose_level >= 1``, used with ``-v``)::

    <severity> [<field>] <project>: <reason>

The ``<project>:`` qualifier is omitted when :attr:`Finding.project`
is empty.  The field appears once in the ``[<field>]`` bracket only;
``(value: …)`` is omitted because the value is typically embedded in
the reason text already.

Compact format (``verbose_level == 0``, default)::

    <Severity>: <reason>
"""

from __future__ import annotations

from collections.abc import Sequence

from ..model.finding import Finding


class StderrFormatter:
    """Renders :class:`Finding` objects to stderr-ready text.

    One finding per line.

    Verbose (``verbose_level >= 1``)::

        <severity> [<field>] <project>: <reason>

    Compact (``verbose_level == 0``)::

        <Severity>: <reason>
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

    def _format_one(self, finding: Finding) -> str:
        """Format a finding in the human or verbose-machine presentation."""
        if self._verbose_level == 0:
            prefix = (
                "Note"
                if finding.severity.value in {"info", "exclusion"}
                else finding.severity.value.title()
            )
            return f"{prefix}: {finding.reason}"
        # Verbose: [field] appears once; project qualifies the subject;
        # (value: …) is omitted because the value is embedded in the reason.
        sev = finding.severity.value.lower()
        field = finding.field
        subject = f"{finding.project}: " if finding.project else ""
        return f"{sev} [{field}] {subject}{finding.reason}"
