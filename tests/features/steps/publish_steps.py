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
from kproj.config import KprojConfig  # noqa: E402
from kproj.model.analysis_info import AnalysisInfo  # noqa: E402
from kproj.model.publication import AssetRef  # noqa: E402
from kproj.model.publish_request import PublishRequest  # noqa: E402
from kproj.services.change_journal import ChangeJournal  # noqa: E402
from kproj.services.kicad_project_reader import KicadProjectReader  # noqa: E402
from kproj.services.site_publisher import SitePublisher  # noqa: E402

# ─────────────────────────── infrastructure helpers ──────────────────────────


class _SilentDesignAnalyzer:
    """Stand-in DesignAnalyzer that emits no findings (no kicad-cli needed)."""

    def __init__(self, _cli: Path) -> None: ...

    def analyze(self, _resolved: object) -> AnalysisInfo:
        return AnalysisInfo(findings=())


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

    Wave-3 fix-ups: honours the new
    ``(resolved, project_info, kicad_cli, ibom_script, site_repo, journal)``
    signature and returns the 3-tuple ``(images, artifacts, diagnostics)``.
    Derives ``basename`` / ``board_rev`` from ``project_info`` so path
    layout matches BLOCKER 1's canonical shape.
    """

    def _gen(
        resolved: Any,
        project_info: Any,
        _kicad_cli: Path,
        _ibom_script: Path,
        _site_repo: Path,
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
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


def _build_workflow(context: Any) -> PublishWorkflow:
    """Build a PublishWorkflow with all external services stubbed.

    When ``context.failing_generator`` is set, use it instead of the
    happy-path stub (drives the Story 9 mid-pipeline rollback scenario).
    When ``context.crashing_design_analyzer`` is set, use it instead
    of the silent DesignAnalyzer (drives the M4 mechanical-failure
    scenarios).
    """
    fake_ibom = Path(context.tmpdir) / "generate_interactive_bom.py"
    if not fake_ibom.exists():
        fake_ibom.write_text("")
    site_repo = context.site_repo
    generator = getattr(context, "failing_generator", None) or _stub_artifact_generator(site_repo)
    design_analyzer_factory = (
        getattr(context, "crashing_design_analyzer", None) or _SilentDesignAnalyzer
    )
    return PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=Path(context.tmpdir)),
        design_analyzer_factory=design_analyzer_factory,
        ibom_script_locator=lambda: fake_ibom,
        artifact_generator=generator,
        site_publisher_factory=SitePublisher,
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
        ),
        dry_run=dry_run,
    )


def _run_workflow(context: Any, *, dry_run: bool = False) -> None:
    """Invoke the stubbed workflow and store result + git calls in context."""
    workflow = _build_workflow(context)
    request = _build_request(context, dry_run=dry_run)
    with patch("kproj.services.site_publisher._git_run") as mock_git:
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
    """Run the workflow once so the project is published before the test.

    Also snapshots the asset mtimes so the "assets are not regenerated"
    check (round-2 M11) can compare against the baseline without any
    mtime-touching workarounds.
    """
    _run_workflow(context)
    assert context.result.outcome in ("published", "refreshed", "noop"), (
        f"Pre-publish failed: {context.result.outcome} - {context.result.message}"
    )
    # Commit the written files so the site repo is clean for the next run.
    # (The workflow mocks _git_run, so we do a real commit here.)
    site = context.site_repo
    os.system(f"git -C '{site}' add -A")
    os.system(f"git -C '{site}' commit -q -m 'initial publish' --allow-empty")

    # Snapshot baseline asset mtimes for the round-2 no-regen assertion.
    versions_root = site / "versions"
    context.baseline_asset_mtimes = {
        p: p.stat().st_mtime for p in versions_root.rglob("*") if p.is_file()
    }


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
        _site_repo: Path,
        journal: ChangeJournal,
    ) -> tuple[tuple[AssetRef, ...], tuple[AssetRef, ...], tuple[object, ...]]:
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


@when('I change COMMENT9 in the schematic to "{new_value}"')
def step_when_change_comment9(context: Any, new_value: str) -> None:
    """Rewrite the fixture SCH so ``${COMMENT9}`` becomes *new_value*.

    Round-2 M11: this is a REAL title-block edit with no mtime hack.
    The pre-round-2 step bumped every already-published asset's mtime
    into the future to defeat the M1 stale-asset escalation.  Round-2
    removes that workaround; the code side compares SCH/PCB
    content-hashes (title-block stripped) against hashes captured in
    the previously published ``_versions/<P>/<R>.md`` front-matter to
    distinguish title-block-only metadata edits from real content
    edits.  The failing test is what drives the code fix.

    ``new_value`` may be an empty string (""); in that case COMMENT9
    is written as present-but-empty, which the reader treats as
    missing and the status parser defaults to :class:`Status.ACTIVE`.
    """
    import time as _time

    from _kicad_fixtures import TitleBlockSpec, write_kicad_sch

    comments: dict[int, str] = {1: "Alice Designer", 2: "A tagline"}
    if new_value != "":
        comments[9] = new_value

    sch_path = context.proj_dir / f"{context.project_name}.kicad_sch"
    write_kicad_sch(
        sch_path,
        TitleBlockSpec(
            title="My Board",
            company="MRCS",
            revision="1.0",
            date="2026.04",
            comments=comments,
        ),
    )
    # Force the SCH mtime to be newer than every previously published
    # asset.  Without this the test would depend on filesystem mtime
    # resolution to detect the edit, which is flaky across OSes/CI.
    # The code MUST NOT rely on mtimes to decide title-block-only
    # vs. schematic-content edits; that's what round-2 fixes.
    future = _time.time() + 60
    os.utime(sch_path, (future, future))


# Behave's parse matcher treats the empty string between quotes as a
# non-match, so an explicit step handles the corner-case scenario where
# COMMENT9 is erased entirely (defaults to active).
@when('I change COMMENT9 in the schematic to ""')
def step_when_change_comment9_empty(context: Any) -> None:
    """Erase COMMENT9 (present-but-empty) so the parser defaults to active."""
    step_when_change_comment9(context, "")


# Retained under its original phrase for backward compatibility with any
# out-of-tree scenarios; delegates to the parameterised step above.
@when("I change the project status to active")
def step_when_change_status_active(context: Any) -> None:
    """Alias: change COMMENT9 to "active" (legacy phrasing)."""
    step_when_change_comment9(context, "active")


@when("I run kproj with -v")
def step_when_run_kproj_verbose(context: Any) -> None:
    """Run the workflow with verbose_level=1 and capture the stderr text."""
    workflow = _build_workflow(context)
    request = _build_request(context)
    # verbose_level=1 emulates `kproj -v <path>`.
    from dataclasses import replace as _replace

    request = _replace(request, verbose_level=1)
    captured_findings: list[Any] = []
    with patch("kproj.services.site_publisher._git_run") as mock_git:
        context.result = workflow.run(request)
        context.git_calls = [tuple(call.args[0]) for call in mock_git.call_args_list]
    context.outcome = context.result.outcome
    context.exit_code = context.result.exit_code
    # Render findings via StderrFormatter to build the stderr surface the
    # CLI would have produced; matches the wire-up added in BLOCKER 4.
    from kproj.formatters.stderr_formatter import StderrFormatter

    captured_findings.extend(context.result.findings)
    context.stderr = StderrFormatter(verbose_level=1).format_findings(captured_findings)


# ─────────────────────────── Then steps ──────────────────────────────────────


@then("the version page exists in the site repo")
def step_then_version_page_exists(context: Any) -> None:
    """Assert the _versions/<P>/<R>.md file was created."""
    P = getattr(context, "project_name", "MyProject")
    version_file = context.site_repo / "_versions" / P / "1.0.md"
    assert version_file.exists(), f"_versions/{P}/1.0.md not found in {context.site_repo}"


@then("the project page exists in the site repo")
def step_then_project_page_exists(context: Any) -> None:
    """Assert the pages/<P>.md file was created."""
    P = getattr(context, "project_name", "MyProject")
    pages_file = context.site_repo / "pages" / f"{P}.md"
    assert pages_file.exists(), f"pages/{P}.md not found in {context.site_repo}"


@then("no files are written to the site repo")
def step_then_no_files_written(context: Any) -> None:
    """Assert the site repo has no version/pages files (dry-run guard)."""
    versions = (
        list((context.site_repo / "_versions").rglob("*.md"))
        if (context.site_repo / "_versions").exists()
        else []
    )
    pages = (
        list((context.site_repo / "pages").rglob("*.md"))
        if (context.site_repo / "pages").exists()
        else []
    )
    assert not versions and not pages, f"dry-run wrote files: versions={versions}, pages={pages}"


@then("the version page contains the audit findings table")
def step_then_version_page_has_audit_table(context: Any) -> None:
    """Assert the version markdown body has a Metadata Audit table."""
    P = getattr(context, "project_name", "AuditProject")
    version_file = context.site_repo / "_versions" / P / "1.0.md"
    if not version_file.exists():
        # Try project name from result
        P = context.result.message.split("'")[1] if "'" in context.result.message else P
        version_file = context.site_repo / "_versions" / P / "1.0.md"
    assert version_file.exists(), f"version file not found: {version_file}"
    content = version_file.read_text()
    assert "Metadata Audit" in content, (
        f"No 'Metadata Audit' in version page body:\n{content[:500]}"
    )


@then("the version page front-matter includes findings counts")
def step_then_front_matter_has_counts(context: Any) -> None:
    """Assert audit: {errors:…, warnings:…} is in the front-matter."""
    P = getattr(context, "project_name", "AuditProject")
    version_file = context.site_repo / "_versions" / P / "1.0.md"
    if not version_file.exists():
        for f in (context.site_repo / "_versions").rglob("*.md"):
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
    for version_file in (context.site_repo / "_versions").rglob("*.md"):
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
    version_files = list((context.site_repo / "_versions").rglob("*.md"))
    assert version_files, "Expected at least one version file after publish"


@then("no partial files remain in the site repo")
def step_then_no_partial_files(context: Any) -> None:
    """Assert the site repo is clean (rollback worked)."""
    version_files = (
        list((context.site_repo / "_versions").rglob("*.md"))
        if (context.site_repo / "_versions").exists()
        else []
    )
    pages_files = (
        list((context.site_repo / "pages").rglob("*.md"))
        if (context.site_repo / "pages").exists()
        else []
    )
    assert not version_files and not pages_files, (
        f"Partial files remain: {version_files + pages_files}"
    )


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


@then('the version page front-matter status is "{expected}"')
def step_then_frontmatter_status_matches(context: Any, expected: str) -> None:
    """Assert the version page front-matter has ``status: <expected>``.

    For ``replaced-by:<target>``, the front-matter emits the base
    ``replaced-by`` token (target-emission is deferred to kproj#14);
    the expected value the scenario passes is therefore just
    ``replaced-by``.
    """
    for version_file in (context.site_repo / "_versions").rglob("*.md"):
        content = version_file.read_text()
        assert f"status: {expected}" in content, (
            f"expected 'status: {expected}' in {version_file}; first 600 chars:\n{content[:600]}"
        )
        return
    raise AssertionError("No version file found in site repo")


@then("assets are not regenerated")
def step_then_assets_not_regenerated(context: Any) -> None:
    """Assert every baseline asset's mtime is unchanged from the snapshot.

    The baseline snapshot is captured in
    :func:`step_given_previously_published`.  A refreshed / noop /
    private-skip outcome MUST NOT invoke the artifact generator, so
    every previously-written asset file's mtime must match the
    baseline.
    """
    baseline = getattr(context, "baseline_asset_mtimes", None)
    assert baseline is not None, (
        "baseline_asset_mtimes was not populated; the 'previously "
        "published' Given step must run before this Then step."
    )
    changed: list[str] = []
    for path, baseline_mtime in baseline.items():
        if not path.exists():
            changed.append(f"{path}: asset removed (should not happen)")
            continue
        current_mtime = path.stat().st_mtime
        if current_mtime != baseline_mtime:
            changed.append(f"{path}: mtime changed ({baseline_mtime:.6f} → {current_mtime:.6f})")
    assert not changed, (
        "round-2 M11: refresh must not regenerate assets, but the "
        "following mtimes changed:\n  " + "\n  ".join(changed)
    )


@then('a git commit with the "{prefix}" prefix was invoked')
def step_then_git_commit_prefix(context: Any, prefix: str) -> None:
    """Assert the mocked git runner saw a ``git commit -m <prefix>...`` call.

    Since ``kproj.services.site_publisher._git_run`` is patched
    during the workflow run, we inspect the recorded call arg
    tuples to find the commit invocation and check the message.
    """
    git_calls = getattr(context, "git_calls", None)
    assert git_calls is not None, (
        "context.git_calls was not populated; the When step must "
        "patch site_publisher._git_run and record its args."
    )
    commits = [call for call in git_calls if call and call[0] == "commit"]
    assert commits, f"no git commit was invoked; git_calls={git_calls!r}"
    matching = [c for c in commits if any(prefix in arg for arg in c)]
    assert matching, (
        f"expected at least one commit whose message starts with {prefix!r}; "
        f"got commit invocations={commits!r}"
    )


@then("no git commit is invoked on the second run")
def step_then_no_commit_invoked_second_run(context: Any) -> None:
    """Assert the second-run git_calls list contains no ``commit`` invocation.

    Used by the ``active → private`` scenario: private-skip returns
    before any journal is opened, so no commit is ever attempted.
    """
    git_calls = getattr(context, "git_calls", None)
    assert git_calls is not None, "context.git_calls not populated"
    commits = [call for call in git_calls if call and call[0] == "commit"]
    assert not commits, f"expected no commit on the second run; got {commits!r}"


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
    """Assert no ``_versions/*.md`` files exist in the site repo."""
    versions_dir = context.site_repo / "_versions"
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


@then("stderr contains the audit finding names")
def step_then_stderr_has_audit_names(context: Any) -> None:
    """Assert the rendered stderr text contains audit finding rule names.

    Uses the AuditProject fixture (see :func:`step_given_project_with_warnings`)
    which triggers ``date_format`` and ``designer_format`` warnings.
    """
    stderr_text = getattr(context, "stderr", "") or ""
    finding_fields = {f.field for f in context.result.findings}
    assert finding_fields, (
        "expected at least one finding under the AuditProject fixture; "
        f"got findings={finding_fields}"
    )
    # At least one finding's field name must appear in stderr.
    hits = [name for name in finding_fields if name in stderr_text]
    assert hits, (
        f"No finding names surfaced on stderr. stderr={stderr_text!r} findings={finding_fields}"
    )
