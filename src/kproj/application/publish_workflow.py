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
from collections.abc import Callable
from pathlib import Path

from ..common.content_hash import content_hash_excluding_title_block
from ..common.kicad_install import (
    SUPPORTED_KICAD_MAJORS,
    KicadNotFoundError,
    find_ibom_script,
    find_kicad_cli,
    kicad_version,
)
from ..common.kicad_libraries import enumerate_libraries
from ..common.subprocess_runner import (
    DEFAULT_GIT_TIMEOUT,
    SubprocessFailedError,
    SubprocessTimeoutError,
)
from ..common.subprocess_runner import run as subprocess_run
from ..config import KprojConfig
from ..formatters.markdown_table_formatter import MarkdownTableFormatter
from ..model.analysis_info import AnalysisInfo
from ..model.finding import Finding
from ..model.project_info import ProjectInfo, Status
from ..model.publication import AssetRef, Publication
from ..model.publish_request import PublishRequest
from ..model.publish_result import Outcome, PublishResult
from ..model.resolved_project import ResolvedProject
from ..services.change_journal import ChangeJournal
from ..services.design_analyzer import DesignAnalysisError, DesignAnalyzer
from ..services.fab_packager import FabPackager
from ..services.ibom_generator import IbomGenerator
from ..services.kicad_project_reader import (
    KicadProjectReader,
    ProjectResolutionError,
)
from ..services.metadata_analyzer import MetadataAnalyzer
from ..services.pcb_exporter import PcbExporter
from ..services.schematic_exporter import SchematicExporter, SchematicExportError
from ..services.site_publisher import SitePublisher
from ..services.source_packager import SourcePackager
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

