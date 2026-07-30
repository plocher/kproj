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
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

from .. import __version__
from ..application.publish_workflow import PublishWorkflow
from ..application.site_management_workflow import SiteManagementWorkflow
from ..common.logging_setup import configure as configure_logging
from ..config import ConfigOverrides, KprojConfig, load_config
from ..formatters.stderr_formatter import StderrFormatter
from ..model.finding import Finding
from ..model.publish_request import PublishRequest
from ..model.publish_result import PublishResult, compute_exit_code
from ..model.severity import Severity
from ..model.site_management import DeleteRequest
from ..services.kicad_project_reader import KicadProjectReader, ProjectResolutionError

_log = logging.getLogger(__name__)

_DEFAULT_YAML_FILENAME = ".kproj.yaml"
_COMPACT_VISIBLE_ADVISORY_FIELDS = frozenset(
    {
        # GitHub-link advisories: project has no repo / unpushed repo.
        "github_link_missing",
        "github_link_unpushed",
        # Production-folder advisories: directly affect what gets published
        # (fab.zip is omitted when production/ is missing or incomplete).
        "production_missing",
        "production_incomplete",
    }
)

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
  ibom_extra_fields: Details,Description
  fabricator: jlc

Without a ~/.kproj.yaml and no --inventory/KPROJ_INVENTORY, kproj publishes
without datasheet deep-links (jbom is never invoked - see --inventory below).

Commands:
  kproj publish [project]
  kproj list [project]
  kproj list --all
  kproj delete [project] [--version <board_rev>] [--force] [--dry-run] [--no-push]
