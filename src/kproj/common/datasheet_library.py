"""Datasheet deep-links from the BOM's ``Datasheet Name`` column (kproj#29).

Per the datasheet document library map (``plocher/jBOM#342``), its
publish-mechanics resolution (``plocher/jBOM#350``), and the
ticket-owner's live-lookup ruling on kproj#29 (which amends ADR 0003 —
see ``docs/adr/0010-live-jbom-bom-invocation-for-datasheet-names.md``):

1. **Resolution path**: kproj invokes ``jbom bom <project_dir> -f
   "Datasheet Name" -o -`` at publish time and parses the CSV from
   stdout (:func:`read_datasheet_names`). This is a deliberate,
   narrowly-scoped exception to ADR 0003's "read, don't invoke":
   ``production/jbom.csv`` is a stale, fab-oriented snapshot that may
   predate the ``Datasheet Name`` field entirely, whereas datasheet
   links must reflect the *current* inventory. kproj still never
   writes to the inventory, never runs ``jbom fab``, and never invokes
   any other jBOM subcommand. When the invocation fails (jbom missing,
   too old to know the field, or any other mechanical failure) or the
   column comes back absent, kproj publishes without datasheet links
   and :func:`read_datasheet_names` returns an advisory ``Finding``
   instead of raising - the lookup is never a publish blocker.
2. **Site representation**: no site copies. Published pages deep-link
   the public ``plocher/SPCoast-inventory`` repo directly.
   :func:`build_datasheet_link` constructs the two deterministic URLs
   (view + download) from a curated name.
3. **URL-stability**: ``main``-branch URLs, no commit pinning — the
   library's Never-Rename / append-only invariant guarantees they
   cannot rot.
4. **Guard**: :func:`check_datasheet_links` is kproj's advisory-only
   publish check. It runs read-only against the conventional local
   library clone path (:data:`DEFAULT_LIBRARY_REPO`, overridable —
   mirrors the ``~/Dropbox/KiCad/projects`` convention used by
   :mod:`kproj.services.metadata_analyzer` for ``replaced-by:<X>``
   resolution) and emits warning findings for unresolvable or
   not-yet-pushed names. It never blocks a publish: short 404 windows
   on rarely-followed links are acceptable, and publish/push ordering
   is owned by Makefile orchestration, not a kproj gate.

The per-project ``*.pdf`` disk-walk (:mod:`kproj.common.project_docs`'
former ``discover_datasheets`` / ``discover_datasheet_files``) and its
site-copy sibling (``_copy_datasheets`` in
:mod:`kproj.application.publish_workflow`) are retired: the
project-index Documentation list derives solely from the BOM's
distinct ``Datasheet Name`` values, per this module.
"""

from __future__ import annotations

import csv
import io
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from ..model.datasheet_link import DatasheetLink
from ..model.finding import Finding
from ..model.severity import Severity
from .subprocess_runner import DEFAULT_GIT_TIMEOUT, DEFAULT_KICAD_TIMEOUT, SubprocessTimeoutError
from .subprocess_runner import run as subprocess_run

_log = logging.getLogger(__name__)

DEFAULT_LIBRARY_REPO: Path = Path.home() / "Dropbox" / "KiCad" / "SPCoast-inventory"
"""SPCoast convention for the local ``SPCoast-inventory`` clone used by the
advisory publish guard (mirrors ``metadata_analyzer._DEFAULT_PROJECTS_ROOT``'s
``~/Dropbox/KiCad/projects`` convention)."""

_LIBRARY_OWNER_REPO: str = "plocher/SPCoast-inventory"
"""The public library repo's ``<owner>/<repo>`` slug (jBOM#350 resolution)."""

_VIEW_URL_TEMPLATE: str = (
    f"https://github.com/{_LIBRARY_OWNER_REPO}/blob/main/datasheets/{{name}}.pdf"
)
_DOWNLOAD_URL_TEMPLATE: str = (
    f"https://raw.githubusercontent.com/{_LIBRARY_OWNER_REPO}/main/datasheets/{{name}}.pdf"
)

_DATASHEET_NAME_COLUMN: str = "Datasheet Name"
"""The jBOM ``--fields`` output header (jBOM#359), as it lands in ``jbom.csv``."""

_GIT_INVOCATION_ERRORS: tuple[type[Exception], ...] = (SubprocessTimeoutError, OSError)
"""Mirrors ``common.github_link``'s collapsing of git failure modes: a slow
or broken git can only make the guard conservative (emit the advisory
warning), never abort a publish."""


def _strip_pdf_suffix(name: str) -> str:
    """Return *name* with a single trailing ``.pdf``/``.PDF`` suffix removed.

    The curated ``Datasheet Name`` is documented as the bare name (the
    library's glossary: "the bare name resolves to
    ``datasheets/<name>.pdf``"), but tolerate a BOM value that already
    carries the suffix so kproj never publishes a ``*.pdf.pdf`` link.
    """
    if name.lower().endswith(".pdf"):
        return name[: -len(".pdf")]
    return name