ArtifactGeneratorCallable = Callable[
    ["ResolvedProject", "ProjectInfo", Path, Path, Path, "ChangeJournal"],
    tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple["Finding", ...]],
]
"""Callable that generates all release artifacts for a project.

Signature::

    def generator(
        resolved: ResolvedProject,
        project_info: ProjectInfo,
        kicad_cli: Path,
        ibom_script: Path,
        site_repo: Path,
        journal: ChangeJournal,
    ) -> tuple[images_refs, artifact_refs, diagnostics]

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

__all__ = [
    "ArtifactGeneratorCallable",
    "DesignAnalyzerFactory",
    "IbomScriptLocator",
    "Outcome",
    "PublishRequest",
    "PublishResult",
    "PublishWorkflow",
    "SitePublisherFactory",
]


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
        artifact_generator: ArtifactGeneratorCallable | None = None,
        site_publisher_factory: SitePublisherFactory | None = None,
    ) -> None:
        """Construct a workflow with optional injectable service factories.

        Args:
            project_reader: Optional :class:`KicadProjectReader`.
            metadata_analyzer: Optional :class:`MetadataAnalyzer`.
            design_analyzer_factory: Callable returning a configured
                :class:`DesignAnalyzer` for a given ``kicad-cli`` path.
            ibom_script_locator: Callable returning the iBOM script path.
                Defaults to :func:`~kproj.common.kicad_install.find_ibom_script`.
            artifact_generator: Callable that runs all exporters + packagers
                and returns ``(images, artifacts)`` asset refs.  Defaults to
                :func:`_default_artifact_generator`.
            site_publisher_factory: Callable constructing a :class:`SitePublisher`
                from an open :class:`ChangeJournal`.  Defaults to
                :class:`SitePublisher`.
        """
        self._project_reader = project_reader or KicadProjectReader()
        self._metadata_analyzer = metadata_analyzer or MetadataAnalyzer()
        self._design_analyzer_factory = design_analyzer_factory or DesignAnalyzer
        self._ibom_script_locator: IbomScriptLocator = ibom_script_locator or find_ibom_script
        self._artifact_generator: ArtifactGeneratorCallable = (
            artifact_generator or _default_artifact_generator
        )
        self._site_publisher_factory: SitePublisherFactory = site_publisher_factory or SitePublisher

    def run(self, request: PublishRequest) -> PublishResult:
        """Run the full 11-step publish pipeline against *request*.

        Args:
            request: The bundled inputs (project arg + config + flags).

        Returns:
            A :class:`PublishResult` describing the run.
        """
        site_repo = request.config.site_repo

        # ── Steps 1-2: Resolve project + discover kicad-cli ──
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

        if major not in SUPPORTED_KICAD_MAJORS:
            allowed = ", ".join(f"{m}.x" for m in sorted(SUPPORTED_KICAD_MAJORS))
            return PublishResult.build(
                "failed",
                message=(
                    f"kproj: unsupported kicad-cli version {major}.{minor}.{patch} "
                    f"at {kicad_cli} (kproj v1 supports {allowed})."
                ),
            )

        print(
            f"kproj: kicad-cli {major}.{minor}.{patch} at {kicad_cli}",
            file=sys.stderr,
        )

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
                message=f"kproj: design analysis failed ({exc.origin}): {exc}",
            )
        analysis = AnalysisInfo(
            findings=tuple(read_findings) + metadata_analysis.findings + design_analysis.findings
        )

        # ── Step 4: Status detection (private-skip) ──
        if project_info.status is Status.PRIVATE:
            return PublishResult.build(
                "private-skip",
                message=(
                    f"kproj: {resolved.basename!r} is status=private; "
                    "audit + DRC/ERC ran for stderr only, no site writes."
                ),
                findings=analysis.findings,
            )

        # ── Step 5a: iBOM pre-flight ──
        try:
            ibom_script = self._ibom_script_locator()
        except KicadNotFoundError as exc:
            return PublishResult.build(
                "failed",
                message=f"kproj: {exc}",
                findings=analysis.findings,
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
                            f"kproj: site repo {site_repo} has uncommitted changes. "
                            "Commit, stash, or clean before publishing."
                        ),
                        findings=analysis.findings,
                    )
            except (SubprocessFailedError, SubprocessTimeoutError) as exc:
                return PublishResult.build(
                    "failed",
                    message=f"kproj: could not check site-repo cleanliness: {exc}",
                    findings=analysis.findings,
                )

        # ── Step 6: New-release detection ──
        body_md = MarkdownTableFormatter().render(analysis.findings)
        readme_md = _read_readme(resolved.project_dir)

        prod_dir = resolved.project_dir / "production"
        include_fab = prod_dir.is_dir() and any(prod_dir.iterdir())
        images_refs, artifact_refs = _compute_standard_asset_refs(
            project_info.project, project_info.board_rev, include_fab=include_fab
        )

        # Compute title-block-stripped content hashes so we can
        # distinguish metadata-only edits from real design edits when
        # asset mtimes look stale.  Values are also persisted in the
        # emitted version-page front-matter for the next run to read.
        sch_content_hash = content_hash_excluding_title_block(resolved.root_schematic)
        pcb_content_hash = content_hash_excluding_title_block(resolved.pcb_file)

        preliminary_pub = PublishWorkflow.build_publication(
            resolved,
            project_info,
            analysis,
            body_md=body_md,
            readme_md=readme_md,
            images=images_refs,
            artifacts=artifact_refs,
            sch_content_hash=sch_content_hash,
            pcb_content_hash=pcb_content_hash,
        )

        preliminary_outcome = SitePublisher.detect_outcome(preliminary_pub, site_repo)
        # M1 fix-up: docs/DESIGN.md § New-release detection requires
        # comparing each asset's mtime against its source.  When the
        # PCB has been edited since the last publish but the title
        # block is stable, detect_outcome alone returns ``noop`` and
        # leaves stale renders/STEP/iBOM/source/fab on the site.
        # Force a full publish when any asset is older than its source.
        #
        # M11 round-2: BUT if the SCH/PCB content-hash (with title
        # blocks stripped) matches the hash stored in the previously
        # published version file, the mtime bump is title-block-only
        # (i.e. only status/date/rev metadata changed).  In that case
        # do NOT escalate to publish — the outcome stays
        # "refresh" (or "noop") per PRD Story 6's cheap-refresh contract.
        if (
            preliminary_outcome != "publish"
            and _assets_are_stale(
                images=images_refs,
                artifacts=artifact_refs,
                resolved=resolved,
                site_repo=site_repo,
            )
            and not _title_block_only_change_since_publish(
                site_repo=site_repo,
                project=project_info.project,
                board_rev=project_info.board_rev,
                current_sch_hash=sch_content_hash,
                current_pcb_hash=pcb_content_hash,
            )
        ):
            preliminary_outcome = "publish"
        if preliminary_outcome == "noop":
            return PublishResult.build("noop", findings=analysis.findings)

        # ── Steps 7-11: Open journal, generate artifacts, publish ──
        try:
            with ChangeJournal(site_repo, dry_run=request.dry_run) as journal:
                # Step 8: Generate artifacts (only for "publish"; skip on "refresh")
                producer_diagnostics: tuple[Finding, ...] = ()
                if preliminary_outcome == "publish" and not request.dry_run:
                    actual_images, actual_artifacts, producer_diagnostics = (
                        self._artifact_generator(
                            resolved,
                            project_info,
                            kicad_cli,
                            ibom_script,
                            site_repo,
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
                    sch_content_hash=sch_content_hash,
                    pcb_content_hash=pcb_content_hash,
                )

                # Step 10: SitePublisher.publish.  Pass the workflow's
                # pre-computed outcome so SitePublisher does not re-
                # decide against post-generation asset mtimes and
                # short-circuit an M1-escalated publish back to noop.
                site_publisher = self._site_publisher_factory(journal)
                result = site_publisher.publish(
                    final_pub,
                    site_repo,
                    request.config.no_push,
                    request.dry_run,
                    force_outcome=preliminary_outcome,
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
                message=f"kproj: schematic export failed: {exc}",
                findings=analysis.findings,
            )
        except FileNotFoundError as exc:
            # IbomGenerator raises FileNotFoundError when iBOM exits 0
            # but produces no HTML.  Treat the same as the other
            # mechanical-failure shapes so callers get exit 2 with a
            # tidy stderr message rather than a traceback.
            return PublishResult.build(
                "failed",
                message=f"kproj: artifact generation failed: {exc}",
                findings=analysis.findings,
            )
        except (SubprocessFailedError, SubprocessTimeoutError, OSError) as exc:
            return PublishResult.build(
                "failed",
                message=f"kproj: pipeline failed: {exc}",
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
        sch_content_hash: str = "",
        pcb_content_hash: str = "",
    ) -> Publication:
        """Build the site-emission-ready :class:`Publication` for a project.

        This is DESIGN step 9 (build Publication).  It calls
        :func:`kproj.common.kicad_libraries.enumerate_libraries`
        against ``resolved.project_dir`` and threads the resulting
        library refs onto :attr:`Publication.libraries`.

        Args:
            resolved: The resolved project (provides ``project_dir``).
            project_info: Title-block + audit-ready facts.
            analysis_info: Audit + DRC/ERC findings merged.
            body_md: Pre-rendered Markdown body (audit + DRC/ERC tables).
            readme_md: Project README.md content for ``pages/<P>.md``.
            images: Image asset refs.
            artifacts: Artifact asset refs.
            sch_content_hash: SHA-256 of the SCH content with the
                title-block stripped (M11 round-2).  Persisted in the
                emitted version-page front-matter so the next kproj
                run can distinguish title-block-only edits from real
                schematic edits.
            pcb_content_hash: Same, for the PCB file.

        Returns:
            A populated :class:`Publication`.
        """
        return Publication(
            project_info=project_info,
            analysis_info=analysis_info,
            body_md=body_md,
            readme_md=readme_md,
            images=images,
            artifacts=artifacts,
            libraries=enumerate_libraries(resolved.project_dir),
            sch_content_hash=sch_content_hash,
            pcb_content_hash=pcb_content_hash,
        )


# ──────────────────────────── module-level helpers ────────────────────────────


def _read_readme(project_dir: Path) -> str:
    """Read and return the project's README.md content, or empty string."""
    readme = project_dir / "README.md"
    if readme.is_file():
        return readme.read_text(encoding="utf-8")
    return ""


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


