"""Datasheet deep-links from the BOM's curated ``Datasheet Name`` column.

Per the datasheet document library map (``plocher/jBOM#342``), its
publish-mechanics resolution (``plocher/jBOM#350``), the kproj#29
ticket-owner's live-lookup ruling (ADR 0003 amendment), and the kproj#36
follow-up ruling that fixed the broken invocation and multi-field shape
(see ``docs/adr/0010-live-jbom-bom-invocation-for-datasheet-names.md``):

1. **Resolution path**: kproj invokes ``jbom -q bom <project_dir>
   --inventory <path> --fabricator <profile>
   -f "reference,datasheet,datasheet_name" -o -``
   at publish time and parses the CSV from stdout
   (:func:`read_datasheet_rows`) into structured, **per-reference**
   rows. This is a deliberate, narrowly-scoped exception to ADR 0003's
   "read, don't invoke": ``production/jbom.csv`` is a stale,
   fab-oriented snapshot that may predate the ``Datasheet Name`` field
   entirely, whereas datasheet links must reflect the *current*
   inventory. kproj still never writes to the inventory, never runs
   ``jbom fab``, and never invokes any other jBOM subcommand. The
   global ``-q`` flag (kproj#41) suppresses jBOM's info/warning
   guidance diagnostics on stderr; errors still print.
2. **PATH invocation, `-m` fallback**: the ``jbom`` executable is
   resolved from ``PATH`` (:func:`shutil.which`); when not found on
   ``PATH`` kproj falls back to ``[sys.executable, "-m", "jbom"]``
   (jBOM is also a normal Python dependency of kproj). Both invocation
   shapes degrade to the same advisory finding on failure.
3. **No inventory, no invocation (kproj#36 owner ruling)**: the
   ``datasheet_name`` column only exists in the inventory, so when
   ``inventory`` is unconfigured (``None``) kproj never builds or
   runs the ``jbom bom`` command at all - there is no data to fetch.
   This is a silent, advisory-free degraded state (the kproj#37
   first-run INFO hint is the discoverability companion), not the
   "invoke without ``--inventory`` and accept blank columns" behavior
   this module previously implemented.
4. **Extensible field list**: :data:`DATASHEET_BOM_FIELDS` is a single
   declared, comma-joined constant built from a field-token tuple.
   Today it fetches ``reference,datasheet,datasheet_name`` - general
   BOM-row plumbing whose eventual consumer is the iBOM
   interactive-BOM viewer (out of scope for kproj#36 itself), which
   will need more fields; extending the tuple is the only change
   required.
5. **Site representation**: no site copies. Published pages deep-link
   the public datasheet-library repo directly (default
   ``plocher/SPCoast-inventory``, overridable per
   :mod:`kproj.config`'s ``datasheet_repo`` precedence).
   :func:`build_datasheet_link` constructs the two deterministic URLs
   (view + download) from a curated name.
6. **URL-stability**: ``main``-branch URLs, no commit pinning — the
   library's Never-Rename / append-only invariant guarantees they
   cannot rot.
7. **Guard**: :func:`check_datasheet_links` is kproj's advisory-only
   publish check. It runs read-only against the conventional local
   library clone path (default :data:`kproj.config.DEFAULT_DATASHEET_LIBRARY`,
   overridable per :mod:`kproj.config`'s ``datasheet_library``
   precedence - mirrors the ``~/Dropbox/KiCad/projects`` convention
   used by :mod:`kproj.services.metadata_analyzer` for
   ``replaced-by:<X>`` resolution) and emits warning findings for
   unresolvable or not-yet-pushed names. It never blocks a publish:
   short 404 windows on rarely-followed links are acceptable, and
   publish/push ordering is owned by Makefile orchestration, not a
   kproj gate.

The per-project ``*.pdf`` disk-walk (:mod:`kproj.common.project_docs`'
former ``discover_datasheets`` / ``discover_datasheet_files``) and its
site-copy sibling (``_copy_datasheets`` in
:mod:`kproj.application.publish_workflow`) are retired: the
project-index Documentation list derives its distinct names from the
structured :func:`read_datasheet_rows` rows via
:func:`distinct_datasheet_names`.
"""

from __future__ import annotations

import csv
import io
import logging
import re
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.parse import quote as _urlquote

