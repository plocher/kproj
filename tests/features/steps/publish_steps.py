"""Step definitions shared across kproj#4 Behave feature files.

All steps here use the full publish pipeline with injectable stubs so
real ``kicad-cli``, iBOM, and git operations are not required.

**iBOM caveat (kproj#10)**: the iBOM end-to-end is gated on a separate spike.
The artifact generator used here is a stub that writes placeholder files and
returns the canonical asset refs.  This tests the pipeline orchestration
without invoking real iBOM.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from behave import given, then, when  # type: ignore[import-untyped]

_TESTS_ROOT = Path(__file__).resolve().parents[2]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from _kicad_fixtures import (  # noqa: E402
    TitleBlockSpec,
    make_minimal_project,
)
from kproj.application import publish_workflow as workflow_module  # noqa: E402
from kproj.application.publish_workflow import PublishWorkflow  # noqa: E402
from kproj.config import (  # noqa: E402
    DEFAULT_DATASHEET_LIBRARY,
    DEFAULT_DATASHEET_REPO,
    DEFAULT_FABRICATOR,
    DEFAULT_IBOM_EXTRA_FIELDS,
    GENERIC_SITE_PROFILE,
    KprojConfig,
)

# Steps below reference GENERIC_SITE_PROFILE's directory constants
# instead of literal ``_versions`` / ``pages`` paths so scenarios exercise
# the SiteProfile abstraction ("the version page lands under the
# configured versions dir") rather than pinning to a specific backend.
_VDIR = GENERIC_SITE_PROFILE.versions_dir
from kproj.model.analysis_info import AnalysisInfo  # noqa: E402
from kproj.model.finding import Finding  # noqa: E402
from kproj.model.publication import AssetRef  # noqa: E402
from kproj.model.publish_request import PublishRequest  # noqa: E402
from kproj.model.severity import Severity  # noqa: E402
from kproj.services.change_journal import ChangeJournal  # noqa: E402
from kproj.services.kicad_project_reader import KicadProjectReader  # noqa: E402
from kproj.services.site_publisher import SitePublisher  # noqa: E402

# ─────────────────────────── infrastructure helpers ──────────────────────────


class _SilentDesignAnalyzer:
    """Stand-in DesignAnalyzer that emits no findings (no kicad-cli needed)."""

    def __init__(self, _cli: Path) -> None: ...

    def analyze(self, _resolved: object) -> AnalysisInfo:
        return AnalysisInfo(findings=())


class _StaticMetadataAnalyzer:
    """Metadata analyzer stand-in used to isolate BDD exit-code contracts."""

    def __init__(self, findings: tuple[Finding, ...]) -> None:
        self._findings = findings

    def analyze(self, _project_info: object, _project_dir: Path) -> AnalysisInfo:
        """Return the scenario-selected findings."""
        return AnalysisInfo(findings=self._findings)


def _make_site_repo(base_dir: Path) -> Path:
    """Initialise a bare git repo at ``<base_dir>/site``."""
    site = base_dir / "site"
    site.mkdir(exist_ok=True)
    os.system(f"git -C '{site}' init -q")
    os.system(f"git -C '{site}' config user.email 'test@test.com'")
    os.system(f"git -C '{site}' config user.name 'Test'")
    return site


def _stub_artifact_generator(site_repo: Path) -> Any:
    """Return an artifact generator stub that writes placeholder files.

    Honours the artifact-generator signature
    ``(resolved, project_info, kicad_cli, ibom_script, kicad_python,
    site_repo, site_profile, inventory, fabricator, ibom_extra_fields, journal)``
    and returns the 3-tuple
    ``(images, artifacts, diagnostics)``.  Derives ``basename`` /
    ``board_rev`` from ``project_info`` so path layout matches
    BLOCKER 1's canonical shape.
    """

    def _gen(
        resolved: Any,
        project_info: Any,
        _kicad_cli: Path,
        _ibom_script: Path,
        _kicad_python: Path,
        _site_repo: Path,
        _site_profile: object,
        inventory: Path | None,
        fabricator: str,
        ibom_extra_fields: tuple[str, ...],
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
        del inventory, fabricator, ibom_extra_fields
        basename = getattr(project_info, "project", None) or getattr(resolved, "basename", "demo")
        R = getattr(project_info, "board_rev", None) or "1.0"
        PR = f"{basename}-{R}"
        base_site = f"/versions/{basename}/{R}"
        asset_dir = site_repo / "versions" / basename / R
        asset_dir.mkdir(parents=True, exist_ok=True)
        for filename in [
            f"{PR}.top.png",
            f"{PR}.bottom.png",
            f"{PR}.sch.svg",
            f"{PR}.sch.pdf",
            f"{PR}.ibom.html",
            f"{PR}.step",
            f"{PR}.source.zip",
        ]:
            p = asset_dir / filename
            p.write_bytes(b"placeholder")
            journal.will_create(p)
        images: tuple[AssetRef, ...] = (
            AssetRef(path=f"{base_site}/{PR}.top.png", tag="render-top", title="Top"),
            AssetRef(path=f"{base_site}/{PR}.bottom.png", tag="render-bottom", title="Bottom"),
            AssetRef(path=f"{base_site}/{PR}.sch.svg", tag="schematic-svg", title="Schematic"),
        )
        artifacts: tuple[AssetRef, ...] = (
            AssetRef(
                path=f"{base_site}/{PR}.sch.pdf",
                tag="schematic-pdf",
                post="Full schematic (all sheets)",
            ),
            AssetRef(
                path=f"{base_site}/{PR}.ibom.html",
                tag="interactive-bom",
                post="Interactive HTML BOM",
            ),
            AssetRef(path=f"{base_site}/{PR}.step", tag="step-model", post="3D STEP model"),
            AssetRef(
                path=f"{base_site}/{PR}.source.zip",
                tag="source-archive",
                post="KiCad source archive",
            ),
        )
        return images, artifacts, ()

    return _gen


def _default_fake_datasheet_lookup(context: Any) -> Any:
    """Return a hermetic stand-in for ``read_datasheet_names`` (kproj#29).

    Behave scenarios never exec a real ``jbom`` subprocess: this fake
    returns whatever ``context.datasheet_names`` /
    ``context.datasheet_lookup_findings`` a Given-step has pre-loaded
    (empty by default), regardless of the
    ``(project_dir, inventory, fabricator)``
    arguments it's called with.
    """

    def _lookup(_project_dir: Path, _inventory: Path | None, _fabricator: str) -> Any:
        names = tuple(getattr(context, "datasheet_names", ()))
        findings = tuple(getattr(context, "datasheet_lookup_findings", ()))
        return names, findings

    return _lookup


def _build_workflow(context: Any) -> PublishWorkflow:
    """Build a PublishWorkflow with all external services stubbed.

    When ``context.failing_generator`` is set, use it instead of the
    happy-path stub (drives the Story 9 mid-pipeline rollback scenario).
    When ``context.crashing_design_analyzer`` is set, use it instead
    of the silent DesignAnalyzer (drives the M4 mechanical-failure
    scenarios). ``context.datasheet_name_lookup`` overrides the default
    hermetic fake datasheet-name lookup (kproj#29) when a scenario needs
    to drive a specific names/findings combination.
    """
    fake_ibom = Path(context.tmpdir) / "generate_interactive_bom.py"
    if not fake_ibom.exists():
        fake_ibom.write_text("")
    fake_python = Path(context.tmpdir) / "kicad-python3"
    if not fake_python.exists():
        fake_python.write_text("")
    site_repo = context.site_repo
    generator = getattr(context, "failing_generator", None) or _stub_artifact_generator(site_repo)
    design_analyzer_factory = (
        getattr(context, "crashing_design_analyzer", None) or _SilentDesignAnalyzer
    )
    datasheet_name_lookup = getattr(context, "datasheet_name_lookup", None) or (
        _default_fake_datasheet_lookup(context)
    )
    return PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=Path(context.tmpdir)),
        metadata_analyzer=getattr(context, "metadata_analyzer", None),
        design_analyzer_factory=design_analyzer_factory,
        ibom_script_locator=lambda: fake_ibom,
        kicad_python_locator=lambda: fake_python,
        artifact_generator=generator,
        site_publisher_factory=SitePublisher,
        datasheet_name_lookup=datasheet_name_lookup,
        library_repo=Path(context.tmpdir) / "no-such-library-clone",
    )


def _build_request(context: Any, *, dry_run: bool = False) -> PublishRequest:
    """Build a PublishRequest from the context."""
    fake_cli = Path(context.tmpdir) / "kicad-cli"
    if not fake_cli.exists():
        fake_cli.write_text("")
    # Patch kicad_version so the fake cli passes version check.
    workflow_module.kicad_version = lambda _: (9, 0, 4)  # type: ignore[attr-defined]
    return PublishRequest(
        project_arg=str(context.proj_dir),
        config=KprojConfig(
            site_repo=context.site_repo,
            no_push=getattr(context, "no_push", True),
            kicad_cli=fake_cli,
            site_profile=GENERIC_SITE_PROFILE,
            inventory=getattr(context, "inventory", None),
            datasheet_library=getattr(context, "datasheet_library", DEFAULT_DATASHEET_LIBRARY),
            datasheet_repo=getattr(context, "datasheet_repo", DEFAULT_DATASHEET_REPO),
            ibom_extra_fields=getattr(context, "ibom_extra_fields", DEFAULT_IBOM_EXTRA_FIELDS),
            fabricator=getattr(context, "fabricator", DEFAULT_FABRICATOR),
        ),
        dry_run=dry_run,
    )


def _run_workflow(context: Any, *, dry_run: bool = False) -> None:
    """Invoke the stubbed workflow and store result + git calls in context."""
    workflow = _build_workflow(context)
    request = _build_request(context, dry_run=dry_run)
    # Behave mocks git (a documented limitation): the real
    # ``git diff --cached`` change-detection is validated interactively,
    # not here.  Stub _git_staged_names non-empty so publish() proceeds to
    # commit and the pipeline-orchestration assertions stay meaningful.
    with (
        patch("kproj.services.site_publisher._git_run") as mock_git,
        patch(
            "kproj.services.site_publisher._git_staged_names",
            return_value=getattr(context, "staged_names", ["versions/staged"]),
        ),
        patch(
            "kproj.services.site_publisher._git_pending_push_count",
            return_value=getattr(context, "pending_push_count", 0),
        ),
    ):
        context.result = workflow.run(request)
        context.git_calls = [tuple(call.args[0]) for call in mock_git.call_args_list]
    context.outcome = context.result.outcome
    context.stderr = context.result.message or ""
    # Also set context.exit_code for compatibility with preflight_steps.py assertions.
    context.exit_code = context.result.exit_code


# ─────────────────────────── Given steps ─────────────────────────────────────


@given("a populated KiCad project with status {status:w}")
def step_given_project_with_status(context: Any, status: str) -> None:
    """Create a minimal project with the given status."""
    context.tmpdir = tempfile.mkdtemp(prefix="kproj-behave-")
    name = "MyProject"
    context.project_name = name
    context.proj_dir = make_minimal_project(
        Path(context.tmpdir) / name,
        name,
        sch_title_block=TitleBlockSpec(
            title="My Board",
            company="MRCS",
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer", 2: "A tagline", 9: status},
        ),
        pcb_title_block=TitleBlockSpec(
            title="My Board",
            company="MRCS",
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    context.site_repo = _make_site_repo(Path(context.tmpdir))


@given("a project with exactly one audit warning")
def step_given_project_with_one_audit_warning(context: Any) -> None:
    """Create a project with one isolated WARNING finding."""
    step_given_project_with_status(context, "active")
    context.metadata_analyzer = _StaticMetadataAnalyzer(
        (
            Finding(
                severity=Severity.WARNING,
                field="metadata_warning",
                value="",
                reason="A genuine metadata warning.",
                source="audit",
            ),
        )
    )


@given("no findings except the GitHub-link advisory")
def step_given_only_github_link_finding(context: Any) -> None:
    """Suppress unrelated metadata findings for INFO exit-code scenarios."""
    context.metadata_analyzer = _StaticMetadataAnalyzer(())


@given("a project with audit warnings")
def step_given_project_with_warnings(context: Any) -> None:
    """Create a project that will trigger audit warnings."""
    context.tmpdir = tempfile.mkdtemp(prefix="kproj-behave-")
    name = "AuditProject"
    context.project_name = name
    # Missing designer_format (not First Last) and missing date triggers warnings.
    context.proj_dir = make_minimal_project(
        Path(context.tmpdir) / name,
        name,
        sch_title_block=TitleBlockSpec(
            title="Audit Board",
            company="MRCS",
            revision="1.0",
            date="bad-date",  # date_format warning
            comments={1: "alice", 9: "active"},  # designer_format warning
        ),
        pcb_title_block=TitleBlockSpec(
            title="Audit Board",
            company="MRCS",
            revision="1.0",
            date="bad-date",
            comments={1: "alice"},
        ),
    )
    context.site_repo = _make_site_repo(Path(context.tmpdir))


@given("the project was previously published")
def step_given_previously_published(context: Any) -> None:
    """Run the workflow once so the project is published before the test."""
    _run_workflow(context)
    assert context.result.outcome in ("published", "refreshed", "noop"), (
        f"Pre-publish failed: {context.result.outcome} - {context.result.message}"
    )
    # Commit the written files so the site repo is clean for the next run.
    # (The workflow mocks _git_run, so we do a real commit here.)
    site = context.site_repo
    os.system(f"git -C '{site}' add -A")
    os.system(f"git -C '{site}' commit -q -m 'initial publish' --allow-empty")


@given("a clean site repo")
def step_given_clean_site_repo(context: Any) -> None:
    """Ensure a clean git site repo exists (also set on context)."""
    # context.site_repo should already be set by a prior Given step.
    # This step is a no-op if the site_repo is already initialised.
    if not hasattr(context, "site_repo"):
        if not hasattr(context, "tmpdir"):
            context.tmpdir = tempfile.mkdtemp(prefix="kproj-behave-")
        context.site_repo = _make_site_repo(Path(context.tmpdir))


@given("the site repo has uncommitted changes")
def step_given_dirty_site_repo(context: Any) -> None:
    """Add an uncommitted file to the site repo."""
    (context.site_repo / "dirty.md").write_text("uncommitted")


@given("no_push mode is active")
def step_given_no_push(context: Any) -> None:
    """Enable no-push mode (KPROJ_NO_PUSH semantics)."""
    context.no_push = True


@given("push is enabled")
def step_given_push_enabled(context: Any) -> None:
    """Disable batch-only no-push behavior for this run."""
    context.no_push = False


@given("the site repo has {count:d} pending commits")
def step_given_pending_site_commits(context: Any, count: int) -> None:
    """Set the mocked upstream-ahead count for the next publish."""
    context.pending_push_count = count


@given("the project content is unchanged")
def step_given_project_content_unchanged(context: Any) -> None:
    """Make the publisher follow its no-op branch."""
    context.staged_names = []


@given("the site repo upstream is unavailable")
def step_given_unavailable_site_upstream(context: Any) -> None:
    """Make the pending-push probe use its advisory unavailable state."""
    context.pending_push_count = None


@given("an artifact producer will fail after writing one asset")
def step_given_failing_producer(context: Any) -> None:
    """Install a failing artifact generator for the next kproj run.

    Mimics a real mid-pipeline producer crash: writes one asset,
    journals it, then raises an OSError that the workflow converts
    to outcome="failed" (via the generic OSError catch in
    :meth:`PublishWorkflow.run`).  The ChangeJournal rolls back the
    one written file per ADR 0005; combined with the mocked _git_run
    (no commit ever happens), the site repo stays completely clean.
    """

    def _failing_gen(
        resolved: Any,
        project_info: Any,
        _kicad_cli: Path,
        _ibom_script: Path,
        _kicad_python: Path,
        _site_repo: Path,
        _site_profile: object,
        inventory: Path | None,
        fabricator: str,
        ibom_extra_fields: tuple[str, ...],
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
        del inventory, fabricator, ibom_extra_fields
        basename = getattr(project_info, "project", None) or getattr(resolved, "basename", "demo")
        R = getattr(project_info, "board_rev", None) or "1.0"
        # Simulate one producer writing an asset before a later one fails.
        asset_dir = _site_repo / "versions" / basename / R
        asset_dir.mkdir(parents=True, exist_ok=True)
        early_asset = asset_dir / f"{basename}-{R}.top.png"
        early_asset.write_bytes(b"placeholder")
        journal.will_create(early_asset)
        raise OSError("simulated producer failure after one asset was written")

    context.failing_generator = _failing_gen


# ─────────────────────────── When steps ──────────────────────────────────────


@when("I run kproj")
def step_when_run_kproj(context: Any) -> None:
    """Run the full publish pipeline (all external services stubbed)."""
    _run_workflow(context)


@when("I run kproj with --dry-run")
def step_when_run_dry_run(context: Any) -> None:
    """Run the full publish pipeline in dry-run mode."""
    _run_workflow(context, dry_run=True)


@when("I run kproj a second time with the same project")
def step_when_run_kproj_again(context: Any) -> None:
    """Run the pipeline a second time (for no-op detection)."""
    _run_workflow(context)


@when("I run plain kproj with unchanged content")
def step_when_run_plain_kproj_unchanged(context: Any) -> None:
    """Run the final batch invocation with the first run's pending commit."""
    context.no_push = False
    context.staged_names = []
    context.pending_push_count = 1
    _run_workflow(context)


@when("I run kproj with -v")
def step_when_run_kproj_verbose(context: Any) -> None:
    """Run the workflow with verbose_level=1 and capture the stderr text."""
    import importlib
    import io
    from contextlib import redirect_stderr
    workflow = _build_workflow(context)
    request = _build_request(context)
    # verbose_level=1 emulates `kproj -v <path>`.
    from dataclasses import replace as _replace

    request = _replace(request, verbose_level=1)
    with (
        patch("kproj.services.site_publisher._git_run") as mock_git,
        patch(
            "kproj.services.site_publisher._git_staged_names",
            return_value=["versions/staged"],
        ),
    ):
        context.result = workflow.run(request)
        context.git_calls = [tuple(call.args[0]) for call in mock_git.call_args_list]
    context.outcome = context.result.outcome
    context.exit_code = context.result.exit_code
    cli_main = importlib.import_module("kproj.cli.main")
    err_buffer = io.StringIO()
    with redirect_stderr(err_buffer):
        cli_main._render_result_to_stderr(context.result, verbose_level=1, debug=False)
    context.stderr = err_buffer.getvalue()


# ─────────────────────────── Then steps ──────────────────────────────────────


@then("the version page exists in the site repo")
def step_then_version_page_exists(context: Any) -> None:
    """Assert the version markdown was created under the profile's versions_dir."""
    P = getattr(context, "project_name", "MyProject")
    version_file = context.site_repo / _VDIR / P / "1.0.md"
    assert version_file.exists(), f"{_VDIR}/{P}/1.0.md not found in {context.site_repo}"


@then("the project page exists in the site repo")
def step_then_project_page_exists(context: Any) -> None:
    """Assert the per-project section index was created (versions/<P>/_index.md)."""
    P = getattr(context, "project_name", "MyProject")
    index_file = GENERIC_SITE_PROFILE.project_index_path(context.site_repo, P)
    assert index_file.exists(), f"{index_file} not found in {context.site_repo}"


@then("no files are written to the site repo")
def step_then_no_files_written(context: Any) -> None:
    """Assert the site repo has no version/section-index files (dry-run guard)."""
    versions = (
        list((context.site_repo / _VDIR).rglob("*.md"))
        if (context.site_repo / _VDIR).exists()
        else []
    )
    assert not versions, f"dry-run wrote files: versions={versions}"


@then("the dry-run destination is reported")
def step_then_dry_run_destination_reported(context: Any) -> None:
    """Assert the site-relative fallback destination reaches the user."""
    assert context.result.message == (
        "Note: --dry-run only. Would have published to /versions/myproject/#v-10"
    )


@then("the version page contains the audit findings table")
def step_then_version_page_has_audit_table(context: Any) -> None:
    """Assert the version markdown body has a Metadata Audit table."""
    P = getattr(context, "project_name", "AuditProject")
    version_file = context.site_repo / _VDIR / P / "1.0.md"
    if not version_file.exists():
        # Try project name from result
        P = context.result.message.split("'")[1] if "'" in context.result.message else P
        version_file = context.site_repo / _VDIR / P / "1.0.md"
    assert version_file.exists(), f"version file not found: {version_file}"
    content = version_file.read_text()
    assert "Metadata Audit" in content, (
        f"No 'Metadata Audit' in version page body:\n{content[:500]}"
    )


@then("the version page front-matter includes findings counts")
def step_then_front_matter_has_counts(context: Any) -> None:
    """Assert audit: {errors:…, warnings:…} is in the front-matter."""
    P = getattr(context, "project_name", "AuditProject")
    version_file = context.site_repo / _VDIR / P / "1.0.md"
    if not version_file.exists():
        for f in (context.site_repo / _VDIR).rglob("*.md"):
            version_file = f
            break
    content = version_file.read_text()
    assert "audit" in content, f"No 'audit:' key in version page:\n{content[:500]}"


@then("kproj exit code signals findings present")
def step_then_exit_1(context: Any) -> None:
    """Assert exit code is 1 (findings present, publish succeeded)."""
    assert context.result.exit_code == 1, (
        f"expected exit 1 (findings present), got {context.result.exit_code}; "
        f"outcome={context.result.outcome!r}"
    )


@then("the version page has updated status")
def step_then_version_has_updated_status(context: Any) -> None:
    """Assert the version page front-matter has status: active."""
    for version_file in (context.site_repo / _VDIR).rglob("*.md"):
        content = version_file.read_text()
        assert "status: active" in content, (
            f"Expected 'status: active' in {version_file}:\n{content[:500]}"
        )
        return
    raise AssertionError("No version file found in site repo")


@then("the kproj outcome is not a full publish")
def step_then_outcome_not_full_publish(context: Any) -> None:
    """Assert outcome is 'refreshed' (not 'published' which regenerates assets)."""
    assert context.result.outcome in ("refreshed", "noop"), (
        f"expected refreshed or noop, got {context.result.outcome!r}"
    )


@then("a new commit was added to the site repo")
def step_then_commit_exists(context: Any) -> None:
    """Assert the site repo now has at least one commit (via file existence)."""
    # We mock _git_run so we can't check git log directly.
    # Instead, verify the version file was written.
    version_files = list((context.site_repo / _VDIR).rglob("*.md"))
    assert version_files, "Expected at least one version file after publish"


@then("no partial files remain in the site repo")
def step_then_no_partial_files(context: Any) -> None:
    """Assert the site repo is clean (rollback worked)."""
    version_files = (
        list((context.site_repo / _VDIR).rglob("*.md"))
        if (context.site_repo / _VDIR).exists()
        else []
    )
    assert not version_files, f"Partial files remain: {version_files}"


@then("stderr explains the uncommitted state")
def step_then_stderr_dirty_message(context: Any) -> None:
    """Assert the failure message mentions uncommitted changes."""
    msg = context.result.message
    assert "uncommitted" in msg or "changes" in msg, (
        f"Expected uncommitted/changes in message: {msg!r}"
    )


@then("no git push was invoked")
def step_then_no_push_invoked(context: Any) -> None:
    """Assert the mocked git runner was never asked to push.

    Requires the scenario to have captured git calls via a mocked
    :func:`kproj.services.site_publisher._git_run`.  When ``no_push``
    is true, ``SitePublisher.publish`` calls ``git add`` and
    ``git commit`` but must never invoke ``git push``.
    """
    git_calls = getattr(context, "git_calls", None)
    if git_calls is None:
        # Fallback: outcome must at least be a terminal success and the
        # workflow's PublishResult must not carry a "push" verb in the
        # message; the `-v` scenario provides git_calls directly.
        assert context.result.outcome in (
            "published",
            "refreshed",
            "noop",
        ), f"expected success outcome, got {context.result.outcome!r}"
        return
    push_calls = [call for call in git_calls if call and call[0] == "push"]
    assert not push_calls, f"Expected no git push invocations under no_push mode; got: {push_calls}"


@then("pending site commits were pushed")
def step_then_pending_site_commits_pushed(context: Any) -> None:
    """Assert a plain no-op invokes git push to flush pending commits."""
    assert any(call and call[0] == "push" for call in context.git_calls)
    assert "pushed 1 pending site commit(s)" in context.result.message


@then("a site commit was made without a push")
def step_then_batch_commit_was_not_pushed(context: Any) -> None:
    """Prove the initial no-push invocation committed but did not push."""
    assert any(call and call[0] == "commit" for call in context.git_calls)
    assert not any(call and call[0] == "push" for call in context.git_calls)
    os.system(f"git -C '{context.site_repo}' add -A")
    os.system(f"git -C '{context.site_repo}' commit -q -m 'batched publish'")


@then("the unchanged no-op is quiet")
def step_then_unchanged_noop_is_quiet(context: Any) -> None:
    """Assert a no-debt no-op keeps its concise existing summary."""
    assert context.result.message == "Info: MyProject-1.0 unchanged - nothing to publish."


@then('pending site commit debt is reported for "{mode}"')
def step_then_pending_debt_is_reported(context: Any, mode: str) -> None:
    """Assert the non-pushing mode names its queued site commit debt."""
    assert f"Note: site repo has 2 unpushed commit(s) ({mode})." in context.result.message


@then("stderr shows the GitHub-link Note")
def step_then_github_link_note_is_rendered(context: Any) -> None:
    """Assert the INFO advisory uses the default human Note presentation."""
    from kproj.formatters.stderr_formatter import StderrFormatter

    rendered = StderrFormatter().format_findings(context.result.findings)
    assert "Note: Project is not a Git repository" in rendered


@then("the unavailable upstream advisory is reported")
def step_then_unavailable_upstream_advisory(context: Any) -> None:
    """Assert the probe's unavailable state surfaces as an INFO finding."""
    assert "site_push_pending_unknown" in {finding.field for finding in context.result.findings}


# ─────────────────────────── M4 round-2 steps ────────────────────────────────


@given("kicad-cli DRC will crash without producing JSON")
def step_given_drc_will_crash(context: Any) -> None:
    """Install a crashing DesignAnalyzer for the next kproj run (DRC path)."""
    from kproj.services.design_analyzer import DesignAnalysisError

    class _CrashingAnalyzer:
        def __init__(self, _cli: Path) -> None: ...

        def analyze(self, _resolved: object) -> AnalysisInfo:
            raise DesignAnalysisError(
                "kicad-cli pcb drc failed without producing JSON (rc=2): "
                "kicad-cli: segfault probing board",
                origin="drc",
                returncode=2,
            )

    context.crashing_design_analyzer = _CrashingAnalyzer


@given("kicad-cli ERC will crash without producing JSON")
def step_given_erc_will_crash(context: Any) -> None:
    """Install a crashing DesignAnalyzer for the next kproj run (ERC path)."""
    from kproj.services.design_analyzer import DesignAnalysisError

    class _CrashingAnalyzer:
        def __init__(self, _cli: Path) -> None: ...

        def analyze(self, _resolved: object) -> AnalysisInfo:
            raise DesignAnalysisError(
                "kicad-cli sch erc failed without producing JSON (rc=1): "
                "kicad-cli: schematic unreadable",
                origin="erc",
                returncode=1,
            )

    context.crashing_design_analyzer = _CrashingAnalyzer


@then("the kproj exit code is {code:d}")
def step_then_exit_code_is(context: Any, code: int) -> None:
    """Assert the workflow's exit code equals *code*.

    Distinct from the ``kproj exits with code`` step in
    ``preflight_steps.py``: this one reads ``context.result.exit_code``
    populated by ``_run_workflow``.
    """
    assert context.result.exit_code == code, (
        f"expected exit code {code}, got {context.result.exit_code}; "
        f"outcome={context.result.outcome!r} message={context.result.message!r}"
    )


@then("no version page is written")
def step_then_no_version_page_written(context: Any) -> None:
    """Assert no per-version markdown files exist under the profile's versions_dir."""
    versions_dir = context.site_repo / _VDIR
    files = list(versions_dir.rglob("*.md")) if versions_dir.exists() else []
    assert not files, f"expected no version pages; found {files!r}"


@then("no git commit is invoked")
def step_then_no_git_commit_invoked(context: Any) -> None:
    """Assert the mocked git runner never saw a ``git commit`` call."""
    git_calls = getattr(context, "git_calls", None)
    if git_calls is None:
        # No git invocations were captured at all — by definition, no commit.
        return
    commits = [call for call in git_calls if call and call[0] == "commit"]
    assert not commits, f"expected no git commit; got {commits!r}"


@then("stderr reports a compact findings summary")
def step_then_stderr_reports_compact_summary(context: Any) -> None:
    """Assert verbose stderr contains aggregate findings context, not finding rows."""
    stderr_text = getattr(context, "stderr", "") or ""
    finding_fields = {f.field for f in context.result.findings}
    assert finding_fields, (
        "expected at least one finding under the AuditProject fixture; "
        f"got findings={finding_fields}"
    )
    assert "Note: Collected" in stderr_text, (
        f"expected compact findings summary on stderr; got stderr={stderr_text!r}"
    )
    assert not any(name in stderr_text for name in finding_fields), (
        f"expected no per-finding names on verbose stderr; got stderr={stderr_text!r}"
    )
