"""Step definitions for ``preflight.feature``.

Foundation slice scenarios. These steps exercise the ``kproj.cli.main``
entry point against a temp directory; full per-story Gherkin coverage
lands once the downstream services are implemented.
"""

from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path
from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]

from kproj import cli


@given("a directory with no .kicad_pro file")
def step_empty_directory(context: Any) -> None:
    """Create a temp directory that does not contain a KiCad project."""
    context.tmpdir = tempfile.mkdtemp(prefix="kproj-behave-")
    context.project_path = Path(context.tmpdir)


@when("I run kproj against that directory")
def step_run_kproj(context: Any) -> None:
    """Invoke :func:`kproj.cli.main` against the prepared directory."""
    err_buffer = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = err_buffer
    try:
        context.exit_code = cli.main([str(context.project_path)])
    finally:
        sys.stderr = original_stderr
    context.stderr = err_buffer.getvalue()


@then("kproj exits with code {code:d}")
def step_exit_code(context: Any, code: int) -> None:
    """Assert the captured exit code matches *code*."""
    assert context.exit_code == code, (
        f"expected exit code {code}, got {context.exit_code}; stderr={context.stderr!r}"
    )


@then('stderr mentions "{fragment}"')
def step_stderr_mentions(context: Any, fragment: str) -> None:
    """Assert *fragment* appears in the captured stderr output."""
    assert fragment in context.stderr, (
        f"expected stderr to contain {fragment!r}; got {context.stderr!r}"
    )