from ..config import DEFAULT_DATASHEET_REPO, DEFAULT_FABRICATOR
from ..model.datasheet_link import DatasheetLink
from ..model.datasheet_row import DatasheetRow
from ..model.finding import Finding
from ..model.severity import Severity
from .subprocess_runner import DEFAULT_GIT_TIMEOUT, DEFAULT_KICAD_TIMEOUT, SubprocessTimeoutError
from .subprocess_runner import run as subprocess_run

_log = logging.getLogger(__name__)

_DATASHEET_BOM_FIELD_TOKENS: tuple[str, ...] = ("reference", "datasheet", "datasheet_name")
"""Extensible field-token tuple joined into :data:`DATASHEET_BOM_FIELDS`.

General BOM-row plumbing (kproj#36 owner ruling): the eventual consumer
is the iBOM interactive-BOM viewer, which will need more fields than
``datasheet_name`` alone. Adding a future field is a one-line change
to this tuple; nothing else in this module hardcodes the field list.
"""

DATASHEET_BOM_FIELDS: str = ",".join(_DATASHEET_BOM_FIELD_TOKENS)
"""The ``jbom bom -f`` value: comma-separated, normalized field tokens
(NOT display headers - see the kproj#36 bug this constant fixes)."""

_IBOM_BOM_FIELD_TOKENS: tuple[str, ...] = (
    "reference",
    "datasheet",
    "datasheet_name",
    "manufacturer",
    "mfgpn",
    "fabricator_part_number",
    "description",
    "dnp",
)
"""Field-token tuple for inventory-enriched iBOM data extraction.

The values are intentionally inventory-facing and map directly onto the
iBOM interactive table fields we surface in kproj#48.
"""

IBOM_BOM_FIELDS: str = ",".join(_IBOM_BOM_FIELD_TOKENS)
"""The ``jbom bom -f`` value used by :func:`read_ibom_rows`."""
DEFAULT_JBOM_FABRICATOR: str = DEFAULT_FABRICATOR
"""Default jBOM fabricator mode for lookup command generation."""

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


def build_datasheet_link(name: str, *, owner_repo: str = DEFAULT_DATASHEET_REPO) -> DatasheetLink:
    """Construct the deterministic view + download URLs for *name*.

    Pure function — no I/O — per the jBOM#350 URL contract: ``main``
    branch, no commit pinning. The URL path segment is percent-encoded
    (:func:`urllib.parse.quote`, default ``safe="/"``) so a curated name
    containing a space or other reserved character still produces a
    well-formed URL; the library's current names are hyphenated ASCII
    in practice, but nothing upstream enforces that convention.

    Args:
        name: The curated ``Datasheet Name`` (bare name, optionally
            carrying a redundant ``.pdf`` suffix, which is stripped).
            :attr:`DatasheetLink.name` carries the raw (unencoded) bare
            name; only the URL fields are encoded.
        owner_repo: The public library repo's ``<owner>/<repo>`` slug.
            Defaults to :data:`kproj.config.DEFAULT_DATASHEET_REPO`;
            production callers pass ``KprojConfig.datasheet_repo`` so a
            CLI/env/yaml override (kproj#37) is honored.

    Returns:
        A populated :class:`DatasheetLink`.
    """
    bare = _strip_pdf_suffix(name)
    encoded = _urlquote(bare)
    return DatasheetLink(
        name=bare,
        view_url=f"https://github.com/{owner_repo}/blob/main/datasheets/{encoded}.pdf",
        download_url=(
            f"https://raw.githubusercontent.com/{owner_repo}/main/datasheets/{encoded}.pdf"
        ),
    )


JbomInvoker = Sequence[str]
"""Type alias documenting the argv shape a caller may inject in place of
the real ``jbom bom`` invocation, for hermetic testing."""


def _resolve_jbom_executable() -> tuple[str, ...]:
    """Return the argv prefix that invokes ``jbom`` (kproj#36 owner ruling).

    Prefers the ``jbom`` executable on ``PATH`` (:func:`shutil.which`);
    falls back to ``[sys.executable, "-m", "jbom"]`` when not found
    (jBOM is also a normal Python dependency of kproj). Both shapes
    degrade to the same advisory finding on failure.
    """
    jbom_path = shutil.which("jbom")
    if jbom_path is not None:
        return (jbom_path,)
    return (sys.executable, "-m", "jbom")


