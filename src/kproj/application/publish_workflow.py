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

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ..common.kicad_install import (
    KicadNotFoundError,
    find_kicad_cli,
    kicad_version,
)
from ..config import KprojConfig
from ..model.finding import Finding
from ..services.kicad_project_reader import (
    KicadProjectReader,
    ProjectResolutionError,
)

_log = logging.getLogger(__name__)

_SUPPORTED_KICAD_MAJOR = 9
"""v1 enforces KiCad major version 9.x per docs/DESIGN.md § Pipeline orchestration."""

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

    The foundation slice executes the pre-flight portion of the
    pipeline described in ``docs/DESIGN.md`` § *Pipeline orchestration
    sequence*:

    1. Resolve the project via :class:`KicadProjectReader`.
    2. Discover the ``kicad-cli`` executable (config override or
       :func:`find_kicad_cli`) and verify its major version is 9.x.
    3. Print a one-line "kproj: kicad-cli <version> at <path>" to
       stderr for auditability.

    On any pre-flight failure the workflow returns
    ``PublishResult(outcome="failed", exit_code=2)`` with a clear
    stderr-ready message. On pre-flight success, the workflow also
    returns ``failed``/``2`` because the downstream services are still
    stubs; the message indicates the walking-skeleton state.

    Constructor accepts an optional :class:`KicadProjectReader` so
    tests can inject a stand-in without monkeypatching imports.
    """

    def __init__(self, *, project_reader: KicadProjectReader | None = None) -> None:
        """Construct a workflow.

        Args:
            project_reader: Optional custom :class:`KicadProjectReader`
                instance. Defaults to a fresh one with the SPCoast
                ``~/Dropbox/KiCad/projects/`` basename root.
        """
        self._project_reader = project_reader or KicadProjectReader()

    def run(self, request: PublishRequest) -> PublishResult:
        """Run the publish pipeline against *request*.

        Args:
            request: The bundled inputs (project arg + config + flags).

        Returns:
            A :class:`PublishResult` describing the run.

        Notes:
            Foundation-slice semantics: pre-flight is fully implemented;
            steps 2+ (read / analyze / export / publish) are stubbed.
        """
        try:
            resolved = self._project_reader.resolve(request.project_arg)
        except ProjectResolutionError as exc:
            return PublishResult(
                outcome="failed",
                exit_code=2,
                message=f"kproj: project resolution failed: {exc}",
            )

        try:
            kicad_cli = self._resolve_kicad_cli(request.config)
            major, minor, patch = kicad_version(kicad_cli)
        except KicadNotFoundError as exc:
            return PublishResult(
                outcome="failed",
                exit_code=2,
                message=f"kproj: {exc}",
            )

        if major != _SUPPORTED_KICAD_MAJOR:
            return PublishResult(
                outcome="failed",
                exit_code=2,
                message=(
                    f"kproj: unsupported kicad-cli version {major}.{minor}.{patch} "
                    f"at {kicad_cli} (kproj v1 requires major version {_SUPPORTED_KICAD_MAJOR}.x)."
                ),
            )

        print(
            f"kproj: kicad-cli {major}.{minor}.{patch} at {kicad_cli}",
            file=sys.stderr,
        )

        return PublishResult(
            outcome="failed",
            exit_code=2,
            message=(
                f"kproj: pre-flight succeeded for {resolved.basename!r}; the rest of "
                "the publish pipeline is not yet implemented (foundation walking-skeleton)."
            ),
        )

    @staticmethod
    def _resolve_kicad_cli(config: KprojConfig) -> Path:
        """Return the configured ``kicad-cli`` or probe via the locator."""
        if config.kicad_cli is not None:
            if not config.kicad_cli.exists():
                raise KicadNotFoundError(
                    f"configured kicad_cli={config.kicad_cli!r} does not exist."
                )
            return config.kicad_cli
        return find_kicad_cli()