def build_datasheet_link(name: str) -> DatasheetLink:
    """Construct the deterministic view + download URLs for *name*.

    Pure function — no I/O — per the jBOM#350 URL contract: ``main``
    branch, no commit pinning.

    Args:
        name: The curated ``Datasheet Name`` (bare name, optionally
            carrying a redundant ``.pdf`` suffix, which is stripped).

    Returns:
        A populated :class:`DatasheetLink`.
    """
    bare = _strip_pdf_suffix(name)
    return DatasheetLink(
        name=bare,
        view_url=_VIEW_URL_TEMPLATE.format(name=bare),
        download_url=_DOWNLOAD_URL_TEMPLATE.format(name=bare),
    )


JbomInvoker = Sequence[str]
"""Type alias documenting the argv shape a caller may inject in place of
the real ``python -m jbom`` invocation, for hermetic testing."""


def _default_jbom_command(project_dir: Path, inventory: Path | None) -> list[str]:
    """Build the ``python -m jbom bom ...`` argv for datasheet-name lookup.

    Uses ``[sys.executable, "-m", "jbom", ...]`` rather than a bare
    ``jbom`` on ``PATH``: jBOM is a normal Python dependency of kproj
    (``tool.uv.sources``), guaranteed importable in kproj's own venv,
    so this needs no separate executable-discovery locator (unlike
    kicad-cli, which lives outside any Python environment).
    """
    command = [
        sys.executable,
        "-m",
        "jbom",
        "bom",
        str(project_dir),
        "-f",
        _DATASHEET_NAME_COLUMN,
        "-o",
        "-",
    ]
    if inventory is not None:
        command.extend(["--inventory", str(inventory)])
    return command


def read_datasheet_names(
    project_dir: Path,
    inventory: Path | None = None,
    *,
    project: str = "",
    jbom_command: Sequence[str] | None = None,
) -> tuple[tuple[str, ...], tuple[Finding, ...]]:
    """Return the distinct curated ``Datasheet Name`` values via ``jbom bom``.

    Invokes ``jbom bom <project_dir> -f "Datasheet Name" -o -`` (plus
    ``--inventory <inventory>`` when configured) and parses the CSV
    from stdout. This queries jBOM's *current* view of the inventory at
    publish time rather than a stale ``production/jbom.csv`` fab
    snapshot (kproj#29 ticket-owner ruling amending ADR 0003 — see
    ``docs/adr/0010-live-jbom-bom-invocation-for-datasheet-names.md``).

    Every failure mode - jbom missing, too old to recognise the field,
    a non-zero exit, a subprocess timeout, or unparseable output -
    degrades to an advisory ``Finding`` rather than raising: the
    datasheet-name lookup is never a publish blocker. Rows with an
    absent or empty ``Datasheet Name`` (uncurated Items) are silently
    excluded - no per-row finding, per the Acceptance criterion.

    Args:
        project_dir: The resolved KiCad project directory (``jbom bom``
            accepts a project directory, ``.kicad_sch`` path, or
            basename; kproj always passes the resolved directory).
        inventory: Optional inventory CSV path forwarded as ``jbom bom
            --inventory``. ``None`` omits the flag; jBOM then has no
            curated data to join against, so every row's ``Datasheet
            Name`` comes back blank (a valid, advisory-free degraded
            state - not every project need be inventory-curated).
        project: Project basename, threaded onto any emitted
            :class:`Finding`.
        jbom_command: Test-only seam: an explicit argv to run instead of
            the real ``python -m jbom bom ...`` invocation. Production
            callers omit this; hermetic tests inject a fake script.

    Returns:
        A 2-tuple of:
        - The distinct names, case-insensitively sorted, with any
          redundant ``.pdf`` suffix left intact (callers pass names
          through :func:`build_datasheet_link`, which strips it).
        - Diagnostics: empty in the happy path; one warning ``Finding``
          when the invocation fails or the ``Datasheet Name`` column is
          absent from its output.
    """
    command = (
        list(jbom_command)
        if jbom_command is not None
        else _default_jbom_command(project_dir, inventory)
    )

    try:
        result = subprocess_run(command, timeout=DEFAULT_KICAD_TIMEOUT, check=False)
    except (SubprocessTimeoutError, OSError) as exc:
        return (), (
            Finding(
                severity=Severity.WARNING,
                field="datasheet_field_missing",
                value=" ".join(command),
                reason=(
                    f"`jbom bom` invocation failed ({exc}); publishing without "
                    "datasheet links. Ensure jBOM is installed and importable."
                ),
                project=project,
            ),
        )

    if result.returncode != 0:
        return (), (
            Finding(
                severity=Severity.WARNING,
                field="datasheet_field_missing",
                value=" ".join(command),
                reason=(
                    f"`jbom bom` exited {result.returncode}; publishing without "
                    f"datasheet links. stderr: {result.stderr.strip() or '(empty)'}"
                ),
                project=project,
            ),
        )

    reader = csv.DictReader(io.StringIO(result.stdout))
    fieldnames = reader.fieldnames or ()
    if _DATASHEET_NAME_COLUMN not in fieldnames:
        return (), (
            Finding(
                severity=Severity.WARNING,
                field="datasheet_field_missing",
                value=" ".join(command),
                reason=(
                    f"`jbom bom` output has no '{_DATASHEET_NAME_COLUMN}' column; "
                    "publishing without datasheet links. This jBOM version may "
                    "predate the Datasheet Name field (jBOM >= 7.4.0 required)."
                ),
                project=project,
            ),
        )
    names = {
        row[_DATASHEET_NAME_COLUMN].strip()
        for row in reader
        if row.get(_DATASHEET_NAME_COLUMN, "").strip()
    }
    return tuple(sorted(names, key=str.lower)), ()