def jbom_tool_report() -> str:
    """Return a human-readable report for the jBOM command kproj will use."""
    command = _resolve_jbom_executable()
    location = " ".join(command)
    fallback = " (Python module fallback)" if len(command) > 1 else ""
    try:
        result = subprocess_run([*command, "--version"], check=False)
    except (SubprocessTimeoutError, OSError):
        return f"Info: Using jbom (version unknown) at {location}{fallback}"
    version = (
        result.stdout.strip().splitlines()[0] if result.stdout.strip() else "jbom (version unknown)"
    )
    return f"Info: Using {version} at {location}{fallback}"


def _default_jbom_command(
    project_dir: Path,
    inventory: Path | None,
    *,
    fabricator: str = DEFAULT_JBOM_FABRICATOR,
    fields: str = DATASHEET_BOM_FIELDS,
) -> list[str] | None:
    """Build the ``jbom -q bom ...`` argv for a BOM-row lookup.

    Returns ``None`` when *inventory* is unconfigured: per the kproj#36
    owner ruling, the ``datasheet_name`` column only exists in the
    inventory, so there is nothing to fetch and the command is never
    built (callers must not invoke jBOM at all in that case).

    ``-q`` (kproj#41) is jBOM's *global* quiet flag - it suppresses
    info/warning guidance diagnostics (e.g. "Missing important generic
    fields: ...") on stderr so they don't leak into kproj's terminal /
    captured stderr during a publish run. Errors still print. Being a
    global flag, it MUST precede the ``bom`` subcommand. No version
    detection or fallback: per the owner ruling, latest jBOM and latest
    kproj are always used together (the flag is a no-op, not an error,
    against any jBOM version that already understands ``-q``).
    """
    if inventory is None:
        return None
    return [
        *_resolve_jbom_executable(),
        "-q",
        "bom",
        str(project_dir),
        "--inventory",
        str(inventory),
        "--fabricator",
        fabricator,
        "-f",
        fields,
        "-o",
        "-",
    ]


def _display_header(field: str) -> str:
    """Return jBOM's rendered CSV header for a normalized field token.

    jBOM renders a title-cased, space-joined header regardless of the
    ``-f`` token's casing (verified against real jBOM 7.8.0:
    ``-f reference,datasheet,datasheet_name`` renders
    ``"Reference","Datasheet","Datasheet Name"``). This is the parser
    side of the kproj#36 fix: the *token* passed to ``-f`` must be
    normalized snake_case, but the *column* it renders under is still
    the display header.
    """
    return field.replace("_", " ").title()


def _normalize_csv_header(name: str) -> str:
    """Normalize a CSV header label to a lookup token."""
    collapsed = re.sub(r"[^a-z0-9]+", "_", name.strip().lower())
    return collapsed.strip("_")


def _normalize_csv_row(row: Mapping[str, str | None]) -> dict[str, str]:
    """Return a normalized-header mapping with stripped string values."""
    return {
        _normalize_csv_header(str(key)): (value or "").strip()
        for key, value in row.items()
        if key is not None
    }


def _first_present(normalized_row: Mapping[str, str], *aliases: str) -> str:
    """Return the first non-empty value among normalized-header aliases."""
    for alias in aliases:
        value = normalized_row.get(alias, "").strip()
        if value:
            return value
    return ""


def _expand_references(reference_cell: str) -> tuple[str, ...]:
    """Expand jBOM's aggregated reference cell into per-reference tokens.

    jBOM emits grouped references as comma-delimited strings
    (e.g. ``\"R8, R9, R21, R22\"``). iBOM extra-data matching is
    per-reference, so this splitter normalizes grouped cells into a
    stable tuple.
    """
    return tuple(part.strip() for part in reference_cell.split(",") if part.strip())


