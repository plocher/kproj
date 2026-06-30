"""The :class:`PublishResult` value object + :func:`compute_exit_code`.

Lives in ``model/`` so both the application workflow (which constructs
results) and the CLI (which maps them to process exit codes) share a
single source of truth.  This addresses the wave-1 carry-forward note
that the ``PublishResult.exit_code`` field was previously dead because
``cli.py`` re-derived the code from outcome + findings independently.

Going forward the workflow MUST populate ``exit_code`` authoritatively
via :func:`compute_exit_code` (or its convenience wrapper
:meth:`PublishResult.with_computed_exit_code`) and the CLI MAY simply
read ``result.exit_code`` - they agree by construction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .finding import Finding
from .severity import Severity

Outcome = Literal["published", "refreshed", "noop", "private-skip", "failed"]
"""Closed set of v1 ``PublishWorkflow`` outcomes per docs/DESIGN.md."""

_TERMINAL_SUCCESS_OUTCOMES: frozenset[str] = frozenset(
    {"published", "refreshed", "noop", "private-skip"}
)
"""Outcomes that signify the workflow completed without mechanical failure."""

_FINDING_SEVERITIES: frozenset[Severity] = frozenset({Severity.ERROR, Severity.WARNING})
"""Severities that contribute to the ``exit_code=1`` "findings present" rule.

``Severity.EXCLUSION`` is intentionally excluded - KiCad treats
exclusions as the developer's promise to suppress an otherwise-noisy
finding, per the locked foundation behaviour.
"""


def compute_exit_code(outcome: Outcome, findings: Sequence[Finding]) -> int:
    """Return the process exit code for *outcome* + *findings*.

    Implements ``docs/DESIGN.md`` § *Exit code mapping*:

    - ``0`` - terminal-success outcome AND no error/warning findings.
    - ``1`` - terminal-success outcome AND at least one error or warning
      finding.  Exclusions never escalate to exit 1.
    - ``2`` - ``outcome == "failed"`` (mechanical failure).  Anything
      else outside the closed set is treated as ``2`` as well.

    Args:
        outcome: The workflow outcome literal.
        findings: All findings the workflow produced.

    Returns:
        The integer process exit code.
    """
    if outcome == "failed":
        return 2
    if outcome in _TERMINAL_SUCCESS_OUTCOMES:
        for finding in findings:
            if finding.severity in _FINDING_SEVERITIES:
                return 1
        return 0
    # Defensive default: an unknown outcome literal is treated as mechanical
    # failure.  The Literal type prevents this at type-check time; the
    # runtime branch exists so a stray cast or future-extension miss does
    # not slip through as a misleading exit 0.
    return 2


@dataclass(frozen=True)
class PublishResult:
    """Outcome of a ``PublishWorkflow.run`` invocation.

    Attributes:
        outcome: One of the values in :data:`Outcome`.
        exit_code: Process exit code per ``docs/DESIGN.md`` § *Exit
            code mapping*.  Populated authoritatively by the workflow
            via :func:`compute_exit_code` so the CLI can rely on it
            directly.
        message: Human-readable summary intended for stderr.
        findings: Findings emitted during the run.
        produced_paths: Paths the run wrote (or would have written in
            dry-run).  Stable for verbose-mode logging.
    """

    outcome: Outcome
    exit_code: int
    message: str = ""
    findings: tuple[Finding, ...] = field(default_factory=tuple)
    produced_paths: tuple[Path, ...] = field(default_factory=tuple)

    @classmethod
    def build(
        cls,
        outcome: Outcome,
        *,
        message: str = "",
        findings: Sequence[Finding] = (),
        produced_paths: Sequence[Path] = (),
    ) -> PublishResult:
        """Construct a :class:`PublishResult` with the canonical exit code.

        This is the **only** way callers (workflow + tests) should
        construct a result that needs a derived exit code; constructing
        the dataclass directly with an arbitrary ``exit_code`` is
        reserved for explicit "mechanical failure with a specific code"
        cases such as pre-flight pathways that have not yet collected
        findings.

        Args:
            outcome: Workflow outcome literal.
            message: Optional stderr-ready summary.
            findings: Optional findings sequence.
            produced_paths: Optional produced-path sequence.

        Returns:
            A new :class:`PublishResult` whose ``exit_code`` matches
            :func:`compute_exit_code` for the given outcome + findings.
        """
        return cls(
            outcome=outcome,
            exit_code=compute_exit_code(outcome, findings),
            message=message,
            findings=tuple(findings),
            produced_paths=tuple(produced_paths),
        )
