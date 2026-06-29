"""The :class:`PublishWorkflow` orchestrator (foundation walking-skeleton).

Per ``docs/DESIGN.md`` § *Pipeline orchestration sequence*,
:class:`PublishWorkflow` drives the publish pipeline end-to-end. The
foundation slice implements only the *pre-flight* portion (project
resolution + ``kicad-cli`` discovery + major-version check) and stubs
the downstream steps with ``PublishResult(outcome="failed",
exit_code=2)`` per the issue's walking-skeleton scope.

This module also owns the :class:`PublishRequest` / :class:`PublishResult`
value objects so that :mod:`kproj.cli` has a stable downstream contract
even before the full pipeline lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..config import KprojConfig
from ..model.finding import Finding

Outcome = Literal["published", "refreshed", "noop", "private-skip", "failed"]
"""Closed set of v1 PublishWorkflow outcomes per docs/DESIGN.md."""


@dataclass(frozen=True)
class PublishRequest:
    """Inputs for one :meth:`PublishWorkflow.run` invocation.

    Attributes:
        project_arg: CLI positional — path to a ``.kicad_pro`` / dir /
            basename / ``"."``. Resolved by ``KicadProjectReader.resolve``.
        config: Effective configuration after the precedence chain
            (``cli > env > yaml > default``).
        dry_run: ``True`` enables read-only mode (no writes, no git ops).
        verbose_level: 0 = quiet, 1 = ``-v``, 2 = ``-v -d``.
        debug: ``True`` enables implementation-private debug output;
            independent of :attr:`verbose_level`.
    """

    project_arg: str
    config: KprojConfig
    dry_run: bool = False
    verbose_level: int = 0
    debug: bool = False


@dataclass(frozen=True)
class PublishResult:
    """Outcome of a :meth:`PublishWorkflow.run` invocation.

    Attributes:
        outcome: One of the values in :data:`Outcome`.
        exit_code: Process exit code per ``docs/DESIGN.md`` § *Exit
            code mapping* — 0 / 1 / 2.
        message: Human-readable summary intended for stderr.
        findings: Findings emitted during the run (used by the
            front-matter summary + exit-code-1 detection).
        produced_paths: Paths the run wrote (or would have written
            in dry-run). Stable for verbose-mode logging.
    """

    outcome: Outcome
    exit_code: int
    message: str = ""
    findings: tuple[Finding, ...] = field(default_factory=tuple)
    produced_paths: tuple[Path, ...] = field(default_factory=tuple)


class PublishWorkflow:
    """Walking-skeleton publish pipeline orchestrator.

    The full implementation per ``docs/DESIGN.md`` § *Pipeline
    orchestration sequence* is built up across subsequent issues. The
    foundation slice (this commit) executes only pre-flight — project
    resolution + ``kicad-cli`` discovery + version check — and returns
    ``PublishResult(outcome="failed", exit_code=2)`` for any
    downstream pipeline state.
    """

    def __init__(self) -> None:
        """Construct a workflow.

        Downstream slices will accept injected service factories here.
        """

    def run(self, request: PublishRequest) -> PublishResult:
        """Run the publish pipeline against *request*.

        Args:
            request: The bundled inputs (project arg + config + flags).

        Returns:
            A :class:`PublishResult` with the run's outcome + exit code.

        Notes:
            The foundation slice always returns
            ``PublishResult(outcome="failed", exit_code=2)`` with a
            ``NotImplementedError``-equivalent message. The real
            pre-flight + pipeline land in slice (i) of issue #1.
        """
        return PublishResult(
            outcome="failed",
            exit_code=2,
            message=(
                f"kproj: pipeline not yet implemented for {request.project_arg!r}; "
                "this is the foundation walking-skeleton."
            ),
        )
