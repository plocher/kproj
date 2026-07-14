"""Step definitions for ``config_precedence.feature`` (kproj#37).

Drives :func:`kproj.cli.main` with real argv, real ``os.environ`` mutations,
and a real ``~/.kproj.yaml`` fixture file - never a hand-built
:class:`~kproj.config.KprojConfig` - so the CLI > env > yaml precedence
chain is exercised end-to-end through the actual entry point
(``parse_args`` -> ``build_request`` -> ``load_config``), not just at the
config-resolver unit level.

:class:`_CapturingWorkflow` stands in for :class:`~kproj.application.publish_workflow.PublishWorkflow`
so no real ``kicad-cli`` / ``jbom`` / git invocation is needed; it exists
solely to capture the resolved :class:`~kproj.config.KprojConfig` for
assertion.
"""

from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from behave import given, then, when  # type: ignore[import-untyped]

from kproj import cli
from kproj.model.publish_request import PublishRequest
from kproj.model.publish_result import PublishResult

# ``kproj.cli`` re-exports the ``main`` *function* (see ``kproj/cli/__init__.py``),
# which shadows the ``kproj.cli.main`` *module* path for dotted-string patch
# targets. Import the module explicitly (mirrors tests/unit/test_cli.py) so
# ``patch()`` resolves ``PublishWorkflow`` on the module, not the function.
cli_main = importlib.import_module("kproj.cli.main")

# The full set of KPROJ_* variables (plus HOME) a scenario must isolate from
# whatever the host shell/CI runner happens to have set, so a scenario that
# doesn't explicitly configure a tier never accidentally inherits ambient
# state left over from the developer's environment.
_ISOLATED_ENV_KEYS: tuple[str, ...] = (
    "HOME",
    "KPROJ_SITE_REPO",
    "KPROJ_NO_PUSH",
    "KPROJ_KICAD_CLI",
    "KPROJ_INVENTORY",
    "KPROJ_DATASHEET_LIBRARY",
    "KPROJ_DATASHEET_REPO",
)


class _CapturingWorkflow:
    """Stand-in ``PublishWorkflow`` that records the request and reports success.

    Never touches kicad-cli, jBOM, or git - ``main()`` only needs a
    ``.run(request)`` method returning a :class:`PublishResult`.
    """

    def __init__(self) -> None:
        self.captured: list[PublishRequest] = []

    def run(self, request: PublishRequest) -> PublishResult:
        self.captured.append(request)
        return PublishResult(outcome="published", exit_code=0)


@given('a ~/.kproj.yaml with "{yaml_key}" set to "{value}"')
def step_yaml_key(context: Any, yaml_key: str, value: str) -> None:
    """Append *yaml_key: value* to the scenario's ``~/.kproj.yaml`` fixture."""
    if not hasattr(context, "home_dir"):
        context.home_dir = tempfile.mkdtemp(prefix="kproj-behave-home-")
    yaml_path = Path(context.home_dir) / ".kproj.yaml"
    existing = yaml_path.read_text(encoding="utf-8") if yaml_path.exists() else ""
    yaml_path.write_text(f"{existing}{yaml_key}: {value}\n", encoding="utf-8")


@given('the environment variable "{env_var}" is set to "{value}"')
def step_env_var(context: Any, env_var: str, value: str) -> None:
    """Record an environment variable override to apply when kproj runs."""
    if not hasattr(context, "env_overrides"):
        context.env_overrides = {}
    context.env_overrides[env_var] = value


def _run_kproj(context: Any, *, extra_argv: list[str]) -> None:
    """Invoke ``kproj.cli.main`` with an isolated env + the scenario's yaml fixture.

    Saves and restores every key in :data:`_ISOLATED_ENV_KEYS` around the
    call so scenarios never leak into each other or pick up ambient state
    from the host environment.
    """
    home_dir = getattr(context, "home_dir", None) or tempfile.mkdtemp(prefix="kproj-behave-home-")
    env_overrides = dict(getattr(context, "env_overrides", {}))

    saved = {key: os.environ.get(key) for key in _ISOLATED_ENV_KEYS}
    try:
        for key in _ISOLATED_ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["HOME"] = home_dir
        os.environ.update(env_overrides)

        workflow = _CapturingWorkflow()
        with patch.object(cli_main, "PublishWorkflow", return_value=workflow):
            context.kproj_exit_code = cli.main(["/tmp/kproj-behave-nonexistent", *extra_argv])
    finally:
        for key, original in saved.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original

    assert workflow.captured, "PublishWorkflow.run() was never invoked"
    context.resolved_config = workflow.captured[-1].config


@when('I run kproj with "{cli_flag}" set to "{value}"')
def step_run_with_flag(context: Any, cli_flag: str, value: str) -> None:
    """Run kproj with a single CLI flag set to *value*."""
    _run_kproj(context, extra_argv=[cli_flag, value])


@when("I run kproj with no config flags")
def step_run_with_no_flags(context: Any) -> None:
    """Run kproj with no configuration-related CLI flags."""
    _run_kproj(context, extra_argv=[])


@then('the resolved "{config_field}" is "{expected}"')
def step_resolved_field(context: Any, config_field: str, expected: str) -> None:
    """Assert the captured ``KprojConfig`` field matches *expected*."""
    value = getattr(context.resolved_config, config_field)
    actual = str(value) if isinstance(value, Path) else value
    assert actual == expected, (
        f"expected KprojConfig.{config_field} == {expected!r}, got {actual!r}"
    )