"""


def _build_publish_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> argparse.ArgumentParser:
    """Construct the ``kproj publish`` parser."""
    parser = subparsers.add_parser(
        "publish",
        help="Publish a project snapshot into the site repo.",
        prog="kproj publish",
        description=(
            "Publish a point-in-time snapshot of a KiCad project to the SPCoast Hugo site."
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
            '"Details,Description".'
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
        "--republish",
        "--force",
        dest="republish",
        action="store_true",
        default=False,
        help=(
            "Force artifact regeneration and publish even when unchanged checks "
            "would otherwise skip producers."
        ),
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
        "--watermark",
        type=str,
        default="",
        metavar="TAG",
        help=(
            "Free-text tag stamped into the generated iBOM page, the Hugo "
            "front-matter kproj_publish_context, and the site-repo commit "
            "message, alongside the auto-detected kproj version/install type. "
            "Intended for dev/test invocations (e.g. `uv run kproj publish "
            "--watermark <unique-tag>`) so their output is unmistakably "
            "distinct from a normal production publish; forces a regeneration "
            "like any other publish-context change."
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
    parser.set_defaults(command="publish")
    return parser


def _build_list_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> argparse.ArgumentParser:
    """Construct the parser for ``kproj list``."""
    parser = subparsers.add_parser(
        "list",
        help="List published versions for a project.",
        prog="kproj list",
        description="List published versions for a project in the site repo.",
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help=(
            "Project to inspect. Accepts the same input forms as publish and defaults to '.' (cwd)."
        ),
    )
    parser.add_argument(
        "--all",
        dest="all_projects",
        action="store_true",
        default=False,
        help="List every published project in one-line-per-project format.",
    )
    parser.add_argument(
        "--site-repo",
        type=str,
        default=None,
        metavar="PATH",
        help="Override the local SPCoast site-repo checkout (highest precedence).",
    )
    parser.set_defaults(command="list")
    return parser


def _build_delete_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> argparse.ArgumentParser:
    """Construct the parser for ``kproj delete``."""
    parser = subparsers.add_parser(
        "delete",
        help="Delete published site content for a project/version.",
        prog="kproj delete",
        description="Delete published site content for a project.",
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help=(
            "Project to delete. Accepts the same input forms as publish and defaults to '.' (cwd)."
        ),
    )
    parser.add_argument(
        "--version",
        type=str,
        default=None,
        metavar="REV",
        help="Delete only one published version.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help=(
            "Allow destructive project deletion. Required for full-project delete; "
            "also required when --version targets the project's last published version."
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
        help="Read-only mode: show what delete would remove without writing.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        default=False,
        help="Skip git push after delete commit.",
    )
    parser.set_defaults(command="delete")
    return parser


def _build_parser() -> argparse.ArgumentParser:
    """Construct the root parser for the kproj CLI surface."""
    parser = argparse.ArgumentParser(
        prog="kproj",
        description=(
            "Publish, list, and delete point-in-time KiCad project snapshots on the SPCoast Hugo site."
        ),
        epilog=_CONFIG_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(
        title="commands",
        dest="command",
        metavar="{publish,list,delete}",
        required=True,
    )
    _build_publish_parser(subparsers)
    _build_list_parser(subparsers)
    _build_delete_parser(subparsers)
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
    site_repo = getattr(namespace, "site_repo", None)
    no_push = bool(getattr(namespace, "no_push", False))
    inventory = getattr(namespace, "inventory", None)
    datasheet_library = getattr(namespace, "datasheet_library", None)
    datasheet_repo = getattr(namespace, "datasheet_repo", None)
    ibom_extra_fields = getattr(namespace, "ibom_extra_fields", None)
    fabricator = getattr(namespace, "fabricator", None)
    return ConfigOverrides(
        site_repo=Path(site_repo) if site_repo else None,
        # argparse default for --no-push is False; only treat True as an override
        # so that absence falls through to env / yaml / default.
        no_push=True if no_push else None,
        kicad_cli=None,  # reserved for future --kicad-cli flag
        inventory=Path(inventory) if inventory else None,
        datasheet_library=Path(datasheet_library) if datasheet_library else None,
        datasheet_repo=datasheet_repo or None,
        ibom_extra_fields=ibom_extra_fields or None,
        fabricator=fabricator or None,
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
    config = _load_runtime_config(namespace, env=env, yaml_path=yaml_path)
    verbose_level = int(namespace.verbose) + (1 if namespace.debug else 0)
    return PublishRequest(
        project_arg=str(namespace.project),
        config=config,
        dry_run=bool(namespace.dry_run),
        republish=bool(namespace.republish),
        verbose_level=verbose_level,
        debug=bool(namespace.debug),
        watermark=str(getattr(namespace, "watermark", "") or "").strip(),
    )


def build_delete_request(
    namespace: argparse.Namespace,
    env: Mapping[str, str],
    yaml_path: Path,
    *,
    project: str | None = None,
) -> DeleteRequest:
    """Build a :class:`DeleteRequest` from a parsed delete namespace + env."""
    config = _load_runtime_config(namespace, env=env, yaml_path=yaml_path)
    return DeleteRequest(
        project=str(project if project is not None else namespace.project),
        version=str(namespace.version) if namespace.version else None,
        force=bool(namespace.force),
        dry_run=bool(namespace.dry_run),
        config=config,
    )


def _load_runtime_config(
    namespace: argparse.Namespace,
    *,
    env: Mapping[str, str],
    yaml_path: Path,
) -> KprojConfig:
    """Resolve :class:`KprojConfig` from parsed args + env + yaml path."""
    overrides = _overrides_from(namespace)
    return load_config(overrides=overrides, env=env, yaml_path=yaml_path)


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


def _resolve_site_project_identifier(project_arg: str) -> str:
    """Resolve a publish-style project argument into a site project identifier.

    ``list`` and ``delete`` accept the same project input forms as ``publish``.
    When local KiCad resolution succeeds, this returns the canonical basename.
    If local resolution fails, fall back to the raw token so direct site-project
    identifiers continue to work.
    """
    try:
        return KicadProjectReader().resolve(project_arg).basename
    except ProjectResolutionError:
        return project_arg


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
    command = str(getattr(namespace, "command", ""))

    if command == "list":
        config = _load_runtime_config(namespace, env=os.environ, yaml_path=yaml_path)
        project: str | None
        if bool(getattr(namespace, "all_projects", False)):
            project = None
        else:
            project = _resolve_site_project_identifier(str(namespace.project))
        project_workflow = SiteManagementWorkflow()
        project_result = project_workflow.list_projects(config, project=project)
        if project_result.message:
            print(project_result.message, file=sys.stderr)
        return project_result.exit_code

    if command == "delete":
        project = _resolve_site_project_identifier(str(namespace.project))
        delete_request = build_delete_request(
            namespace,
            env=os.environ,
            yaml_path=yaml_path,
            project=project,
        )
        delete_workflow = SiteManagementWorkflow()
        delete_result = delete_workflow.delete(delete_request)
        if delete_result.message:
            print(delete_result.message, file=sys.stderr)
        return delete_result.exit_code

    publish_request = build_request(
        namespace,
        env=os.environ,
        yaml_path=yaml_path,
    )
    # Wire -v / -d to the kproj-namespaced logger BEFORE the workflow runs
    # so subprocess argv, git invocations, and regen decisions are visible.
    configure_logging(verbose_level=publish_request.verbose_level, debug=publish_request.debug)
    _emit_first_run_hint(yaml_path=yaml_path, inventory=publish_request.config.inventory)
    publish_workflow = PublishWorkflow()
    publish_result = publish_workflow.run(publish_request)
    _render_result_to_stderr(
        publish_result,
        verbose_level=publish_request.verbose_level,
        debug=publish_request.debug,
    )
    return resolve_exit_code(publish_result)


def _render_result_to_stderr(result: PublishResult, *, verbose_level: int, debug: bool) -> None:
    """Print compact findings context and the run summary to stderr.

    End-of-run output is always compact regardless of verbosity:
    only selected high-signal advisories in
    :data:`_COMPACT_VISIBLE_ADVISORY_FIELDS` are shown as one-liners,
    plus the ``Note: Collected`` summary line.

    With ``-v`` (``verbose_level >= 1``), DRC/ERC findings were already
    shown inline by
    :func:`~kproj.application.publish_workflow._print_design_findings_inline`
    before this function is called; the summary hint text reflects that.

    ``-d`` controls the exec-transcript display in
    :mod:`kproj.common.subprocess_runner` and has no effect here.

    Args:
        result: The :class:`PublishResult` returned by
            :meth:`PublishWorkflow.run`.
        verbose_level: Current verbosity level derived from CLI flags.
        debug: ``True`` when ``-d`` was supplied (unused here; kept for
            call-site compatibility).
    """
    if result.findings:
        active = [f for f in result.findings if f.severity != Severity.EXCLUSION]
        if verbose_level >= 1:
            # -v: DRC/ERC were already shown inline by the workflow.  Emit
            # non-design (audit/other) findings so the detail is visible.
            # No Note line: everything is shown, nothing is hidden.
            non_design = [f for f in result.findings if f.source.lower() not in {"drc", "erc"}]
            if non_design:
                rendered = StderrFormatter(verbose_level=1).format_findings(non_design)
                if rendered:
                    print(rendered, file=sys.stderr)
        else:
            # Compact mode: surface only selected high-signal advisories.
            highlighted = _findings_to_highlight_in_compact_stderr(result.findings)
            if highlighted:
                rendered = StderrFormatter(verbose_level=0).format_findings(highlighted)
                if rendered:
                    print(rendered, file=sys.stderr)
            # Only print the Note line when there are active findings not already
            # shown by the compact advisory display.  If every active finding was
            # already surfaced above, the Note line just repeats what was said.
            hidden_active = [f for f in active if f.field not in _COMPACT_VISIBLE_ADVISORY_FIELDS]
            if hidden_active or (active and not highlighted):
                print(
                    _findings_summary_for_stderr(result.findings, verbose_level=verbose_level),
                    file=sys.stderr,
                )
    if result.message:
        print(result.message, file=sys.stderr)


def _findings_summary_for_stderr(findings: Sequence[Finding], *, verbose_level: int = 0) -> str:
    """Return a human-readable findings summary suitable for stderr output.

    Active issues (ERROR/WARNING/INFO) are counted and described by source.
    Exclusions (KiCad-suppressed violations) are noted separately so they
    do not inflate the issue count or appear as problems to fix.
    """
    active = [f for f in findings if f.severity != Severity.EXCLUSION]

    # Build per-source description of active findings.
    source_counts: dict[str, Counter[Severity]] = {}
    for f in active:
        bucket = _source_bucket(f.source)
        if bucket not in source_counts:
            source_counts[bucket] = Counter()
        source_counts[bucket][f.severity] += 1

    source_parts: list[str] = []
    for bucket in ("audit", "drc", "erc", "other"):
        counts = source_counts.get(bucket)
        if not counts:
            continue
        items: list[str] = []
        if counts[Severity.ERROR]:
            n = counts[Severity.ERROR]
            items.append(f"{n} error{'s' if n > 1 else ''}")
        if counts[Severity.WARNING]:
            n = counts[Severity.WARNING]
            items.append(f"{n} warning{'s' if n > 1 else ''}")
        if counts[Severity.INFO]:
            n = counts[Severity.INFO]
            items.append(f"{n} note{'s' if n > 1 else ''}")
        source_parts.append(f"{bucket}: {', '.join(items)}")

    n_active = len(active)
    if n_active > 0:
        issue_word = "issue" if n_active == 1 else "issues"
        detail = f" ({'; '.join(source_parts)})" if source_parts else ""
        issue_text = f"{n_active} {issue_word}{detail}."
    else:
        issue_text = "No issues."

    details_note = (
        "  Findings shown above." if verbose_level >= 1 else "  run with -v to see findings detail."
    )
    return f"Note: {issue_text}{details_note}"


def _findings_to_highlight_in_compact_stderr(findings: Sequence[Finding]) -> tuple[Finding, ...]:
    """Return selected advisory findings that remain explicit in compact stderr mode."""
    return tuple(
        finding for finding in findings if finding.field in _COMPACT_VISIBLE_ADVISORY_FIELDS
    )


def _source_bucket(source: str) -> str:
    """Return the compact summary bucket for a finding source token."""
    normalized = source.strip().lower()
    if normalized in {"", "audit", "read"}:
        return "audit"
    if normalized in {"drc", "erc"}:
        return normalized
    return "other"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