def read_datasheet_rows(
    project_dir: Path,
    inventory: Path | None = None,
    *,
    project: str = "",
    fabricator: str = DEFAULT_JBOM_FABRICATOR,
    jbom_command: Sequence[str] | None = None,
) -> tuple[tuple[DatasheetRow, ...], tuple[Finding, ...]]:
    """Return structured per-reference BOM rows via a live ``jbom bom`` query.

    Invokes ``jbom -q bom <project_dir> --inventory <path>
    --fabricator <profile> -f
    "reference,datasheet,datasheet_name" -o -`` (the PATH executable;
    see :func:`_resolve_jbom_executable`) and parses the CSV from
    stdout. This queries jBOM's *current* view of the inventory at
    publish time rather than a stale ``production/jbom.csv`` fab
    snapshot (kproj#29 ticket-owner ruling amending ADR 0003 — see
    ``docs/adr/0010-live-jbom-bom-invocation-for-datasheet-names.md``).

    Per the kproj#36 owner ruling, when *inventory* is ``None`` and no
    *jbom_command* test seam is injected, the subprocess is never
    built or run at all: there is no advisory finding either, since
    omitting ``--inventory`` is a deliberate configuration choice, not
    a failure (the kproj#37 first-run INFO hint is the discoverability
    companion). Every other failure mode - jbom missing, too old to
    recognise the field, a non-zero exit, a subprocess timeout, or a
    missing ``Datasheet Name`` column - degrades to an advisory
    ``Finding`` rather than raising: the lookup is never a publish
    blocker.

    Args:
        project_dir: The resolved KiCad project directory (``jbom bom``
            accepts a project directory, ``.kicad_sch`` path, or
            basename; kproj always passes the resolved directory).
        inventory: Optional inventory CSV path forwarded as ``jbom bom
            --inventory``. ``None`` skips the invocation entirely.
        fabricator: jBOM fabricator profile forwarded as
            ``jbom bom --fabricator``.
        project: Project basename, threaded onto any emitted
            :class:`Finding`.
        jbom_command: Test-only seam: an explicit argv to run instead of
            the real ``jbom bom ...`` invocation. Production callers
            omit this; hermetic tests inject a fake script. When given,
            the command always runs regardless of *inventory*.

    Returns:
        A 2-tuple of:
        - Every parsed row (including uncurated references with an
          empty ``datasheet_name``) - callers wanting only curated,
          deduped names should use :func:`distinct_datasheet_names`.
        - Diagnostics: empty in the happy path (including the
          no-inventory skip); one warning ``Finding`` when the
          invocation fails or the ``Datasheet Name`` column is absent
          from its output.
    """
    if jbom_command is not None:
        command = list(jbom_command)
    else:
        built = _default_jbom_command(project_dir, inventory, fabricator=fabricator)
        if built is None:
            return (), ()
        command = built

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
                    "datasheet links. Ensure jBOM is installed and on PATH."
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
    normalized_fieldnames = {_normalize_csv_header(name) for name in fieldnames}
    if "datasheet_name" not in normalized_fieldnames:
        return (), (
            Finding(
                severity=Severity.WARNING,
                field="datasheet_field_missing",
                value=" ".join(command),
                reason=(
                    "`jbom bom` output has no 'Datasheet Name' column; "
                    "publishing without datasheet links. This jBOM version may "
                    "predate the Datasheet Name field (jBOM >= 7.4.0 required)."
                ),
                project=project,
            ),
        )
    rows: list[DatasheetRow] = []
    for row in reader:
        normalized_row = _normalize_csv_row(row)
        references = _expand_references(_first_present(normalized_row, "reference", "designator"))
        datasheet = normalized_row.get("datasheet", "")
        datasheet_name = normalized_row.get("datasheet_name", "")
        manufacturer = normalized_row.get("manufacturer", "")
        mfgpn = normalized_row.get("mfgpn", "")
        mpn = normalized_row.get("mpn", "") or mfgpn
        fabricator_part_number = _first_present(
            normalized_row,
            "fabricator_part_number",
            "supplier_part_number",
            "lcsc_part_number",
            "lcsc_part",
            "lcsc",
        )
        description = _first_present(normalized_row, "description", "comment")
        dnp = normalized_row.get("dnp", "")

        if not references:
            references = ("",)
        for reference in references:
            rows.append(
                DatasheetRow(
                    reference=reference,
                    datasheet=datasheet,
                    datasheet_name=datasheet_name,
                    manufacturer=manufacturer,
                    mfgpn=mfgpn,
                    mpn=mpn,
                    fabricator_part_number=fabricator_part_number,
                    description=description,
                    dnp=dnp,
                )
            )
    return tuple(rows), ()


