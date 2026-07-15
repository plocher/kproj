"""kproj CLI entry point.

Per ``docs/adr/0006-library-shape-boundary-discipline.md``, this module
owns ``argparse`` and delegates the entrypoint to :func:`main` (the
``python -m kproj`` shim in ``src/kproj/__main__.py`` calls into this
module). ``main()`` parses argv, builds a typed
:class:`PublishRequest`, delegates to :class:`PublishWorkflow.run`,
and maps the returned :class:`PublishResult` to a process exit code
per ``docs/DESIGN.md`` § *Exit code mapping*.

See:
- ``CONTEXT.md`` for vocabulary,
- ``docs/PRD.md`` for v1 user-facing requirements,
- ``docs/DESIGN.md`` for implementation specs.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..application.publish_workflow import PublishWorkflow
from ..common.logging_setup import configure as configure_logging
from ..config import ConfigOverrides, load_config
from ..formatters.stderr_formatter import StderrFormatter
from ..model.publish_request import PublishRequest
from ..model.publish_result import PublishResult, compute_exit_code

_log = logging.getLogger(__name__)

_DEFAULT_YAML_FILENAME = ".kproj.yaml"

_CONFIG_EPILOG = """\
Configuration precedence (highest wins):
  CLI flag > KPROJ_* environment variable > ~/.kproj.yaml > default

Environment variables:
  KPROJ_SITE_REPO          overrides --site-repo
  KPROJ_NO_PUSH            overrides --no-push (1/true/yes/on/y/t)
  KPROJ_KICAD_CLI          overrides the kicad-cli executable path
  KPROJ_INVENTORY          overrides --inventory
  KPROJ_DATASHEET_LIBRARY  overrides --datasheet-library
  KPROJ_DATASHEET_REPO     overrides --datasheet-repo
  KPROJ_IBOM_EXTRA_FIELDS  overrides --ibom-extra-fields
  KPROJ_FABRICATOR         overrides --fabricator (generic/jlc/pcbway/seeed)

~/.kproj.yaml example:
  site_repo: /home/you/Dropbox/workspace/SPCoast.github.io
  no_push: false
  kicad_cli: /usr/local/bin/kicad-cli
  inventory: /home/you/Dropbox/KiCad/SPCoast-inventory/SPCoast-INVENTORY.csv
  datasheet_library: /home/you/Dropbox/KiCad/SPCoast-inventory
  datasheet_repo: plocher/SPCoast-inventory
  ibom_extra_fields: MPN,Manufacturer,Fabricator Part Number,Datasheet,Datasheet Name,Description
  fabricator: jlc

Without a ~/.kproj.yaml and no --inventory/KPROJ_INVENTORY, kproj publishes
without datasheet deep-links (jbom is never invoked - see --inventory below).
"""


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
            "Publish a point-in-time snapshot of a KiCad project to the SPCoast Hugo site."
        ),
        epilog=_CONFIG_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
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
        "--inventory",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Inventory CSV to enrich the BOM with curated datasheet names "
            "(env: KPROJ_INVENTORY; yaml: inventory:). Unset means kproj never "
            "invokes jbom and publishes without datasheet deep-links."
        ),
    )
    parser.add_argument(
        "--datasheet-library",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Local datasheet-library clone used by the advisory publish guard "
            "(env: KPROJ_DATASHEET_LIBRARY; yaml: datasheet_library:). "
            "Default: ~/Dropbox/KiCad/SPCoast-inventory."
        ),
    )
    parser.add_argument(
        "--datasheet-repo",
        type=str,
        default=None,
        metavar="OWNER/REPO",
        help=(
            "Public <owner>/<repo> slug that published datasheet deep-links point at "
            "(env: KPROJ_DATASHEET_REPO; yaml: datasheet_repo:). "
            "Default: plocher/SPCoast-inventory."
        ),
    )
    parser.add_argument(
        "--ibom-extra-fields",
        type=str,
        default=None,
        metavar="FIELDS",
        help=(
            "Comma-separated iBOM extra fields to surface (env: KPROJ_IBOM_EXTRA_FIELDS; "
            "yaml: ibom_extra_fields:). Example: "
            '"MPN,Manufacturer,Fabricator Part Number,Datasheet,Datasheet Name,Description".'
        ),
    )
    parser.add_argument(
        "--fabricator",
        type=str,
        choices=["generic", "jlc", "pcbway", "seeed"],
        default=None,
        metavar="FAB",
        help=(
            "Fabricator profile used for `jbom bom` lookup output "
            "(env: KPROJ_FABRICATOR; yaml: fabricator:). "
            "Default: jlc."
        ),
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
        help=(
            "Skip 'git push' after the site-repo commit for batch runs; "
            "a final plain run flushes pending site commits."
        ),
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
        inventory=Path(namespace.inventory) if namespace.inventory else None,
        datasheet_library=(
            Path(namespace.datasheet_library) if namespace.datasheet_library else None
        ),
        datasheet_repo=namespace.datasheet_repo or None,
        ibom_extra_fields=namespace.ibom_extra_fields or None,
        fabricator=namespace.fabricator or None,
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


def _emit_first_run_hint(*, yaml_path: Path, inventory: Path | None) -> None:
    """Emit a one-time INFO hint when config is fully undiscovered (kproj#37).

    Per the owner ruling on kproj#36, an unset ``inventory`` is a valid,
    advisory-free degraded state (no ``Finding``, no ``jbom`` invocation).
    Without this hint the resulting blank-datasheet degradation is
    silent and undiscoverable; this is deliberately INFO-level (not a
    warning/finding) - the degraded state itself stays advisory-free.
    """
    if not yaml_path.exists() and inventory is None:
        _log.info(
            "no %s found and no --inventory/KPROJ_INVENTORY set; datasheet "
            "deep-links will be blank until configured. Run `kproj --help` "
            "for the full ~/.kproj.yaml example.",
            yaml_path,
        )


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
    yaml_path = _default_yaml_path()
    request = build_request(
        namespace,
        env=os.environ,
        yaml_path=yaml_path,
    )
    # Wire -v / -d to the kproj-namespaced logger BEFORE the workflow runs
    # so subprocess argv, git invocations, and regen decisions are visible.
    configure_logging(verbose_level=request.verbose_level, debug=request.debug)
    _emit_first_run_hint(yaml_path=yaml_path, inventory=request.config.inventory)
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
