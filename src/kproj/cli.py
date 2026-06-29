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

from .application.publish_workflow import (
    PublishRequest,
    PublishResult,
    PublishWorkflow,
)
from .config import ConfigOverrides, load_config
from .model.severity import Severity

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
        did not explicitly pass — preserving the precedence semantics
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


_TERMINAL_SUCCESS_OUTCOMES = {"published", "refreshed", "noop", "private-skip"}


def resolve_exit_code(result: PublishResult) -> int:
    """Map a :class:`PublishResult` to a process exit code.

    Implements ``docs/DESIGN.md`` § *Exit code mapping*:

    - ``0`` — terminal-success outcome AND no error/warning findings.
    - ``1`` — terminal-success outcome AND at least one error/warning
      finding (exclusions do not count).
    - ``2`` — ``outcome == "failed"``.

    Args:
        result: The :class:`PublishResult` returned by the workflow.

    Returns:
        The integer exit code.
    """
    if result.outcome == "failed":
        return 2
    if result.outcome in _TERMINAL_SUCCESS_OUTCOMES:
        has_findings = any(
            f.severity in {Severity.ERROR, Severity.WARNING} for f in result.findings
        )
        return 1 if has_findings else 0
    # Unknown outcome: treat as mechanical failure (defensive default).
    return 2


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
    if result.message:
        print(result.message, file=sys.stderr)
    return resolve_exit_code(result)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
