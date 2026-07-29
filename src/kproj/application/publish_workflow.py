"""The :class:`PublishWorkflow` orchestrator.

Per ``docs/DESIGN.md`` § *Pipeline orchestration sequence*,
:class:`PublishWorkflow` drives the publish pipeline end-to-end.  Wave-4
(kproj#4) wires all 11 steps:

1. Project resolution + kicad-cli discovery + version check.
2. Read project metadata.
3. Analyze (MetadataAnalyzer + DesignAnalyzer).
4. Status detection (private-skip).
5. Remaining pre-flight: iBOM script location + site-repo cleanliness.
6. New-release detection (noop / refresh / publish).
7. Open :class:`ChangeJournal`.
8. Generate artifacts (PcbExporter / SchematicExporter / IbomGenerator /
   FabPackager / SourcePackager) — skipped on refresh/noop.
9. Build :class:`Publication`.
10. :meth:`SitePublisher.publish` — write + commit + push.
11. Close :class:`ChangeJournal` (via context-manager exit).

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
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone  # 3.10-compat; py3.11+ can use `datetime.UTC`
from pathlib import Path

import yaml

from .. import __version__ as KPROJ_VERSION
from ..common.datasheet_library import (
    build_datasheet_link,
    check_datasheet_links,
    jbom_tool_report,
    read_datasheet_names,
    read_ibom_rows,
)
from ..common.github_link import derive_github_link, detect_github_link, finding_for_detection
from ..common.install_info import detect_install_info, format_provenance
from ..common.kicad_install import (
    SUPPORTED_KICAD_MAJORS,
    KicadNotFoundError,
    find_ibom_script,
    find_kicad_cli,
    find_kicad_python,
    kicad_version,
)
from ..common.kicad_libraries import enumerate_libraries
from ..common.project_docs import read_description
from ..common.subprocess_runner import (
    DEFAULT_GIT_TIMEOUT,
    SubprocessFailedError,
    SubprocessTimeoutError,
)
from ..common.subprocess_runner import run as subprocess_run
from ..config import KprojConfig, SiteProfile
from ..formatters.markdown_table_formatter import MarkdownTableFormatter
from ..model.analysis_info import AnalysisInfo
from ..model.datasheet_link import DatasheetLink
from ..model.datasheet_row import DatasheetRow
from ..model.finding import Finding
from ..model.project_info import ProjectInfo, Status
from ..model.publication import AssetRef, Publication
from ..model.publish_request import PublishRequest
from ..model.publish_result import Outcome, PublishResult
from ..model.resolved_project import ResolvedProject
from ..model.severity import Severity
from ..services.change_journal import ChangeJournal
from ..services.design_analyzer import DesignAnalysisError, DesignAnalyzer
from ..services.fab_packager import FabPackager
from ..services.ibom_generator import IbomGenerator, write_ibom_user_files
from ..services.kicad_project_reader import (
    KicadProjectReader,
    ProjectResolutionError,
)
from ..services.metadata_analyzer import MetadataAnalyzer
from ..services.pcb_exporter import PcbExporter
from ..services.schematic_exporter import SchematicExporter, SchematicExportError
from ..services.site_publisher import SitePublisher
from ..services.source_packager import SourcePackager
from ..services.thumbnail_generator import ThumbnailGenerator
from ..services.zip_archiver import ZipArchiver

_log = logging.getLogger(__name__)

"""v1 supports KiCad 9.x and 10.x; the canonical set lives in
:data:`kproj.common.kicad_install.SUPPORTED_KICAD_MAJORS` so the
locator + workflow agree on which majors get probed AND accepted.
"""

DesignAnalyzerFactory = Callable[[Path], DesignAnalyzer]
"""Callable used to construct a :class:`DesignAnalyzer` once kicad-cli is known.

A factory (rather than a pre-constructed instance) is taken so that
``kicad-cli`` discovery can run inside :meth:`PublishWorkflow.run` rather
than ahead of the workflow.  Tests inject a fake factory to avoid
invoking real subprocesses.
"""

IbomScriptLocator = Callable[[], Path]
"""Callable that locates the iBOM ``generate_interactive_bom.py`` script.

Defaults to :func:`~kproj.common.kicad_install.find_ibom_script`. Tests
inject a fake that returns a dummy path so the iBOM pre-flight succeeds
without a real KiCad install.
"""

KicadPythonLocator = Callable[[], Path]
"""Callable that locates KiCad's bundled Python interpreter.