def _title_block_only_change_since_publish(
    *,
    site_repo: Path,
    project: str,
    board_rev: str,
    current_sch_hash: str,
    current_pcb_hash: str,
) -> bool:
    """Return ``True`` when the only change since last publish is title-block metadata.

    M11 round-2: compares the workflow's current title-block-stripped
    hashes against the ones persisted in the existing version-page
    front-matter.  When both match, any SCH/PCB mtime bump is a
    title-block-only edit (COMMENT9 status change, revision bump,
    designer field, etc.) and the M1 asset-freshness escalation must
    NOT force a full publish — the outcome stays at ``refresh`` (or
    ``noop`` when the front-matter is byte-for-byte identical).

    Args:
        site_repo: Local site-repo checkout.
        project: Project basename (``<P>``).
        board_rev: Board revision (``<R>``).
        current_sch_hash: Current SCH title-block-stripped hash.
        current_pcb_hash: Current PCB title-block-stripped hash.

    Returns:
        ``True`` when the existing version file contains persisted
        hashes and both match the current hashes; ``False`` otherwise
        (including when no persisted hashes exist yet).
    """
    version_file = site_repo / "_versions" / project / f"{board_rev}.md"
    if not version_file.exists():
        return False
    stored_sch, stored_pcb = _read_stored_source_hashes(version_file)
    if not stored_sch and not stored_pcb:
        # No hashes were persisted (older publish before M11 round-2
        # landed, or hashes were manually stripped).  Fall back to the
        # M1 mtime-only behaviour: return False so the caller escalates.
        return False
    return stored_sch == current_sch_hash and stored_pcb == current_pcb_hash


