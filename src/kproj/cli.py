"""kproj CLI entry point.

Per ``docs/adr/0006-library-shape-boundary-discipline.md``, this is
the **only** module in kproj that imports ``argparse`` or calls
``sys.exit``. ``main()`` parses argv, builds a typed
:class:`PublishRequest`, delegates to :class:`PublishWorkflow.run`,
and maps the returned :class:`PublishResult` to a process exit code
per ``docs/DESIGN.md`` § *Exit code mapping*.

See:
- ``docs/GLOSSARY.md`` for vocabulary,
- ``docs/PRD.md`` for v1 user-facing requirements,
- ``docs/DESIGN.md`` for implementation specs.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from .application.publish_workflow import PublishWorkflow
from .config import ConfigOverrides, load_config
from .formatters.stderr_formatter import StderrFormatter
from .model.publish_request import PublishRequest
from .model.publish_result import PublishResult, compute_exit_code

_DEFAULT_YAML_FILENAME = ".kproj.yaml"


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser for kproj's CLI surface.

    Returns:
        A configured :class:`argparse.ArgumentParser`. Building the
        parser is factored out so unit tests can introspect the flag
        surface without invoking the workflow.
    """
    parser = argparse.ArgumentParser(
        prog="kproj",
        description=(
            "Publish a point-in-time snapshot of a KiCad project to the SPCoast Jekyll site."
        ),
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help=(
            "Project to publish: path to a .kicad_pro / .kicad_sch / .kicad_pcb, a project "
            "directory, a basename resolved under the KiCad projects root, or '.' (cwd). "
            "Defaults to '.'."
        ),
    )
    parser.add_argument(
        "--site-repo",
        type=str,
        default=None,
        metavar="PATH",
        help="Override the local SPCoast site-repo checkout (highest precedence).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Read-only mode: surface findings without writing to the site repo.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        default=False,
        help="Skip 'git push' after the site-repo commit (batch-friendly).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity. Repeat for more detail.",
    )
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        default=False,
        help="Implementation-private debug output (not a stable interface).",
    )
    return parser


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """Parse *argv* using the kproj CLI parser.

    Args:
        argv: Argument list **excluding** the program name.

    Returns:
        The :class:`argparse.Namespace` produced by the parser.
    """
    parser = _build_parser()
    return parser.parse_args(list(argv))


def _overrides_from(namespace: argparse.Namespace) -> ConfigOverrides:
    """Translate the argparse namespace into :class:`ConfigOverrides`.

    Args:
        namespace: The parsed argparse namespace from :func:`parse_args`.

    Returns:
        A :class:`ConfigOverrides` with ``None`` for any flag the user
        did not explicitly pass - preserving the precedence semantics
        in :func:`kproj.config.load_config`.
    """
    return ConfigOverrides(
        site_repo=Path(namespace.site_repo) if namespace.site_repo else None,
        # argparse default for --no-push is False; only treat True as an override
        # so that absence falls through to env / yaml / default.
        no_push=True if namespace.no_push else None,
        kicad_cli=None,  # reserved for future --kicad-cli flag
    )


def build_request(
    namespace: argparse.Namespace,
    env: Mapping[str, str],
    yaml_path: Path,
) -> PublishRequest:
    """Build a :class:`PublishRequest` from a parsed namespace + env.

    Args:
        namespace: Parsed CLI arguments.
        env: Mapping of environment variables (usually ``os.environ``).
        yaml_path: Path to ``~/.kproj.yaml`` (or a fixture in tests).

    Returns:
        A fully populated :class:`PublishRequest` ready for
        :meth:`PublishWorkflow.run`.
    """
    overrides = _overrides_from(namespace)
    config = load_config(overrides=overrides, env=env, yaml_path=yaml_path)
    verbose_level = int(namespace.verbose) + (1 if namespace.debug else 0)
    return PublishRequest(
        project_arg=str(namespace.project),
        config=config,
        dry_run=bool(namespace.dry_run),
        verbose_level=verbose_level,
        debug=bool(namespace.debug),
    )


def resolve_exit_code(result: PublishResult) -> int:
    """Return the process exit code for *result*.

    Wave-2 carry-forward: the workflow now populates
    :attr:`PublishResult.exit_code` authoritatively via
    :func:`kproj.model.publish_result.compute_exit_code`, so this
    function is effectively a single-line re-derivation.  It is kept
    as a stable seam so the CLI surface evolves independently of how
    the workflow constructs its result - if a future refactor stops
    populating ``exit_code`` for any reason, the CLI still maps
    correctly via :func:`compute_exit_code`.

    Args:
        result: The :class:`PublishResult` returned by the workflow.

    Returns:
        The integer exit code per ``docs/DESIGN.md`` § *Exit code mapping*.
    """
    return compute_exit_code(result.outcome, result.findings)


def _default_yaml_path() -> Path:
    """Return the default ``~/.kproj.yaml`` path for the current user."""
    return Path.home() / _DEFAULT_YAML_FILENAME


def main(argv: Sequence[str] | None = None) -> int:
    """kproj CLI entry point.

    Args:
        argv: Optional argument list (excluding program name). Defaults
            to ``sys.argv[1:]``.

    Returns:
        Process exit code per :func:`resolve_exit_code`.
    """
    args = list(sys.argv[1:]) if argv is None else list(argv)
    namespace = parse_args(args)
    request = build_request(
        namespace,
        env=os.environ,
        yaml_path=_default_yaml_path(),
    )
    workflow = PublishWorkflow()
    result = workflow.run(request)
    _render_result_to_stderr(result, verbose_level=request.verbose_level)
    return resolve_exit_code(result)


def _render_result_to_stderr(result: PublishResult, *, verbose_level: int) -> None:
    """Print the workflow result's findings + summary message to stderr.

    ADR 0004 ("show what is provided") and PRD Story 5 require every
    audit/DRC/ERC finding to surface on the user's terminal at default
    verbosity.  The pre-fix CLI emitted only ``result.message``, so
    findings could set ``exit_code=1`` and land in the version page
    while remaining invisible to the user (BLOCKER 4).

    Args:
        result: The :class:`PublishResult` returned by
            :meth:`PublishWorkflow.run`.
        verbose_level: 0 = default (findings + message), 1+ = future
            command-line / subprocess diagnostics (verbose wiring is
            tracked as a Phase 6 follow-up issue).
    """
    if result.findings:
        formatter = StderrFormatter(verbose_level=verbose_level)
        rendered = formatter.format_findings(result.findings)
        if rendered:
            print(rendered, file=sys.stderr)
    if result.message:
        print(result.message, file=sys.stderr)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