Defaults to :func:`~kproj.common.kicad_install.find_kicad_python`. The
iBOM script needs the interpreter that can ``import pcbnew`` (ADR 0008
amendment / kproj#10), so it is resolved in pre-flight alongside the
iBOM script and injected into :class:`~kproj.services.ibom_generator.IbomGenerator`.
Tests inject a fake returning a dummy path so pre-flight succeeds
without a real KiCad install.
"""

ArtifactGeneratorCallable = Callable[
    [
        "ResolvedProject",
        "ProjectInfo",
        Path,
        Path,
        Path,
        Path,
        SiteProfile,
        "Path | None",
        str,
        tuple[str, ...],
        "ChangeJournal",
    ],
    tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple["Finding", ...]],
]
"""Callable that generates all release artifacts for a project.

Signature::

    def generator(
        resolved: ResolvedProject,
        project_info: ProjectInfo,
        kicad_cli: Path,
        ibom_script: Path,
        kicad_python: Path,
        site_repo: Path,
        site_profile: SiteProfile,
        inventory: Path | None,
        fabricator: str,
        ibom_extra_fields: tuple[str, ...],
        journal: ChangeJournal,
    ) -> tuple[images_refs, artifact_refs, diagnostics]

``kicad_python`` is KiCad's bundled interpreter (ADR 0008 amendment /
kproj#10); it is passed to :class:`~kproj.services.ibom_generator.IbomGenerator`
so the iBOM script runs under the Python that has ``pcbnew``.

``site_profile`` supplies :attr:`~kproj.config.SiteProfile.assets_dir` so
asset files are written where the backend serves them (Hugo's
``static/versions/`` resolves at the public ``/versions/`` URL); the
public AssetRef paths stay ``/versions/...`` regardless of backend.

``inventory``, ``fabricator``, and ``ibom_extra_fields`` provide the
iBOM enrichment inputs (kproj#48): when inventory is configured, the
default generator queries jBOM for per-reference inventory fields with
the selected fabricator profile and projects them to iBOM's extra-data
XML format using the configured extra-field list.

``project_info`` carries the canonical ``board_rev`` (PCB-derived per
``docs/DESIGN.md`` § *Metadata precedence*) which the generator MUST
use for the on-disk asset directory layout and AssetRef paths.  The
project basename (``<P>``) and board revision (``<R>``) together form
the ``<P>-<R>`` token in every asset filename per ``docs/DESIGN.md``
§ *Release asset set*.

``diagnostics`` is the third-tuple element added in wave-3 (M6
fix-up): every :class:`ExportResult.diagnostics` from the invoked
producers is accumulated here so the workflow can merge them into
the final analysis (front-matter counts, Markdown body, stderr,
exit code).

The default implementation calls all real exporters + packagers.
Tests inject a stub that creates placeholder files and returns the
canonical asset refs without invoking any subprocesses.
"""

SitePublisherFactory = Callable[["ChangeJournal"], SitePublisher]
"""Callable that constructs a :class:`SitePublisher` given an open journal."""

DatasheetNameLookup = Callable[
    [Path, "Path | None", str],
    tuple[tuple[str, ...], tuple[Finding, ...]],
]
"""Callable that looks up distinct curated ``Datasheet Name`` values for a
project (kproj#29).

Signature: ``(project_dir, inventory, fabricator) -> (names, diagnostics)``.
Defaults to :func:`kproj.common.datasheet_library.read_datasheet_names`,
which invokes ``jbom bom`` live at publish time (ADR 0010). Tests inject
a fake returning canned names/findings so no real jBOM subprocess runs.
"""

__all__ = [
    "ArtifactGeneratorCallable",
    "DesignAnalyzerFactory",
    "IbomScriptLocator",
    "KicadPythonLocator",
    "Outcome",
    "PublishRequest",
    "PublishResult",
    "PublishWorkflow",
    "SitePublisherFactory",
]

_PUBLISH_CONTEXT_SCHEMA: int = 2
"""Schema version for ``kproj_publish_context`` front-matter metadata.

Bumped 1 -> 2 to add ``kproj_install_type`` + ``watermark`` (RCA
follow-up: distinguishing which kproj install/build produced a given
publish - see :mod:`kproj.common.install_info`). The bump means every
version page published under schema 1 is treated as drifted once and
regenerates on its next publish, picking up the new fields.
"""


class PublishWorkflow:
    """Publish-pipeline orchestrator (11 steps end-to-end, kproj#4).

    Per ``docs/DESIGN.md`` § *Pipeline orchestration sequence* all 11
    steps are now wired.  Each injectable factory defaults to the real
    production implementation; tests pass fakes to avoid subprocess
    invocations and git operations.
    """

    def __init__(
        self,
        *,
        project_reader: KicadProjectReader | None = None,
        metadata_analyzer: MetadataAnalyzer | None = None,
        design_analyzer_factory: DesignAnalyzerFactory | None = None,
        ibom_script_locator: IbomScriptLocator | None = None,
        kicad_python_locator: KicadPythonLocator | None = None,
        artifact_generator: ArtifactGeneratorCallable | None = None,
        site_publisher_factory: SitePublisherFactory | None = None,
        datasheet_name_lookup: DatasheetNameLookup | None = None,
        library_repo: Path | None = None,
    ) -> None:
        """Construct a workflow with optional injectable service factories.

        Args:
            project_reader: Optional :class:`KicadProjectReader`.
            metadata_analyzer: Optional :class:`MetadataAnalyzer`.
            design_analyzer_factory: Callable returning a configured
                :class:`DesignAnalyzer` for a given ``kicad-cli`` path.
            ibom_script_locator: Callable returning the iBOM script path.
                Defaults to :func:`~kproj.common.kicad_install.find_ibom_script`.
            kicad_python_locator: Callable returning KiCad's bundled
                Python interpreter path.  Defaults to
                :func:`~kproj.common.kicad_install.find_kicad_python`.
            artifact_generator: Callable that runs all exporters + packagers
                and returns ``(images, artifacts)`` asset refs.  Defaults to
                :func:`_default_artifact_generator`.
            site_publisher_factory: Callable constructing a :class:`SitePublisher`
                from an open :class:`ChangeJournal`.  Defaults to
                :class:`SitePublisher`.
            datasheet_name_lookup: Optional :data:`DatasheetNameLookup`
                (kproj#29).  Defaults to
                :func:`_default_datasheet_name_lookup`, an adapter around
                :func:`~kproj.common.datasheet_library.read_datasheet_names`
                (live ``jbom bom`` invocation). Tests inject a fake to
                avoid a real jBOM subprocess.
            library_repo: Optional local datasheet-library clone path
                override for the advisory publish guard (kproj#29), for
                tests that need to bypass the real clone. Production
                callers omit this; the effective path resolves from
                ``request.config.datasheet_library`` (kproj#37) on each
                :meth:`run` call instead of being fixed at construction
                time.
        """
        self._project_reader = project_reader or KicadProjectReader()
        self._metadata_analyzer = metadata_analyzer or MetadataAnalyzer()
        self._design_analyzer_factory = design_analyzer_factory or DesignAnalyzer
        self._ibom_script_locator: IbomScriptLocator = ibom_script_locator or find_ibom_script
        self._kicad_python_locator: KicadPythonLocator = kicad_python_locator or find_kicad_python
        self._artifact_generator: ArtifactGeneratorCallable = (
            artifact_generator or _default_artifact_generator
        )
        self._site_publisher_factory: SitePublisherFactory = site_publisher_factory or SitePublisher
        self._datasheet_name_lookup: DatasheetNameLookup = (
            datasheet_name_lookup or _default_datasheet_name_lookup
        )
        self._library_repo_override: Path | None = library_repo

    def run(self, request: PublishRequest) -> PublishResult:
        """Run the full 11-step publish pipeline against *request*.

        Args:
            request: The bundled inputs (project arg + config + flags).

        Returns:
            A :class:`PublishResult` describing the run.
        """
        # kproj can be invoked from more than one installation on this
        # machine (a PyPI/Homebrew release, or a dev/editable checkout
        # via `uv run`); detected once, up front, so the -v banner, the
        # iBOM page's embedded provenance, the front-matter
        # `kproj_publish_context`, and the site-repo commit trailer all
        # agree on "which kproj, really" (see kproj.common.install_info).
        install_info = detect_install_info()
        if request.verbose_level >= 1:
            print(f"Info: {format_provenance(install_info, request.watermark)}", file=sys.stderr)
            if install_info.location:
                print(f"Info: kproj loaded from {install_info.location}", file=sys.stderr)

        site_repo = request.config.site_repo

        # ── Steps 1-2: Resolve project + discover kicad-cli ──
        try:
            resolved = self._project_reader.resolve(request.project_arg)
        except ProjectResolutionError as exc:
            return PublishResult.build(
                "failed",
                message=f"Error: project resolution failed: {exc}",
            )

        try:
            kicad_cli = self._resolve_kicad_cli(request.config)
            major, minor, patch = kicad_version(kicad_cli)
        except KicadNotFoundError as exc:
            return PublishResult.build(
                "failed",
                message=f"Error: {exc}",
            )

        if major not in SUPPORTED_KICAD_MAJORS:
            allowed = ", ".join(f"{m}.x" for m in sorted(SUPPORTED_KICAD_MAJORS))
            return PublishResult.build(
                "failed",
                message=(
                    f"Error: unsupported kicad-cli version {major}.{minor}.{patch} "
                    f"at {kicad_cli} (kproj v1 supports {allowed})."
                ),
            )

        if request.verbose_level >= 1:
            print(
                f"Info: Using kicad-cli {major}.{minor}.{patch} at {kicad_cli}",
                file=sys.stderr,
            )
            if request.config.inventory is not None:
                print(jbom_tool_report(), file=sys.stderr)

        # ── Steps 2-3: Read + analyze ──
        project_info, read_findings = self._project_reader.read(resolved)
        metadata_analysis = self._metadata_analyzer.analyze(project_info, resolved.project_dir)
        design_analyzer = self._design_analyzer_factory(kicad_cli)
        try:
            design_analysis = design_analyzer.analyze(resolved)
        except DesignAnalysisError as exc:
            # M4 round-2: a kicad-cli DRC/ERC mechanical crash is a
            # separate channel from findings per ADR 0004.  The failure
            # happens BEFORE the change journal is opened, so no site
            # writes can occur; we surface it as outcome=failed/exit 2
            # with a stderr-ready message and skip everything downstream.
            return PublishResult.build(
                "failed",
                message=f"Error: Design analysis failed ({exc.origin}): {exc}",
            )
        # -v: show DRC/ERC findings inline right after analysis so the
        # user sees them in context without waiting for the end-of-run
        # summary.  The same findings appear in the final PublishResult
        # for the summary line; this call is display-only.
        if request.verbose_level >= 1:
            _print_design_findings_inline(design_analysis.findings)
        analysis = AnalysisInfo(
            findings=tuple(read_findings) + metadata_analysis.findings + design_analysis.findings
        )

        # GitHub-repo-link detection (kproj#30): evaluated exactly ONCE
        # per publish via detect_github_link (the only function in
        # common.github_link that touches git). The single resulting
        # `github_link_detection` is threaded to both consumers so they
        # can never disagree: `finding_for_detection` (pure, no I/O)
        # below drives the absence-highlighting audit finding, and
        # `github_link_detection.url` is passed to build_publication
        # for the front-matter `github_url` field. Never raises; the
        # finding is merged into `analysis` here (rather than only at
        # Publication-build time) so it shows up in the Metadata Audit
        # table/stderr for every outcome, private-skip included.
        github_link_detection = detect_github_link(resolved.project_dir)
        github_link_finding = finding_for_detection(
            github_link_detection, project_dir=resolved.project_dir, project=project_info.project
        )
        if github_link_finding is not None:
            analysis = AnalysisInfo(findings=(*analysis.findings, github_link_finding))

        # Datasheet-name lookup (kproj#29): a live `jbom bom` query (ADR
        # 0010), not the stale `production/jbom.csv` fab snapshot. Evaluated
        # once per publish and threaded to both the front-matter deep-links
        # (via `datasheet_links` -> `build_publication`) and the advisory
        # findings merged into `analysis` here - mirroring the GitHub-link
        # single-evaluation pattern above - so it shows up in the Metadata
        # Audit table/stderr for every outcome, private-skip included.
        #
        # Structural enforcement of "advisory-only, never blocks": both
        # calls are wrapped here, not just internally. `read_datasheet_names`
        # / `check_datasheet_links` already catch every failure mode they
        # know about, but the ticket-owner's "never a publish blocker"
        # guarantee must not rest solely on those two functions being
        # perfectly exhaustive - an injected fake (tests), an unmapped
        # OSError variant, or any other surprise here degrades to a
        # warning Finding rather than propagating and failing the publish.
        library_repo = (
            self._library_repo_override
            if self._library_repo_override is not None
            else request.config.datasheet_library
        )
        datasheet_links, datasheet_findings = self._lookup_datasheet_links(
            resolved.project_dir,
            request.config.inventory,
            project_info.project,
            fabricator=request.config.fabricator,
            library_repo=library_repo,
            datasheet_repo=request.config.datasheet_repo,
        )
        if datasheet_findings:
            analysis = AnalysisInfo(findings=(*analysis.findings, *datasheet_findings))

        # ── Step 4: Status detection (private-skip) ──
        if project_info.status is Status.PRIVATE:
            return PublishResult.build(
                "private-skip",
                message=(
                    f"Note: {resolved.basename!r} is status=private; "
                    "audit + DRC/ERC ran for stderr only, no site writes."
                ),
                findings=analysis.findings,
            )

        # ── Step 5a: iBOM pre-flight (script + KiCad-bundled interpreter) ──
        # kproj#10: the iBOM script needs the interpreter that can
        # ``import pcbnew`` (KiCad's bundled Python, not kproj's venv).
        # Resolve both here so a missing interpreter fails pre-flight
        # with exit 2 before any change journal is opened.
        try:
            ibom_script = self._ibom_script_locator()
            kicad_python = self._kicad_python_locator()
        except KicadNotFoundError as exc:
            return PublishResult.build(
                "failed",
                message=f"Error: {exc}",
                findings=analysis.findings,
            )

        # Refresh iBOM's own web/user.css + user.js (see
        # kproj.services.ibom_generator.write_ibom_user_files) with this
        # run's provenance every publish, independent of whether
        # artifact regeneration itself runs below - both because the
        # write is idempotent/cheap, and so a stale/wiped web/ dir
        # (e.g. after a Plugin and Content Manager reinstall) self-heals
        # on the very next publish rather than only on the next
        # iBOM-regenerating one.
        if not request.dry_run:
            write_ibom_user_files(
                ibom_script,
                install_info=install_info,
                watermark=request.watermark,
            )

        # ── Step 5b: Site-repo cleanliness check (non-private only, non-dry-run) ──
        if not request.dry_run:
            try:
                clean_result = subprocess_run(
                    ["git", "-C", str(site_repo), "status", "--porcelain"],
                    timeout=DEFAULT_GIT_TIMEOUT,
                    check=True,
                )
                if clean_result.stdout.strip():
                    return PublishResult.build(
                        "failed",
                        message=(
                            f"Error: Site repo {site_repo} has uncommitted changes. "
                            "Commit, stash, or clean before publishing."
                        ),
                        findings=analysis.findings,
                    )
            except (SubprocessFailedError, SubprocessTimeoutError) as exc:
                return PublishResult.build(
                    "failed",
                    message=f"Error: Could not check site-repo cleanliness: {exc}",
                    findings=analysis.findings,
                )

        # ── Step 6: assemble render inputs + decide Make-style regeneration ──
        body_md = MarkdownTableFormatter().render(analysis.findings)
        readme_md = _read_readme(resolved.project_dir)

        prod_dir = resolved.project_dir / "production"
        include_fab = prod_dir.is_dir() and any(prod_dir.iterdir())
        images_refs, artifact_refs = _compute_standard_asset_refs(
            project_info.project, project_info.board_rev, include_fab=include_fab
        )

        # Publish timestamp = kproj execution time, emitted as Hugo's
        # reserved ``date`` field.  SitePublisher preserves the on-disk
        # value on an unchanged re-run so the markdown stays byte-identical
        # (git then sees no change); the fresh value lands only when
        # something else changed.
        published_at = _publish_timestamp()

        version_file = request.config.site_profile.version_page_path(
            site_repo, project_info.project, project_info.board_rev
        )
        # Make-style regeneration decision ("ancient makefile" semantics):
        # (re)run the artifact producers only when a KiCad source is newer
        # than its on-disk artifact, or an artifact / the version page is
        # missing.  There is NO kproj-internal content-comparison no-op:
        # git decides whether the publish commits anything (unchanged
        # sources -> byte-identical outputs -> empty ``git diff --cached``).
        publish_context = _current_publish_context(
            kicad_version=(major, minor, patch),
            inventory_enabled=request.config.inventory is not None,
            fabricator=request.config.fabricator,
            ibom_extra_fields=request.config.ibom_extra_fields,
            install_type=install_info.install_type,
            watermark=request.watermark,
        )
        existing_publish_context = _existing_publish_context(version_file)
        publish_context_drift = version_file.exists() and (
            _normalize_publish_context(existing_publish_context)
            != _normalize_publish_context(publish_context)
        )
        if publish_context_drift:
            _log.debug(
                "publish context drift for %s-%s: existing=%s current=%s",
                project_info.project,
                project_info.board_rev,
                existing_publish_context or {},
                publish_context,
            )

        needs_regen_by_staleness = _needs_regeneration(
            images=images_refs,
            artifacts=artifact_refs,
            resolved=resolved,
            site_repo=site_repo,
            site_profile=request.config.site_profile,
            version_file=version_file,
        )
        needs_regen = request.republish or needs_regen_by_staleness or publish_context_drift
        existing_github_url = _existing_github_url(version_file)
        current_github_url = github_link_detection.url or ""
        github_url_drift = version_file.exists() and existing_github_url != current_github_url
        if github_url_drift:
            _log.debug(
                "metadata drift for %s-%s: github_url changed from %r to %r",
                project_info.project,
                project_info.board_rev,
                existing_github_url,
                current_github_url,
            )
        if request.republish:
            decision = "regenerate (forced by --republish/--force)"
        elif needs_regen_by_staleness:
            decision = "regenerate (sources/artifacts stale or missing)"
        elif publish_context_drift:
            decision = "regenerate (publish context changed)"
        else:
            decision = "skip (sources unchanged)"
        if not needs_regen and github_url_drift:
            decision = "skip (sources unchanged; metadata drift: github_url changed)"
        _log.debug(
            "artifact regeneration decision for %s-%s: %s",
            project_info.project,
            project_info.board_rev,
            decision,
        )

        # ── Steps 7-11: Open journal, generate artifacts, publish ──
        try:
            with ChangeJournal(site_repo, dry_run=request.dry_run) as journal:
                # Step 8: (re)generate artifacts only when Make-style
                # staleness says so; skip when everything is up to date.
                producer_diagnostics: tuple[Finding, ...] = ()
                if needs_regen and not request.dry_run:
                    actual_images, actual_artifacts, producer_diagnostics = (
                        self._artifact_generator(
                            resolved,
                            project_info,
                            kicad_cli,
                            ibom_script,
                            kicad_python,
                            site_repo,
                            request.config.site_profile,
                            request.config.inventory,
                            request.config.fabricator,
                            request.config.ibom_extra_fields,
                            journal,
                        )
                    )
                else:
                    actual_images, actual_artifacts = images_refs, artifact_refs

                # M6 fix-up: merge producer-stage diagnostics into the
                # final analysis + rebuild body markdown so front-matter
                # counts, stderr, and Markdown tables all reflect the
                # artifact-generation warnings (production_incomplete,
                # production_stale, fab_gerber_ambiguous, etc.) that were
                # previously discarded.
                final_analysis = (
                    AnalysisInfo(findings=analysis.findings + producer_diagnostics)
                    if producer_diagnostics
                    else analysis
                )
                final_body_md = (
                    MarkdownTableFormatter().render(final_analysis.findings)
                    if producer_diagnostics
                    else body_md
                )

                # Step 9: Build final publication
                final_pub = PublishWorkflow.build_publication(
                    resolved,
                    project_info,
                    final_analysis,
                    body_md=final_body_md,
                    readme_md=readme_md,
                    images=actual_images,
                    artifacts=actual_artifacts,
                    published_at=published_at,
                    github_url=github_link_detection.url or "",
                    datasheets=datasheet_links,
                    publish_context=publish_context,
                )

                # Step 10: SitePublisher.publish writes the markdown,
                # stages the journalled paths, and lets git decide whether
                # to commit (empty ``git diff --cached`` -> no-op).
                site_publisher = self._site_publisher_factory(journal)
                result = site_publisher.publish(
                    final_pub,
                    site_repo,
                    request.config.no_push,
                    request.dry_run,
                    request.config.site_profile,
                )

                # Step 11: ChangeJournal closed via context-manager __exit__
                return result

        except SchematicExportError as exc:
            # BLOCKER 5: a schematic-export shape mismatch (zero SVGs,
            # or multiple root-only SVGs) is a mechanical failure, not
            # an audit finding.  ChangeJournal.__exit__ has already
            # rolled back any files produced by earlier steps within
            # the `with` block above; convert the exception into
            # outcome=failed/exit 2 with a stderr-ready message.
            return PublishResult.build(
                "failed",
                message=f"Error: Schematic export failed: {exc}",
                findings=analysis.findings,
            )
        except FileNotFoundError as exc:
            # IbomGenerator raises FileNotFoundError when iBOM exits 0
            # but produces no HTML.  Treat the same as the other
            # mechanical-failure shapes so callers get exit 2 with a
            # tidy stderr message rather than a traceback.
            return PublishResult.build(
                "failed",
                message=f"Error: Artifact generation failed: {exc}",
                findings=analysis.findings,
            )
        except (SubprocessFailedError, SubprocessTimeoutError, OSError) as exc:
            return PublishResult.build(
                "failed",
                message=f"Error: Pipeline failed: {exc}",
                findings=analysis.findings,
            )

    def _lookup_datasheet_links(
        self,
        project_dir: Path,
        inventory: Path | None,
        project: str,
        *,
        fabricator: str,
        library_repo: Path,
        datasheet_repo: str,
    ) -> tuple[tuple[DatasheetLink, ...], tuple[Finding, ...]]:
        """Run the datasheet-name lookup + advisory guard, never raising.

        Structural enforcement of the "advisory-only, never a publish
        blocker" contract (kproj#29 / ADR 0010): every step here is
        wrapped so an unexpected exception - from the injected lookup
        callable, from :func:`~kproj.common.datasheet_library.check_datasheet_links`,
        or from anything in between - degrades to a single warning
        ``Finding`` (``datasheet_lookup_failed``) instead of propagating
        and failing the publish. This is deliberately *in addition to*
        (not a replacement for) the exhaustive error handling already
        inside ``read_datasheet_names`` / ``check_datasheet_links``.

        Args:
            project_dir: The resolved KiCad project directory.
            inventory: Optional inventory CSV path (``KprojConfig.inventory``).
            project: Project basename, threaded onto any emitted ``Finding``.
            fabricator: jBOM fabricator profile (``KprojConfig.fabricator``).
            library_repo: Resolved local datasheet-library clone path
                (``KprojConfig.datasheet_library``, kproj#37).
            datasheet_repo: Resolved public ``<owner>/<repo>`` slug
                (``KprojConfig.datasheet_repo``, kproj#37).

        Returns:
            A 2-tuple of ``(datasheet_links, findings)``. Both are empty
            on the (never-raising) failure path.
        """
        try:
            names, lookup_findings = self._datasheet_name_lookup(
                project_dir,
                inventory,
                fabricator,
            )
            links = tuple(build_datasheet_link(name, owner_repo=datasheet_repo) for name in names)
            guard_findings = check_datasheet_links(names, library_repo, project=project)
            return links, (*lookup_findings, *guard_findings)
        except Exception as exc:  # advisory-only, deliberately broad; see docstring
            _log.warning("datasheet-name lookup/guard failed unexpectedly: %s", exc)
            return (), (
                Finding(
                    severity=Severity.WARNING,
                    field="datasheet_lookup_failed",
                    value=str(exc),
                    reason=(
                        "datasheet-name lookup or the advisory library guard raised "
                        f"unexpectedly ({exc!r}); publishing without datasheet links"
                    ),
                    project=project,
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

    @staticmethod
    def build_publication(
        resolved: ResolvedProject,
        project_info: ProjectInfo,
        analysis_info: AnalysisInfo,
        *,
        body_md: str = "",
        readme_md: str = "",
        images: tuple[AssetRef, ...] = (),
        artifacts: tuple[AssetRef, ...] = (),
        published_at: str = "",
        github_url: str | None = None,
        datasheets: tuple[DatasheetLink, ...] = (),
        publish_context: Mapping[str, object] | None = None,
    ) -> Publication:
        """Build the site-emission-ready :class:`Publication` for a project.

        This is DESIGN step 9 (build Publication).  It scans
        ``resolved.project_dir`` for the project-global content model:
        :func:`kproj.common.kicad_libraries.enumerate_libraries` for
        library refs, and
        :func:`kproj.common.project_docs.read_description` for the
        DESCRIPTION prose rendered on the project section index.

        Args:
            resolved: The resolved project (provides ``project_dir``).
            project_info: Title-block + audit-ready facts.
            analysis_info: Audit + DRC/ERC findings merged.
            body_md: Pre-rendered Markdown body (audit + DRC/ERC tables).
            readme_md: Project README.md content for the project section
                index ``<versions_dir>/<P>/_index.md``.
            images: Image asset refs.
            artifacts: Artifact asset refs.
            published_at: Publish timestamp for Hugo's ``date`` field
                (empty string omits it).
            github_url: The "see/fork on GitHub" link (kproj#30), or
                ``""`` when none was detected.  ``PublishWorkflow.run``
                always passes this explicitly - computed exactly once
                via :func:`kproj.common.github_link.detect_github_link`
                and shared with the absence-highlighting audit finding
                (see the *Single-evaluation guarantee* in
                ``common/github_link.py``'s module docstring) - so the
                front-matter URL and the finding can never disagree.
                ``None`` (the default) is for direct callers (e.g. unit
                tests) that don't have a precomputed detection; in that
                case this method runs its own one-off detection via
                :func:`kproj.common.github_link.derive_github_link`.
            datasheets: Curated datasheet deep-links (kproj#29), already
                computed once by ``PublishWorkflow.run`` via
                :func:`kproj.common.datasheet_library.read_datasheet_names`
                + :func:`kproj.common.datasheet_library.build_datasheet_link`
                - mirrors the ``github_url`` single-evaluation pattern.
                ``()`` (the default) is for direct callers (e.g. unit
                tests) that don't have a precomputed lookup.
            publish_context: Optional publish-provenance metadata emitted
                as front-matter ``kproj_publish_context`` for future
                regeneration decisions.

        Returns:
            A populated :class:`Publication`.
        """
        resolved_github_url = (
            github_url
            if github_url is not None
            else (derive_github_link(resolved.project_dir) or "")
        )
        return Publication(
            project_info=project_info,
            analysis_info=analysis_info,
            body_md=body_md,
            readme_md=readme_md,
            published_at=published_at,
            datasheets=datasheets,
            description=read_description(resolved.project_dir),
            images=images,
            artifacts=artifacts,
            libraries=enumerate_libraries(resolved.project_dir),
            github_url=resolved_github_url,
            publish_context=dict(publish_context or {}),
        )


# ──────────────────────────── module-level helpers ────────────────────────────


_DESIGN_SOURCES: tuple[str, ...] = ("drc", "erc")


def _print_design_findings_inline(findings: tuple[Finding, ...]) -> None:
    """Print DRC/ERC findings grouped by source to stderr immediately.

    Called from :meth:`PublishWorkflow.run` when ``verbose_level >= 1``
    (``-v``).  Findings are displayed right after :meth:`DesignAnalyzer.analyze`
    returns so they appear in context rather than at the end-of-run summary.

    Format per group::

        DRC: 3 violation(s)
          [warning] copper_to_board_edge: Silkscreen clipped by copper
          [error]   track_width: Track width too narrow (at pos 42.3, 18.7)
        ERC: 0 violation(s)

    Args:
        findings: The findings from :meth:`DesignAnalyzer.analyze` — only
            entries with ``source in ("drc", "erc")`` are displayed.
    """
    by_source: dict[str, list[Finding]] = {src: [] for src in _DESIGN_SOURCES}
    for finding in findings:
        src = finding.source.lower()
        if src in by_source:
            by_source[src].append(finding)
    for src in _DESIGN_SOURCES:
        group = by_source[src]
        label = src.upper()
        count = len(group)
        print(f"{label}: {count} violation(s)", file=sys.stderr)
        if group:
            for f in group:
                sev = f.severity.value.lower()
                location = f" (at {f.value})" if f.value else ""
                print(f"  [{sev}] {f.field}: {f.reason}{location}", file=sys.stderr)
        else:
            print("  (none)", file=sys.stderr)


def _default_datasheet_name_lookup(
    project_dir: Path,
    inventory: Path | None,
    fabricator: str,
) -> tuple[tuple[str, ...], tuple[Finding, ...]]:
    """Default :data:`DatasheetNameLookup` adapter over ``read_datasheet_names``.

    ``read_datasheet_names`` takes ``fabricator`` as a keyword-only
    argument; this adapter preserves the simpler injected callable shape
    used by :class:`PublishWorkflow`.
    """
    return read_datasheet_names(
        project_dir,
        inventory,
        fabricator=fabricator,
    )


def _read_readme(project_dir: Path) -> str:
    """Read and return the project's README.md content, or empty string."""
    readme = project_dir / "README.md"
    if readme.is_file():
        return readme.read_text(encoding="utf-8")
    return ""


def _existing_github_url(version_file: Path) -> str:
    """Return the existing ``github_url`` front-matter value, or ``\"\"``.

    A missing/invalid file (or missing key) is treated as no URL so the
    caller can compare it directly with the current detection result.
    """
    front_matter = _front_matter_mapping(version_file)
    if front_matter is None:
        return ""
    existing = front_matter.get("github_url")
    return str(existing).strip() if existing else ""


def _existing_publish_context(version_file: Path) -> dict[str, object] | None:
    """Return existing ``kproj_publish_context`` data from a version page.

    Missing files, invalid front-matter, absent keys, or non-mapping
    values all return ``None`` so callers can treat them as legacy pages
    without stored publish context.
    """
    front_matter = _front_matter_mapping(version_file)
    if front_matter is None:
        return None
    raw_context = front_matter.get("kproj_publish_context")
    if not isinstance(raw_context, Mapping):
        return None
    return {str(key): value for key, value in raw_context.items()}


def _front_matter_mapping(version_file: Path) -> dict[str, object] | None:
    """Parse and return a version file's YAML front-matter mapping.

    Returns ``None`` when the file is missing, unreadable, lacks fenced
    front-matter, or parses to a non-mapping top-level shape.
    """
    if not version_file.exists():
        return None
    try:
        text = version_file.read_text(encoding="utf-8")
    except OSError:
        return None
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return None
    try:
        front_matter = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    if not isinstance(front_matter, Mapping):
        return None
    return {str(key): value for key, value in front_matter.items()}


def _current_publish_context(
    *,
    kicad_version: tuple[int, int, int],
    inventory_enabled: bool,
    fabricator: str,
    ibom_extra_fields: tuple[str, ...],
    install_type: str,
    watermark: str,
) -> dict[str, object]:
    """Return the current run's output-affecting publish context metadata.

    Args:
        kicad_version: The discovered ``kicad-cli`` ``(major, minor, patch)``.
        inventory_enabled: Whether inventory-derived iBOM enrichment is active.
        fabricator: The configured jBOM fabricator profile.
        ibom_extra_fields: The configured extra iBOM columns.
        install_type: This run's detected kproj install type
            (``"release"``/``"editable"``; see
            :func:`kproj.common.install_info.detect_install_info`). Not
            itself "output-affecting" for the BOM/render pipeline, but
            included here (schema 2) so the front-matter block doubles
            as a provenance record, per the RCA follow-up on
            distinguishing which kproj install produced a given publish.
        watermark: This run's ``--watermark`` value (empty by default).
    """
    major, minor, patch = kicad_version
    return {
        "schema": _PUBLISH_CONTEXT_SCHEMA,
        "kproj_version": KPROJ_VERSION,
        "kicad_cli_version": f"{major}.{minor}.{patch}",
        "inventory_enabled": inventory_enabled,
        "fabricator": fabricator,
        "ibom_extra_fields": list(ibom_extra_fields),
        "kproj_install_type": install_type,
        "watermark": watermark,
    }


def _normalize_publish_context(context: Mapping[str, object] | None) -> dict[str, object]:
    """Normalize publish-context metadata for deterministic equality checks.

    Includes ``kproj_install_type``/``watermark`` like every other
    field: a watermark change forcing a regeneration is intentional,
    not incidental. ``write_ibom_user_files`` refreshes the shared
    ``web/user.css``/``user.js`` on every publish regardless of this
    decision, but the actual ``.ibom.html`` artifact is only
    regenerated when ``needs_regen`` is true - if a watermark change
    didn't count as drift, a "skip" outcome would leave a *stale*
    watermark baked into the on-disk iBOM page while the shared
    ``web/`` files already show the new one, reintroducing the exact
    "which run does this actually reflect" confusion ``--watermark``
    exists to prevent.
    """
    if context is None:
        return {
            "schema": 0,
            "kproj_version": "",
            "kicad_cli_version": "",
            "inventory_enabled": False,
            "fabricator": "",
            "ibom_extra_fields": (),
            "kproj_install_type": "",
            "watermark": "",
        }
    raw_schema = context.get("schema", 0)
    try:
        schema = int(str(raw_schema).strip())
    except (TypeError, ValueError):
        schema = 0

    raw_fields = context.get("ibom_extra_fields", ())
    if isinstance(raw_fields, str):
        ibom_fields = tuple(field.strip() for field in raw_fields.split(",") if field.strip())
    elif isinstance(raw_fields, Sequence):
        ibom_fields = tuple(str(field).strip() for field in raw_fields if str(field).strip())
    else:
        ibom_fields = ()

    return {
        "schema": schema,
        "kproj_version": str(context.get("kproj_version", "")).strip(),
        "kicad_cli_version": str(context.get("kicad_cli_version", "")).strip(),
        "inventory_enabled": bool(context.get("inventory_enabled", False)),
        "fabricator": str(context.get("fabricator", "")).strip().lower(),
        "ibom_extra_fields": ibom_fields,
        "kproj_install_type": str(context.get("kproj_install_type", "")).strip(),
        "watermark": str(context.get("watermark", "")).strip(),
    }


def _publish_timestamp() -> str:
    """Return the current UTC time as an RFC3339 string for Hugo's ``date``.

    Hugo requires its reserved ``date`` front-matter field to be a
    parseable date; the kproj execution time serves as the page's
    publish timestamp.  Seconds precision (microseconds dropped) keeps
    the value tidy.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _compute_standard_asset_refs(
    project: str,
    board_rev: str,
    *,
    include_fab: bool,
) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...]]:
    """Compute the canonical image + artifact :class:`AssetRef` tuples.

    These are deterministic from ``project`` + ``board_rev`` and the
    ``include_fab`` flag.  They are used both in step 6 (new-release
    detection) and step 9 (final publication assembly).

    Args:
        project: The project basename (``<P>``).
        board_rev: The board revision string (``<R>``).
        include_fab: Whether to include ``<P>-<R>.fab.zip``.

    Returns:
        A 2-tuple of ``(images, artifacts)`` :class:`AssetRef` tuples.
    """
    P, R = project, board_rev
    PR = f"{P}-{R}"
    base = f"/versions/{P}/{R}"

    images: tuple[AssetRef, ...] = (
        AssetRef(path=f"{base}/{PR}.top.png", tag="render-top", title="Top"),
        AssetRef(path=f"{base}/{PR}.bottom.png", tag="render-bottom", title="Bottom"),
        AssetRef(path=f"{base}/{PR}.sch.svg", tag="schematic-svg", title="Schematic"),
    )

    artifact_list: list[AssetRef] = [
        AssetRef(
            path=f"{base}/{PR}.sch.pdf",
            tag="schematic-pdf",
            post="Full schematic (all sheets)",
        ),
        AssetRef(
            path=f"{base}/{PR}.ibom.html",
            tag="interactive-bom",
            post="Interactive HTML BOM",
        ),
        AssetRef(
            path=f"{base}/{PR}.step",
            tag="step-model",
            post="3D STEP model",
        ),
    ]
    if include_fab:
        artifact_list.append(
            AssetRef(
                path=f"{base}/{PR}.fab.zip",
                tag="fab-pack",
                post="Fab-house bundle (BOM + POS + gerbers)",
            )
        )
    artifact_list.append(
        AssetRef(
            path=f"{base}/{PR}.source.zip",
            tag="source-archive",
            post="KiCad source archive",
        )
    )

    return images, tuple(artifact_list)


def _needs_regeneration(
    *,
    images: tuple[AssetRef, ...],
    artifacts: tuple[AssetRef, ...],
    resolved: ResolvedProject,
    site_repo: Path,
    site_profile: SiteProfile,
    version_file: Path,
) -> bool:
    """Return ``True`` when the artifact producers must (re)run (Make-style).

    Regeneration is needed when the version page is absent, any expected
    asset is missing, or any existing asset is older than its KiCad
    source (:func:`_assets_are_stale`).  When nothing is stale the
    producers are skipped so their timestamped binaries stay
    byte-identical and the run stays a git no-op.
    """
    if not version_file.exists():
        return True
    for ref in (*images, *artifacts):
        if not site_profile.asset_disk_path(site_repo, ref.path).exists():
            return True
    return _assets_are_stale(
        images=images,
        artifacts=artifacts,
        resolved=resolved,
        site_repo=site_repo,
        site_profile=site_profile,
    )


def _assets_are_stale(
    *,
    images: tuple[AssetRef, ...],
    artifacts: tuple[AssetRef, ...],
    resolved: ResolvedProject,
    site_repo: Path,
    site_profile: SiteProfile,
) -> bool:
    """Return ``True`` when any standard asset is older than its source.

    Implements ``docs/DESIGN.md`` § *New-release detection* asset
    freshness rule.  Each asset tag has a deterministic source:

    - ``render-top`` / ``render-bottom`` / ``step-model`` /
      ``interactive-bom`` → PCB file.
    - ``schematic-svg`` / ``schematic-pdf`` → root schematic file.
    - ``source-archive`` → newest file under ``project_dir``
      (excluding ``production/`` so jBOM outputs don't reset the
      check).
    - ``fab-pack`` → newest file under ``production/``.

    Args:
        images: AssetRef tuple for image-type assets.
        artifacts: AssetRef tuple for downloadable-type assets.
        resolved: The resolved project carrying PCB / SCH paths.
        site_repo: Local site-repo checkout.
        site_profile: Profile mapping the public asset URL to its
            physical on-disk location (Hugo assets live under
            ``static/versions/`` yet resolve at ``/versions/``).

    Returns:
        ``True`` when at least one existing asset is older than its
        source mtime; ``False`` otherwise (and when no source could
        be determined for a given tag).
    """
    source_for_tag = _source_paths_by_tag(resolved)
    for ref in (*images, *artifacts):
        source = source_for_tag.get(ref.tag)
        if source is None or not source.exists():
            continue
        asset_path = site_profile.asset_disk_path(site_repo, ref.path)
        if not asset_path.exists():
            continue
        if asset_path.stat().st_mtime < source.stat().st_mtime:
            return True
    return False


def _source_paths_by_tag(resolved: ResolvedProject) -> dict[str, Path | None]:
    """Map each standard asset tag to its (newest) source-side path.

    See :func:`_assets_are_stale` for the per-tag source rules.
    Returns ``None`` when a tag has no detectable source (e.g. an
    empty ``production/`` for the fab-pack tag); callers treat
    ``None`` as "cannot determine staleness; do not escalate".
    """
    pcb = resolved.pcb_file
    sch = resolved.root_schematic
    return {
        "render-top": pcb,
        "render-bottom": pcb,
        "step-model": pcb,
        "interactive-bom": pcb,
        "schematic-svg": sch,
        "schematic-pdf": sch,
        "source-archive": _newest_source_file(resolved.project_dir),
        "fab-pack": _newest_source_file(resolved.project_dir / "production"),
    }


def _newest_source_file(directory: Path) -> Path | None:
    """Return the file in *directory* with the largest mtime, or ``None``.

    Walks recursively but skips the ``production/`` subdirectory (so a
    jBOM-refreshed production set doesn't fool the source-archive
    freshness check) and any hidden / VCS directories.
    """
    if not directory.is_dir():
        return None
    newest: Path | None = None
    newest_mtime: float = -1.0
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        # Skip production/ when scanning the project root so the source
        # archive's source mtime is the KiCad source set, not jBOM
        # outputs that have their own freshness check.
        try:
            rel = path.relative_to(directory)
        except ValueError:
            continue
        if rel.parts and rel.parts[0] in {"production", ".git"}:
            continue
        mtime = path.stat().st_mtime
        if mtime > newest_mtime:
            newest_mtime = mtime
            newest = path
    return newest


def _default_artifact_generator(
    resolved: ResolvedProject,
    project_info: ProjectInfo,
    kicad_cli: Path,
    ibom_script: Path,
    kicad_python: Path,
    site_repo: Path,
    site_profile: SiteProfile,
    inventory: Path | None,
    fabricator: str,
    ibom_extra_fields: tuple[str, ...],
    journal: ChangeJournal,
) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[Finding, ...]]:
    """Generate all release artifacts using real kicad-cli + iBOM.

    This is the production artifact-generator injected into
    :class:`PublishWorkflow` by default.  Tests replace it with a stub
    that returns placeholder asset refs without invoking any subprocesses.

    Per ``docs/DESIGN.md`` § *Release asset set* + § *IbomGenerator*
    (kproj#10 caveat): if iBOM fails, the :class:`ChangeJournal` context
    manager rolls back all written files.  The workflow catches the
    resulting exception and returns ``outcome="failed"``.

    The on-disk layout and AssetRef paths are derived from the
    canonical ``project_info.project`` (``<P>``) and
    ``project_info.board_rev`` (``<R>``) per ``docs/DESIGN.md``
    § *Release asset set* and § *Metadata precedence*.  Wave-3 fix-up
    (BLOCKER 1): the prior heuristic used ``resolved.project_file.stem``
    for the board revision, which only coincided with the real PCB
    revision when the project basename happened to match.

    Args:
        resolved: The resolved project.
        project_info: Title-block facts carrying the canonical
            ``project`` + ``board_rev`` tokens.
        kicad_cli: Discovered kicad-cli path.
        ibom_script: Discovered iBOM script path.
        kicad_python: KiCad's bundled Python interpreter (runs iBOM;
            kproj#10 - the venv Python lacks ``pcbnew``).
        site_repo: Local site-repo checkout.
        site_profile: Backend profile; its ``assets_dir`` decides where
            asset files are physically written (e.g. Hugo's
            ``static/versions/``), while the public AssetRef URLs stay
            ``/versions/...``.
        inventory: Optional inventory CSV used to enrich iBOM extra-data
            rows from a live ``jbom bom`` query.
        fabricator: jBOM fabricator profile passed to lookup commands
            to normalize item/header shape (for example ``jlc``).
        ibom_extra_fields: Ordered iBOM extra fields to surface.
        journal: Open :class:`ChangeJournal` for rollback tracking.

    Returns:
        A 3-tuple ``(images, artifacts, diagnostics)`` where
        ``diagnostics`` is the accumulated union of
        :attr:`ExportResult.diagnostics` from every producer that ran
        (wave-3 M6 fix-up).
    """
    pcb_exporter = PcbExporter(kicad_cli)
    sch_exporter = SchematicExporter(kicad_cli)
    ibom_gen = IbomGenerator(ibom_script, kicad_python, extra_fields=ibom_extra_fields)
    thumbnail_gen = ThumbnailGenerator()
    archiver = ZipArchiver()
    fab_packager = FabPackager(archiver)
    source_packager = SourcePackager(archiver)

    P = project_info.project
    R = project_info.board_rev
    PR = f"{P}-{R}"
    # Physical write location comes from the profile (Hugo -> static/versions);
    # the public URL below stays /versions/ regardless of backend.
    asset_dir = site_repo / site_profile.assets_dir / P / R
    asset_dir.mkdir(parents=True, exist_ok=True)

    base_site = f"/versions/{P}/{R}"

    diagnostics: list[Finding] = []
    ibom_rows: tuple[DatasheetRow, ...] = ()
    if inventory is not None:
        ibom_rows, ibom_row_findings = read_ibom_rows(
            resolved.project_dir,
            inventory,
            project=P,
            fabricator=fabricator,
        )
        diagnostics.extend(ibom_row_findings)

    # PCB renders
    top_path = asset_dir / f"{PR}.top.png"
    diagnostics.extend(
        pcb_exporter.export_render(resolved.pcb_file, "top", top_path, journal=journal).diagnostics
    )
    # Thumbnail (v1 grey-scale recipe: a copy of the top render, so the
    # front-matter image_path resolves on the built site; real scaling is
    # a tracked follow-up). Derived from top_path, so it runs right after.
    thumbnail_path = asset_dir / f"{PR}.thumbnail.png"
    diagnostics.extend(
        thumbnail_gen.generate(top_path, thumbnail_path, journal=journal).diagnostics
    )
    bottom_path = asset_dir / f"{PR}.bottom.png"
    diagnostics.extend(
        pcb_exporter.export_render(
            resolved.pcb_file, "bottom", bottom_path, journal=journal
        ).diagnostics
    )
    step_path = asset_dir / f"{PR}.step"
    diagnostics.extend(
        pcb_exporter.export_step(resolved.pcb_file, step_path, journal=journal).diagnostics
    )

    # Schematic exports
    svg_path = asset_dir / f"{PR}.sch.svg"
    diagnostics.extend(
        sch_exporter.export_svg(resolved.root_schematic, svg_path, journal=journal).diagnostics
    )
    pdf_path = asset_dir / f"{PR}.sch.pdf"
    diagnostics.extend(
        sch_exporter.export_pdf(resolved.root_schematic, pdf_path, journal=journal).diagnostics
    )

    # iBOM (kproj#10: may fail; ChangeJournal rolls back on exception)
    ibom_path = asset_dir / f"{PR}.ibom.html"
    diagnostics.extend(
        ibom_gen.generate(
            resolved.pcb_file,
            ibom_path,
            f"{PR}.ibom",
            journal=journal,
            extra_data_rows=ibom_rows if ibom_rows else None,
        ).diagnostics
    )

    # Fab pack (optional — skipped when production/ is missing)
    prod_dir = resolved.project_dir / "production"
    fab_result = fab_packager.package(
        prod_dir,
        asset_dir / f"{PR}.fab.zip",
        title=P,
        rev=R,
        journal=journal,
    )
    diagnostics.extend(fab_result.diagnostics)

    # Source archive
    source_path = asset_dir / f"{PR}.source.zip"
    diagnostics.extend(
        source_packager.package(
            resolved.project_dir, source_path, title=P, rev=R, journal=journal
        ).diagnostics
    )

    # kproj#29: datasheets are no longer copied into the site - the
    # project-index Documentation list deep-links the public
    # SPCoast-inventory library repo instead (see PublishWorkflow.run's
    # datasheet-name lookup + PublishWorkflow.build_publication).

    images: tuple[AssetRef, ...] = (
        AssetRef(path=f"{base_site}/{PR}.top.png", tag="render-top", title="Top"),
        AssetRef(path=f"{base_site}/{PR}.bottom.png", tag="render-bottom", title="Bottom"),
        AssetRef(path=f"{base_site}/{PR}.sch.svg", tag="schematic-svg", title="Schematic"),
    )
    artifact_list: list[AssetRef] = [
        AssetRef(
            path=f"{base_site}/{PR}.sch.pdf",
            tag="schematic-pdf",
            post="Full schematic (all sheets)",
        ),
        AssetRef(
            path=f"{base_site}/{PR}.ibom.html", tag="interactive-bom", post="Interactive HTML BOM"
        ),
        AssetRef(path=f"{base_site}/{PR}.step", tag="step-model", post="3D STEP model"),
    ]
    if not fab_result.skipped:
        artifact_list.append(
            AssetRef(
                path=f"{base_site}/{PR}.fab.zip",
                tag="fab-pack",
                post="Fab-house bundle (BOM + POS + gerbers)",
            )
        )
    artifact_list.append(
        AssetRef(
            path=f"{base_site}/{PR}.source.zip", tag="source-archive", post="KiCad source archive"
        )
    )
    return images, tuple(artifact_list), tuple(diagnostics)