def read_ibom_rows(
    project_dir: Path,
    inventory: Path | None = None,
    *,
    project: str = "",
    fabricator: str = DEFAULT_JBOM_FABRICATOR,
    jbom_command: Sequence[str] | None = None,
) -> tuple[tuple[DatasheetRow, ...], tuple[Finding, ...]]:
    """Return per-reference rows with inventory fields for iBOM enrichment.

    This is the kproj#48 companion to :func:`read_datasheet_rows`: it
    uses an expanded ``-f`` list (see :data:`IBOM_BOM_FIELDS`) that
    includes supply-chain columns needed by iBOM. Grouped references in
    jBOM BOM output are expanded into one :class:`DatasheetRow` per
    reference, preserving iBOM's per-reference lookup contract.
    """
    if jbom_command is not None:
        command = list(jbom_command)
    else:
        built = _default_jbom_command(
            project_dir,
            inventory,
            fabricator=fabricator,
            fields=IBOM_BOM_FIELDS,
        )
        if built is None:
            return (), ()
        command = built
    return read_datasheet_rows(
        project_dir,
        inventory,
        project=project,
        fabricator=fabricator,
        jbom_command=command,
    )


def distinct_datasheet_names(rows: Sequence[DatasheetRow]) -> tuple[str, ...]:
    """Return the distinct, case-insensitively deduped, sorted curated names.

    The project-index Documentation list derives its distinct names
    from :func:`read_datasheet_rows`' structured rows via this helper
    (kproj#36 acceptance criterion), rather than the lookup collapsing
    to a single-column shape internally.

    Dedup is case-insensitive: the library's stated uniqueness
    invariant (SPCoast-inventory's glossary: "Names are unique
    case-insensitively") means a curation slip upstream that produces
    two different casings of the same document must not survive as
    two distinct links. First-seen casing wins per name-fold; the
    final order is case-insensitively sorted.

    Args:
        rows: Rows as returned by :func:`read_datasheet_rows`. Rows
            with an absent or empty ``datasheet_name`` (uncurated
            references) contribute nothing.

    Returns:
        The distinct names, case-insensitively sorted.
    """
    by_fold: dict[str, str] = {}
    for row in rows:
        raw = row.datasheet_name.strip()
        if raw:
            by_fold.setdefault(raw.casefold(), raw)
    return tuple(sorted(by_fold.values(), key=str.lower))


def read_datasheet_names(
    project_dir: Path,
    inventory: Path | None = None,
    *,
    project: str = "",
    fabricator: str = DEFAULT_JBOM_FABRICATOR,
    jbom_command: Sequence[str] | None = None,
) -> tuple[tuple[str, ...], tuple[Finding, ...]]:
    """Return the distinct curated ``Datasheet Name`` values via ``jbom bom``.

    Convenience wrapper composing :func:`read_datasheet_rows` +
    :func:`distinct_datasheet_names` for callers that only need the
    distinct-name shape (e.g. the advisory :func:`check_datasheet_links`
    guard). See :func:`read_datasheet_rows` for the full argument and
    failure-mode documentation.

    Returns:
        A 2-tuple of ``(names, findings)`` - the distinct,
        case-insensitively sorted curated names, and diagnostics
        (empty in the happy path; one warning ``Finding`` on failure).
    """
    rows, findings = read_datasheet_rows(
        project_dir,
        inventory,
        project=project,
        fabricator=fabricator,
        jbom_command=jbom_command,
    )
    return distinct_datasheet_names(rows), findings


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
                value=library_repo.name,
                reason=(
                    f"datasheet library clone not found ({library_repo.name}); cannot "
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
                value=library_repo.name,
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
        if not _is_file_safe(candidate):
            findings.append(
                Finding(
                    severity=Severity.WARNING,
                    field="datasheet_unresolvable",
                    value=name,
                    reason=(
                        f"{candidate.name} not found in the local datasheet library; "
                        "the published link may 404"
                    ),
                    project=project,
                )
            )
    return tuple(findings)


def _is_file_safe(path: Path) -> bool:
    """Return whether *path* is a regular file, tolerating filesystem errors.

    ``Path.is_file()`` can raise ``OSError`` for reasons unrelated to
    "the file doesn't exist" - a symlink cycle (``ELOOP``), a permission
    error walking a parent directory, or similar. Per the advisory-only
    guard's contract, any such surprise is treated the same as "not
    found" (conservative: warn, never crash the publish).
    """
    try:
        return path.is_file()
    except OSError:
        return False


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