def check_datasheet_links(
    names: Sequence[str],
    library_repo: Path,
    *,
    project: str = "",
) -> tuple[Finding, ...]:
    """Advisory-only guard: warn on unresolvable or not-yet-pushed names.

    Read-only against *library_repo* (the conventional local
    ``SPCoast-inventory`` clone). Never blocks a publish and never
    raises — every failure mode (missing clone, not a git repo,
    mechanical git failure) collapses to a warning ``Finding``, mirroring
    :mod:`kproj.common.github_link`'s conservative-collapse precedent.

    Args:
        names: Distinct ``Datasheet Name`` values to check (as returned
            by :func:`read_datasheet_names`).
        library_repo: Local clone of ``plocher/SPCoast-inventory``.
        project: Project basename, threaded onto emitted findings.

    Returns:
        A tuple of warning findings (empty in the happy path):
        - ``datasheet_library_missing`` when *library_repo* isn't a
          local git work tree at all (checked once, not per-name).
        - ``datasheet_library_unpushed`` when the clone's ``HEAD`` isn't
          confirmed pushed to its upstream (checked once).
        - ``datasheet_unresolvable`` per name whose
          ``datasheets/<name>.pdf`` isn't found in the local clone.
    """
    if not names:
        return ()

    if not _is_git_work_tree(library_repo):
        return (
            Finding(
                severity=Severity.WARNING,
                field="datasheet_library_missing",
                value=str(library_repo),
                reason=(
                    f"datasheet library clone not found at {library_repo}; cannot "
                    f"confirm {len(names)} datasheet link(s) resolve or are pushed. "
                    "Clone plocher/SPCoast-inventory there, or override the path."
                ),
                project=project,
            ),
        )

    findings: list[Finding] = []
    if not _head_is_pushed(library_repo):
        findings.append(
            Finding(
                severity=Severity.WARNING,
                field="datasheet_library_unpushed",
                value=str(library_repo),
                reason=(
                    "datasheet library clone's current commit isn't confirmed pushed "
                    "to its upstream; published deep-links may 404 until it is pushed"
                ),
                project=project,
            )
        )

    datasheets_dir = library_repo / "datasheets"
    for name in names:
        candidate = datasheets_dir / f"{_strip_pdf_suffix(name)}.pdf"
        if not candidate.is_file():
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    field="datasheet_unresolvable",
                    value=name,
                    reason=(
                        f"{candidate.name} not found in the local datasheet library "
                        f"clone ({datasheets_dir}); the published link may 404"
                    ),
                    project=project,
                )
            )
    return tuple(findings)


def _is_git_work_tree(repo_dir: Path) -> bool:
    """Return whether *repo_dir* is inside a git work tree.

    Mirrors ``common.github_link._is_git_work_tree``.
    """
    try:
        result = subprocess_run(
            ["git", "-C", str(repo_dir), "rev-parse", "--is-inside-work-tree"],
            timeout=DEFAULT_GIT_TIMEOUT,
            check=False,
        )
    except _GIT_INVOCATION_ERRORS:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _head_is_pushed(repo_dir: Path) -> bool:
    """Return whether local ``HEAD`` matches its configured upstream ref.

    Uses only refs already present locally (``@{u}``) — never fetches.
    Mirrors ``common.github_link._head_is_pushed``.
    """
    upstream = _git_output(repo_dir, ["rev-parse", "@{u}"])
    if upstream is None:
        return False
    head = _git_output(repo_dir, ["rev-parse", "HEAD"])
    if head is None:
        return False
    return head == upstream


def _git_output(repo_dir: Path, args: list[str]) -> str | None:
    """Run a git sub-command and return its trimmed stdout, or ``None`` on failure."""
    try:
        result = subprocess_run(
            ["git", "-C", str(repo_dir), *args],
            timeout=DEFAULT_GIT_TIMEOUT,
            check=False,
        )
    except _GIT_INVOCATION_ERRORS:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()
