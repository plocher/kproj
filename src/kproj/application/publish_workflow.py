"""The :class:`PublishWorkflow` orchestrator.

Per ``docs/DESIGN.md`` § *Pipeline orchestration sequence*,
:class:`PublishWorkflow` drives the publish pipeline end-to-end.  Wave-2
adds steps 2-4 (read + analyze + status detection) on top of the wave-1
pre-flight; downstream steps 5-11 remain stubbed.

:class:`PublishRequest` / :class:`PublishResult` were relocated to
:mod:`kproj.model.publish_request` / :mod:`kproj.model.publish_result`
in wave-2 (carry-forward decision) so services and the workflow share
the same dataclasses without TYPE_CHECKING gymnastics; this module
re-exports them for backward compatibility with existing call sites and
tests.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from pathlib import Path

from ..common.kicad_install import (
    KicadNotFoundError,
    find_kicad_cli,
    kicad_version,
)
from ..config import KprojConfig
from ..model.analysis_info import AnalysisInfo
from ..model.project_info import Status
from ..model.publish_request import PublishRequest
from ..model.publish_result import Outcome, PublishResult
from ..services.design_analyzer import DesignAnalyzer
from ..services.kicad_project_reader import (
    KicadProjectReader,
    ProjectResolutionError,
)
from ..services.metadata_analyzer import MetadataAnalyzer

_log = logging.getLogger(__name__)

_SUPPORTED_KICAD_MAJOR = 9
"""v1 enforces KiCad major version 9.x per docs/DESIGN.md § Pipeline orchestration."""

DesignAnalyzerFactory = Callable[[Path], DesignAnalyzer]
"""Callable used to construct a :class:`DesignAnalyzer` once kicad-cli is known.

A factory (rather than a pre-constructed instance) is taken so that
``kicad-cli`` discovery can run inside :meth:`PublishWorkflow.run` rather
than ahead of the workflow.  Tests inject a fake factory to avoid
invoking real subprocesses.
"""

__all__ = [
    "DesignAnalyzerFactory",
    "Outcome",
    "PublishRequest",
    "PublishResult",
    "PublishWorkflow",
]


class PublishWorkflow:
    """Publish-pipeline orchestrator (wave-2 read + analyze + status).

    Per ``docs/DESIGN.md`` § *Pipeline orchestration sequence* steps 1-4:

    1. Resolve the project via :class:`KicadProjectReader`.
    2. Discover the ``kicad-cli`` executable (config override or
       :func:`find_kicad_cli`) and verify its major version is 9.x.
    3. Read title-block metadata + apply per-field precedence.
    4. Run :class:`MetadataAnalyzer` (14-rule audit) and
       :class:`DesignAnalyzer` (DRC + ERC) and merge their findings
       into a single :class:`AnalysisInfo`.
    5. Status detection: ``status == "private"`` short-circuits with
       ``outcome="private-skip"`` BEFORE the iBOM / site-cleanliness
       pre-flight that wave-3 will add (per PRD Story 7).

    Downstream steps 5-11 (new-release detection, ChangeJournal scope,
    artifact generation, site writes, git push) remain stubbed in
    wave-2 and surface as ``outcome="failed"`` with a clear
    walking-skeleton message.

    The constructor accepts an optional :class:`KicadProjectReader`,
    :class:`MetadataAnalyzer`, and :class:`DesignAnalyzer` so tests
    can inject stand-ins without monkeypatching imports.
    """

    def __init__(
        self,
        *,
        project_reader: KicadProjectReader | None = None,
        metadata_analyzer: MetadataAnalyzer | None = None,
        design_analyzer_factory: DesignAnalyzerFactory | None = None,
    ) -> None:
        """Construct a workflow.

        Args:
            project_reader: Optional :class:`KicadProjectReader`.
                Defaults to a fresh instance using the SPCoast basename
                root ``~/Dropbox/KiCad/projects/``.
            metadata_analyzer: Optional :class:`MetadataAnalyzer` for
                test injection.  Defaults to a fresh instance.
            design_analyzer_factory: Callable returning a configured
                :class:`DesignAnalyzer` given a discovered ``kicad-cli``
                path.  Defaults to ``DesignAnalyzer``.  Tests may pass
                a callable that returns a fake to avoid invoking real
                kicad-cli.
        """
        self._project_reader = project_reader or KicadProjectReader()
        self._metadata_analyzer = metadata_analyzer or MetadataAnalyzer()
        self._design_analyzer_factory = design_analyzer_factory or DesignAnalyzer

    def run(self, request: PublishRequest) -> PublishResult:
        """Run the publish pipeline against *request*.

        Args:
            request: The bundled inputs (project arg + config + flags).

        Returns:
            A :class:`PublishResult` describing the run.  ``outcome`` is
            ``"private-skip"`` when the project is marked private,
            ``"failed"`` for any pre-flight failure or any path that
            reaches the wave-2 walking-skeleton boundary at step 5+.
            ``exit_code`` is populated via
            :func:`kproj.model.publish_result.compute_exit_code`.
        """
        try:
            resolved = self._project_reader.resolve(request.project_arg)
        except ProjectResolutionError as exc:
            return PublishResult.build(
                "failed",
                message=f"kproj: project resolution failed: {exc}",
            )

        try:
            kicad_cli = self._resolve_kicad_cli(request.config)
            major, minor, patch = kicad_version(kicad_cli)
        except KicadNotFoundError as exc:
            return PublishResult.build(
                "failed",
                message=f"kproj: {exc}",
            )

        if major != _SUPPORTED_KICAD_MAJOR:
            return PublishResult.build(
                "failed",
                message=(
                    f"kproj: unsupported kicad-cli version {major}.{minor}.{patch} "
                    f"at {kicad_cli} (kproj v1 requires major version {_SUPPORTED_KICAD_MAJOR}.x)."
                ),
            )

        print(
            f"kproj: kicad-cli {major}.{minor}.{patch} at {kicad_cli}",
            file=sys.stderr,
        )

        # Steps 2-3: read project metadata, then merge metadata + DRC/ERC findings.
        # The merged AnalysisInfo flows into status detection (step 4) and any
        # downstream PublishResult so the exit-code mapping sees them.
        project_info, read_findings = self._project_reader.read(resolved)
        metadata_analysis = self._metadata_analyzer.analyze(project_info, resolved.project_dir)
        design_analyzer = self._design_analyzer_factory(kicad_cli)
        design_analysis = design_analyzer.analyze(resolved)
        analysis = AnalysisInfo(
            findings=tuple(read_findings) + metadata_analysis.findings + design_analysis.findings
        )

        # Step 4: status detection - a private project must short-circuit BEFORE
        # the iBOM / site-cleanliness pre-flight that the wave-3 worker wires in.
        if project_info.status is Status.PRIVATE:
            return PublishResult.build(
                "private-skip",
                message=(
                    f"kproj: {resolved.basename!r} is status=private; "
                    "audit + DRC/ERC ran for stderr only, no site writes."
                ),
                findings=analysis.findings,
            )

        return PublishResult.build(
            "failed",
            message=(
                f"kproj: pre-flight + read + analyze succeeded for {resolved.basename!r}; "
                "the rest of the publish pipeline (steps 5\u201311) is not yet implemented."
            ),
            findings=analysis.findings,
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