def _read_stored_source_hashes(version_file: Path) -> tuple[str, str]:
    """Extract ``kproj_source_hashes.{sch,pcb}`` from a version file's front-matter.

    Parses the YAML block delimited by ``---`` markers.  Missing keys
    or an unparseable front-matter yield empty-string sentinels so the
    caller treats them as "no persisted hash".

    Args:
        version_file: Path to a ``_versions/<P>/<R>.md`` file.

    Returns:
        A ``(sch, pcb)`` string tuple.  Either element is ``""`` when
        the corresponding key is absent.
    """
    import yaml

    try:
        text = version_file.read_text(encoding="utf-8")
    except OSError:
        return "", ""
    if not text.startswith("---"):
        return "", ""
    # Split off the front-matter block between the leading ``---`` and
    # the next ``---`` line.
    parts = text.split("---", 2)
    if len(parts) < 3:
        return "", ""
    yaml_block = parts[1]
    try:
        data = yaml.safe_load(yaml_block)
    except yaml.YAMLError:
        return "", ""
    if not isinstance(data, dict):
        return "", ""
    hashes = data.get("kproj_source_hashes")
    if not isinstance(hashes, dict):
        return "", ""
    return str(hashes.get("sch", "") or ""), str(hashes.get("pcb", "") or "")


def _assets_are_stale(
    *,
    images: tuple[AssetRef, ...],
    artifacts: tuple[AssetRef, ...],
    resolved: ResolvedProject,
    site_repo: Path,
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
        asset_path = site_repo / ref.path.lstrip("/")
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
    site_repo: Path,
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
        site_repo: Local site-repo checkout.
        journal: Open :class:`ChangeJournal` for rollback tracking.

    Returns:
        A 3-tuple ``(images, artifacts, diagnostics)`` where
        ``diagnostics`` is the accumulated union of
        :attr:`ExportResult.diagnostics` from every producer that ran
        (wave-3 M6 fix-up).
    """
    pcb_exporter = PcbExporter(kicad_cli)
    sch_exporter = SchematicExporter(kicad_cli)
    ibom_gen = IbomGenerator(ibom_script)
    archiver = ZipArchiver()
    fab_packager = FabPackager(archiver)
    source_packager = SourcePackager(archiver)

    P = project_info.project
    R = project_info.board_rev
    PR = f"{P}-{R}"
    asset_dir = site_repo / "versions" / P / R
    asset_dir.mkdir(parents=True, exist_ok=True)

    base_site = f"/versions/{P}/{R}"

    diagnostics: list[Finding] = []

    # PCB renders
    top_path = asset_dir / f"{PR}.top.png"
    diagnostics.extend(
        pcb_exporter.export_render(resolved.pcb_file, "top", top_path, journal=journal).diagnostics
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
        ibom_gen.generate(resolved.pcb_file, ibom_path, f"{PR}.ibom", journal=journal).diagnostics
    )

    # Fab pack (optional — skipped when production/ is missing)
    prod_dir = resolved.project_dir / "production"
    fab_result = fab_packager.package(
        prod_dir,
        asset_dir / f"{PR}.fab.zip",
        title=P,
        rev=R,
        pcb_path=resolved.pcb_file,
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
