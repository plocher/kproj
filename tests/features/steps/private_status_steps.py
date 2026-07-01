"""Step definitions for ``private_status.feature``.

Exercises the wave-2 ``PublishWorkflow`` directly (rather than the CLI
entry point) so the status-detection short-circuit can be asserted on
the typed :class:`PublishResult` rather than parsed stderr text.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]

# Re-use the fixture builder from the unit-test layer.
_TESTS_ROOT = Path(__file__).resolve().parents[2]
if str(_TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TESTS_ROOT))

from _kicad_fixtures import (  # noqa: E402 - path setup above
    TitleBlockSpec,
    make_minimal_project,
)
from kproj.application import publish_workflow as workflow_module  # noqa: E402
from kproj.application.publish_workflow import PublishWorkflow  # noqa: E402
from kproj.config import GENERIC_SITE_PROFILE, KprojConfig  # noqa: E402
from kproj.model.analysis_info import AnalysisInfo  # noqa: E402
from kproj.model.publish_request import PublishRequest  # noqa: E402
from kproj.services.kicad_project_reader import KicadProjectReader  # noqa: E402


class _SilentDesignAnalyzer:
    """Stand-in DesignAnalyzer that emits no findings (no real kicad-cli)."""

    def __init__(self, _kicad_cli: Path) -> None: ...

    def analyze(self, _resolved: object) -> AnalysisInfo:
        return AnalysisInfo(findings=())


@given('a KiCad project whose schematic COMMENT9 is "{value}"')
def step_project_with_comment9(context: Any, value: str) -> None:
    """Materialise a fixture project carrying *value* in SCH ${COMMENT9}."""
    context.tmpdir = tempfile.mkdtemp(prefix="kproj-behave-private-")
    project_dir = Path(context.tmpdir) / "private-demo"
    make_minimal_project(
        project_dir,
        "private-demo",
        sch_title_block=TitleBlockSpec(
            title="Private Project",
            company="ACME",
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer", 9: value},
        ),
        pcb_title_block=TitleBlockSpec(
            title="Private Project",
            company="ACME",
            revision="1.0",
            date="2026.04",
            comments={1: "Alice Designer"},
        ),
    )
    context.project_dir = project_dir
    context.projects_root = Path(context.tmpdir)


@when("I run kproj against that project")
def step_run_kproj_workflow(context: Any) -> None:
    """Invoke :class:`PublishWorkflow` directly, stubbing kicad-cli discovery."""
    fake_cli = Path(context.tmpdir) / "kicad-cli"
    fake_cli.write_text("")

    # Patch the workflow's kicad_version probe to return 9.x without a real cli.
    workflow_module.kicad_version = lambda _cli: (9, 0, 4)  # type: ignore[attr-defined]

    config = KprojConfig(
        site_repo=Path("/tmp/private-site"),
        no_push=True,
        kicad_cli=fake_cli,
        site_profile=GENERIC_SITE_PROFILE,
    )
    request = PublishRequest(
        project_arg=str(context.project_dir),
        config=config,
    )
    workflow = PublishWorkflow(
        project_reader=KicadProjectReader(projects_root=context.projects_root),
        design_analyzer_factory=_SilentDesignAnalyzer,
    )
    context.result = workflow.run(request)
    context.stderr = context.result.message


@then('kproj reports outcome "{outcome}"')
def step_outcome_matches(context: Any, outcome: str) -> None:
    """Assert the captured :class:`PublishResult` outcome equals *outcome*."""
    assert context.result.outcome == outcome, (
        f"expected outcome {outcome!r}, got {context.result.outcome!r}; "
        f"message={context.result.message!r}"
    )


# Note: the ``stderr mentions "{fragment}"`` step lives in
# ``preflight_steps.py``; Behave shares step modules across feature files,
# so we intentionally do NOT redeclare it here.  Our ``when`` step writes
# the workflow's result.message into ``context.stderr`` so the existing
# step matcher Just Works.
