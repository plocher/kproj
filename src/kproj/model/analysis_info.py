"""The :class:`AnalysisInfo` value object.

Aggregates a tuple of :class:`Finding` objects produced by
``MetadataAnalyzer`` and/or ``DesignAnalyzer`` plus convenience helpers
for the front-matter summary + exit-code mapping.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .finding import Finding
from .severity import Severity


@dataclass(frozen=True)
class AnalysisInfo:
    """A collection of :class:`Finding`s for a single project.

    Attributes:
        findings: Immutable tuple of findings produced by upstream
            analyzers. Order is preserved (analyzers can opt to sort
            before constructing).
    """

    findings: tuple[Finding, ...] = field(default_factory=tuple)

    def count(self, severity: Severity) -> int:
        """Return the number of findings at *severity*.

        Args:
            severity: The severity level to count.

        Returns:
            The integer count of findings whose severity equals
            *severity*.
        """
        return sum(1 for f in self.findings if f.severity is severity)

    @property
    def has_findings(self) -> bool:
        """Return ``True`` iff at least one error or warning exists.

        Exclusions are intentionally suppressed by KiCad's GUI and do
        not contribute to the exit-code-1 "findings present" condition
        (``docs/DESIGN.md`` § *Exit code mapping*).
        """
        return any(f.severity in {Severity.ERROR, Severity.WARNING} for f in self.findings)

    def merged_with(self, other: AnalysisInfo) -> AnalysisInfo:
        """Return a new :class:`AnalysisInfo` concatenating both finding sets.

        Args:
            other: Another :class:`AnalysisInfo` to merge with.

        Returns:
            A fresh :class:`AnalysisInfo` whose ``findings`` is
            ``self.findings + other.findings`` (order preserved).
        """
        return AnalysisInfo(findings=self.findings + other.findings)
