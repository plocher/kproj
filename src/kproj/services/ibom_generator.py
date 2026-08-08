"""The :class:`IbomGenerator` service.

Per ``docs/adr/0008-ibom-direct-script-invocation.md`` +
``docs/DESIGN.md`` § *IbomGenerator*, this service invokes the
``generate_interactive_bom.py`` PCM-installed script directly via
``subprocess.run`` rather than via ``kicad-cli jobset run``. The
``kicad-cli`` job runner requires a live KiCad GUI process, which
contradicts kproj's locked non-interactive Makefile / CI use case
(ADR 0007).

The argv, fixed by ADR 0008:

    <python> <ibom_script>
        --no-browser --no-compression
        --dest-dir <staging>
        --name-format <P>-<R>.ibom
        --extra-data-file <pcb|inventory-xml>
        --dnp-field kicad_dnp
        --layer-view <F|B|FB>
        --extra-fields <configured-extra-fields>
        --include-tracks
        <pcb>

``--layer-view`` is chosen from footprint placement sides on the PCB:
front-only -> ``F``, back-only -> ``B``, both sides -> ``FB``. Empty or
unparseable boards fall back to ``F``. iBOM filters the BOM table by the
active canvas layer, so a fixed ``F`` default hides back-side parts on
mixed boards (e.g. bottom connectors) until the visitor switches view.

``<python>`` is **KiCad's bundled Python interpreter**, resolved by
:func:`kproj.common.kicad_install.find_kicad_python` during pre-flight
and injected at construction time.  It is NOT :data:`sys.executable`:
the iBOM script does ``import pcbnew`` unconditionally, and ``pcbnew``
is a SWIG C-extension that resolves only inside KiCad's own
interpreter, never in kproj's ``uv``-managed venv (see ADR 0008's
amendment / kproj#10).  ``<ibom_script>`` is likewise resolved by
:func:`kproj.common.kicad_install.find_ibom_script` during pre-flight.

The script writes ``<staging>/<name-format>.html``. The service moves
that file to the caller's *output_file* via :func:`os.replace` so the
release-asset filename is independent of the iBOM staging directory.
"""

from __future__ import annotations

import html
import json
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from pathlib import Path

from ..common.datasheet_library import build_datasheet_link
from ..common.install_info import InstallInfo, format_provenance
from ..common.subprocess_runner import DEFAULT_KICAD_TIMEOUT
from ..common.subprocess_runner import run as subprocess_run
from ..model.datasheet_row import DatasheetRow
from ..model.export_result import ExportResult
from .change_journal import ChangeJournal

_IBOM_HEADLESS_ENV_VAR = "INTERACTIVE_HTML_BOM_NO_DISPLAY"
"""Set in the subprocess env so iBOM doesn't require wxPython for display init.

The PCM-installed iBOM script imports wxPython unconditionally unless this
env var is set, and `wxPython` is typically not in the kproj venv (we're a
non-interactive Makefile / CI tool per ADR 0007 + ADR 0008).  Setting the
var lets the script run headless against the locally-installed PCM iBOM.
"""

_DEFAULT_EXTRA_FIELDS: tuple[str, ...] = ("MPN", "Manufacturer")
"""Backwards-compatible default extra fields (ADR 0008 contract)."""

_TRUE_DNP_MARKERS: frozenset[str] = frozenset({"1", "true", "yes", "y", "dnp"})
"""Truthy string markers treated as DNP during XML projection."""
_IBOM_FALLBACK_LAYER_VIEW = "F"
"""Initial layer view when the PCB has no detectable footprint sides."""

_FOOTPRINT_BLOCK_RE = re.compile(
    r"\(footprint\b",
    re.MULTILINE,
)
"""Matches the start of a footprint s-expression in a ``.kicad_pcb``."""

_FOOTPRINT_LAYER_RE = re.compile(
    r"\(layer\s+\"([FB])\.Cu\"\)",
)
"""Matches the footprint's own copper placement layer (not nested pads)."""

_FOOTPRINT_ATTR_RE = re.compile(
    r"\(attr\s+([^)]*)\)",
)
"""Matches the footprint ``(attr ...)`` token list."""

_IGNORED_FOOTPRINT_ATTR_TOKENS: frozenset[str] = frozenset(
    {
        "board_only",
        "exclude_from_bom",
    }
)
"""Attr tokens whose footprints are ignored for default layer-view choice.

``board_only`` / ``exclude_from_bom`` parts are typically mechanical and
are not listed in the iBOM table, so they should not force ``FB``.
"""

_IBOM_USER_CSS_TEMPLATE = """/* Managed by kproj -- regenerated on every publish. Do not hand-edit.
 * __PROVENANCE__
 * See src/kproj/services/ibom_generator.py (write_ibom_user_files).
 *
 * Uses iBOM's supported user.css customization hook
 * (https://github.com/openscopeproject/InteractiveHtmlBom/wiki/Customization).
 * This stylesheet is appended after iBOM's built-in CSS in the same
 * <style> block, so same-specificity selectors here win by source
 * order alone -- no anchor matching against iBOM's own CSS text.
 */
.bom {
  table-layout: auto;
}
.bom th[col_name="References"] {
  width: 8.5ch;
  min-width: 7.2ch;
  max-width: 11ch;
}
.bom th[col_name="Value"] {
  width: 11ch;
  min-width: 9ch;
  max-width: 15ch;
}
.bom th[col_name="Details"] {
  width: 20ch;
  min-width: 16ch;
  max-width: 28ch;
}
.bom th[col_name="Description"] {
  width: auto;
}
/* th.numCol hosts the column-visibility menu button/dropdown
 * (#vismenu / #vismenu-content). It is intentionally left
 * unconstrained here: forcing it narrow previously corrupted that
 * dropdown's own sizing and serves no layout purpose. */
#vismenu-content {
  max-height: 70vh;
  overflow-y: auto;
  z-index: 4000;
}
.bom thead {
  position: relative;
  z-index: 1200;
}
.bom tbody {
  position: relative;
  z-index: 1;
}
"""
"""``user.css`` template; ``__PROVENANCE__`` is filled in by :func:`_build_user_css`."""

_IBOM_USER_JS_TEMPLATE = """// Managed by kproj -- regenerated on every publish. Do not hand-edit.
// __PROVENANCE__
// See src/kproj/services/ibom_generator.py (write_ibom_user_files).
//
// Uses iBOM's supported user.js customization hook
// (https://github.com/openscopeproject/InteractiveHtmlBom/wiki/Customization)
// instead of patching iBOM's own generated/bundled HTML, CSS, or JS.

(function seedSpcoastDefaultHiddenColumns() {
  // Seed a first-visit default (only when the visitor has no saved
  // preference yet) using iBOM's own storage-key convention (see
  // util.js: `storagePrefix` + readStorage/writeStorage), so that
  // initDefaults() reads it exactly as if a visitor had chosen it via
  // the UI once. This runs at parse time, before iBOM's own
  // window.onload calls initStorage()/initDefaults(), so `storage`
  // (iBOM's own abstraction) isn't set up yet; we talk to
  // window.localStorage directly instead, using the same prefix.
  try {
    var key = storagePrefix + "hiddenColumns";
    if (window.localStorage.getItem(key) === null) {
      window.localStorage.setItem(key, JSON.stringify(["checkboxes", "Footprint"]));
    }
  } catch (e) {
    // localStorage unavailable (e.g. private browsing); iBOM's own
    // built-in default (nothing hidden) takes over silently.
  }
})();

// Cosmetically relabel "References" to "Ref" in the rendered UI by
// editing rendered text nodes rather than iBOM's source. The internal
// field name ("References", used in storage keys and col_name
// attributes) stays untouched so iBOM's own column matching /
// drag-reorder keeps working unmodified. Registered on the documented
// BOM_BODY_CHANGE_EVENT hook (fires on initial render and every
// subsequent re-render: drag-reorder, mode change, etc.) rather than a
// one-time window.onload listener, so the column header and the
// vismenu dropdown's own list item both stay relabeled across
// re-renders, not just the first paint.
EventHandler.registerCallback(IBOM_EVENT_TYPES.BOM_BODY_CHANGE_EVENT, function spcoastRelabelReferences() {
  function relabelChildren(el) {
    if (!el) {
      return;
    }
    Array.from(el.childNodes).forEach(function (node) {
      if (node.nodeType === Node.TEXT_NODE && node.textContent.includes("References")) {
        node.textContent = node.textContent.replace("References", "Ref");
      }
    });
  }
  var referencesCheckbox = document.getElementById("referencesCheckbox");
  relabelChildren(referencesCheckbox && referencesCheckbox.parentElement);
  relabelChildren(document.querySelector('th[col_name="References"]'));
  var vismenuContent = document.getElementById("vismenu-content");
  if (vismenuContent) {
    Array.from(vismenuContent.querySelectorAll("label")).forEach(relabelChildren);
  }

  // Surface the same provenance descriptor inside iBOM's own UI, since
  // the standalone .ibom.html file is also a downloadable artifact in
  // its own right and may be opened outside the Hugo wrapper entirely
  // (see docs on kproj.common.install_info). A hover-only title
  // attribute on iBOM's existing credit line -- not new visible text,
  // not a change to iBOM's own HTML source.
  var creditLine = document.querySelector(".shameless-plug");
  if (creditLine) {
    creditLine.title = __PROVENANCE_JSON__;
  }
});
"""
"""``user.js`` template; ``__PROVENANCE__``/``__PROVENANCE_JSON__`` are filled
in by :func:`_build_user_js`."""


def _build_user_css(provenance: str) -> str:
    """Return ``user.css`` content with *provenance* in its header comment."""
    return _IBOM_USER_CSS_TEMPLATE.replace("__PROVENANCE__", provenance)


def _build_user_js(provenance: str) -> str:
    """Return ``user.js`` content with *provenance* in its header comment.

    Also embeds *provenance* as a properly quoted JS string literal
    (via :func:`json.dumps`) for the runtime ``title`` attribute set on
    iBOM's own credit line.
    """
    return _IBOM_USER_JS_TEMPLATE.replace("__PROVENANCE__", provenance).replace(
        "__PROVENANCE_JSON__", json.dumps(provenance)
    )


class IbomGenerator:
    """Interactive HTML BOM generator.

    Invokes the PCM-installed ``generate_interactive_bom.py`` script
    per ADR 0008.
    """

    def __init__(
        self,
        ibom_script: Path,
        python_exe: Path,
        *,
        extra_fields: Sequence[str] = _DEFAULT_EXTRA_FIELDS,
    ) -> None:
        """Construct an iBOM generator.

        Args:
            ibom_script: Path to ``generate_interactive_bom.py``, as
                resolved by
                :func:`kproj.common.kicad_install.find_ibom_script`
                during pre-flight.
            python_exe: KiCad's bundled Python interpreter (the one
                that can ``import pcbnew``), as resolved by
                :func:`kproj.common.kicad_install.find_kicad_python`
                during pre-flight.  Required (no default) so callers
                cannot silently fall back to ``sys.executable``, which
                lacks ``pcbnew`` (ADR 0008 amendment / kproj#10).
            extra_fields: Extra iBOM table columns to surface from the
                extra-data source (inventory-derived XML when provided,
                otherwise the PCB metadata path).
        """
        self._ibom_script = ibom_script
        self._python_exe = python_exe
        self._extra_fields = tuple(field.strip() for field in extra_fields if field.strip())

    def generate(
        self,
        pcb_path: Path,
        output_file: Path,
        name_format: str,
        *,
        journal: ChangeJournal | None = None,
        extra_data_rows: Sequence[DatasheetRow] | None = None,
    ) -> ExportResult:
        """Generate the interactive HTML BOM for *pcb_path*.

        Args:
            pcb_path: Path to the source ``.kicad_pcb``. Always passed
                as iBOM's positional board argument and used as the
                ``--extra-data-file`` fallback when no inventory XML
                projection is provided.
            output_file: Final HTML path. iBOM is allowed to write
                into a private staging directory and the produced
                HTML is then atomically moved here.
            name_format: The ``--name-format`` value to pass iBOM.
                iBOM writes ``<dest-dir>/<name_format>.html``; the
                ``.ibom`` suffix is part of *name_format* per
                ``docs/DESIGN.md`` § *Release asset set*.
            journal: Optional open :class:`ChangeJournal`.
            extra_data_rows: Optional inventory-enriched per-reference
                rows. When provided, kproj projects them to a temporary
                XML netlist and passes that via ``--extra-data-file`` so
                iBOM can surface jBOM-derived fields without forking.
                When omitted, the legacy ``--extra-data-file <pcb>``
                path is retained.

        Returns:
            A populated :class:`ExportResult` carrying the invoked
            argv, elapsed time, and the final *output_file* path.

        Raises:
            FileNotFoundError: When iBOM exits 0 but did not produce
                the expected ``<dest-dir>/<name_format>.html`` file.
            SubprocessFailedError: When iBOM exits non-zero.
            SubprocessTimeoutError: When iBOM exceeds the
                ``DEFAULT_KICAD_TIMEOUT``.
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)
        if journal is not None:
            # BLOCKER 3: pre-existing asset → will_modify so rollback
            # restores the prior bytes via git checkout.
            journal.register_output(output_file)

        with tempfile.TemporaryDirectory(prefix="kproj-ibom-") as staging:
            staging_dir = Path(staging)
            extra_data_file = pcb_path
            if extra_data_rows:
                extra_data_file = staging_dir / "kproj-ibom-extra-data.xml"
                _write_extra_data_xml(
                    extra_data_file,
                    extra_data_rows,
                    self._extra_fields,
                )
            has_front, has_back = detect_pcb_footprint_sides(pcb_path)
            layer_view = choose_ibom_layer_view(has_front=has_front, has_back=has_back)
            argv = [
                str(self._python_exe),
                str(self._ibom_script),
                "--no-browser",
                "--no-compression",
                "--dest-dir",
                str(staging_dir),
                "--name-format",
                name_format,
                "--extra-data-file",
                str(extra_data_file),
                "--dnp-field",
                "kicad_dnp",
                "--layer-view",
                layer_view,
            ]
            if self._extra_fields:
                argv.extend(["--extra-fields", ",".join(self._extra_fields)])
            argv.extend(
                [
                    "--include-tracks",
                    str(pcb_path),
                ]
            )
            started = time.monotonic()
            env = {**os.environ, _IBOM_HEADLESS_ENV_VAR: "1"}
            result = subprocess_run(
                argv,
                timeout=DEFAULT_KICAD_TIMEOUT,
                check=True,
                env=env,
            )
            elapsed = time.monotonic() - started

            produced = staging_dir / f"{name_format}.html"
            if not produced.is_file():
                raise FileNotFoundError(
                    f"iBOM exited 0 but produced no HTML at {produced}; "
                    f"check the iBOM script ({self._ibom_script}) is the one shipped by PCM."
                )
            os.replace(produced, output_file)

        return ExportResult(
            path=output_file,
            command=result.command,
            elapsed_seconds=elapsed,
        )


def detect_pcb_footprint_sides(pcb_path: Path) -> tuple[bool, bool]:
    """Return whether *pcb_path* has front- and/or back-side footprints.

    Scans footprint s-expressions for each footprint's own ``(layer "F.Cu")``
    / ``(layer "B.Cu")`` placement side. Nested pad or graphical layer tokens
    are ignored by only inspecting text from the footprint open through the
    first ``(layer "?.Cu")`` occurrence (KiCad writes the placement layer
    immediately under the footprint header).

    Footprints whose ``(attr ...)`` includes ``board_only`` or
    ``exclude_from_bom`` are skipped so mechanical-only back items do not
    force a dual-side default view.

    Args:
        pcb_path: Path to a ``.kicad_pcb`` file.

    Returns:
        ``(has_front, has_back)``. Both ``False`` when the file is missing,
        unreadable, or contains no countable footprints.
    """
    try:
        text = pcb_path.read_text(encoding="utf-8")
    except OSError:
        return False, False

    has_front = False
    has_back = False
    matches = list(_FOOTPRINT_BLOCK_RE.finditer(text))
    for index, match in enumerate(matches):
        block_start = match.start()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        # Placement layer is written immediately under the footprint header.
        # Search only the first copper ``(layer "?.Cu")`` near the open so
        # nested pad ``(layers "F.Cu" "B.Cu")`` tokens cannot flip the side.
        # ``(attr ...)`` sits after properties (~1.5–2 kB in); scan farther
        # for attr only.
        layer_window = text[block_start : min(block_start + 200, block_end)]
        layer_match = _FOOTPRINT_LAYER_RE.search(layer_window)
        if layer_match is None:
            continue
        attr_window = text[block_start : min(block_start + 3000, block_end)]
        attr_match = _FOOTPRINT_ATTR_RE.search(attr_window)
        if attr_match is not None:
            attr_tokens = set(attr_match.group(1).split())
            if attr_tokens & _IGNORED_FOOTPRINT_ATTR_TOKENS:
                continue
        side = layer_match.group(1)
        if side == "F":
            has_front = True
        elif side == "B":
            has_back = True
        if has_front and has_back:
            break
    return has_front, has_back


def choose_ibom_layer_view(*, has_front: bool, has_back: bool) -> str:
    """Choose iBOM ``--layer-view`` so the default table shows every side.

    iBOM filters the BOM table by canvas layer (``F`` / ``B`` / ``FB``).
    Prefer the single populated side when only one side has parts; use
    ``FB`` when both sides are populated so neither side is hidden on
    first open. Fall back to front when nothing is detected.

    Args:
        has_front: True when at least one countable front footprint exists.
        has_back: True when at least one countable back footprint exists.

    Returns:
        One of ``"F"``, ``"B"``, or ``"FB"``.
    """
    if has_front and has_back:
        return "FB"
    if has_back and not has_front:
        return "B"
    if has_front:
        return "F"
    return _IBOM_FALLBACK_LAYER_VIEW


def write_ibom_user_files(
    ibom_script: Path,
    *,
    install_info: InstallInfo,
    watermark: str = "",
) -> None:
    """Write kproj's ``user.css``/``user.js`` into iBOM's own ``web/`` dir.

    iBOM reads ``user.css`` / ``user.js`` (and ``userheader.html`` /
    ``userfooter.html``, unused here) from ``<install-root>/web/`` and
    embeds them into every generated page via its own
    ``///USERCSS///`` / ``///USERJS///`` placeholders
    (``InteractiveHtmlBom/core/ibom.py::generate_file``). This is
    iBOM's documented customization surface -- see
    https://github.com/openscopeproject/InteractiveHtmlBom/wiki/Customization.
    Writing here means SPCoast's UI defaults ride iBOM's own supported
    extension point instead of splicing text into iBOM's generated
    output after the fact.

    Called directly by :meth:`~kproj.application.publish_workflow.PublishWorkflow.run`
    (not from :meth:`IbomGenerator.generate`) so it can carry the
    per-publish :class:`~kproj.common.install_info.InstallInfo` +
    ``--watermark`` value without widening the injected
    ``ArtifactGeneratorCallable`` signature every provenance-surfacing
    site would otherwise need to thread through.

    Idempotent: overwrites both files unconditionally on every call, so
    a Plugin and Content Manager reinstall that wipes ``web/`` self-heals
    on the next publish.

    Args:
        ibom_script: Path to ``generate_interactive_bom.py``. iBOM's
            ``web/`` directory is always a sibling of this script.
        install_info: This process's detected kproj version + install
            type (see :func:`kproj.common.install_info.detect_install_info`),
            embedded in both files' header comments and, for ``user.js``,
            as a hover tooltip on iBOM's own credit line.
        watermark: Optional free-text tag (``--watermark``) appended to
            the embedded provenance string; empty by default.
    """
    provenance = format_provenance(install_info, watermark)
    web_dir = ibom_script.parent / "web"
    web_dir.mkdir(parents=True, exist_ok=True)
    (web_dir / "user.css").write_text(_build_user_css(provenance), encoding="utf-8")
    (web_dir / "user.js").write_text(_build_user_js(provenance), encoding="utf-8")


def _normalize_field_name(field: str) -> str:
    """Normalize a user-facing field name for lookup matching."""
    return field.strip().lower().replace("-", "_").replace(" ", "_")


def _is_dnp_marker(value: str) -> bool:
    """Return whether *value* should be interpreted as DNP."""
    return value.strip().lower() in _TRUE_DNP_MARKERS


def _datasheet_url_from_row(row: DatasheetRow) -> str:
    """Return the curated datasheet URL for *row*, or an empty string."""
    datasheet_name = row.datasheet_name.strip()
    if not datasheet_name:
        return ""
    return build_datasheet_link(datasheet_name).view_url


def _render_datasheet_anchor(url: str) -> str:
    """Render a compact HTML anchor for the Datasheet field."""
    safe_url = html.escape(url, quote=True)
    return f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer">Datasheet</a>'


def _render_details_field(row: DatasheetRow) -> str:
    """Render the compact multi-line Details field HTML for one component."""
    details: list[str] = []

    manufacturer = row.manufacturer.strip()
    if manufacturer:
        details.append(html.escape(manufacturer))

    mpn = (row.mpn or row.mfgpn).strip()
    if mpn:
        details.append(html.escape(mpn))

    datasheet_url = _datasheet_url_from_row(row)
    if datasheet_url:
        details.append(_render_datasheet_anchor(datasheet_url))

    return "<br>".join(details)


def _resolve_extra_field_value(field_name: str, row: DatasheetRow) -> str:
    """Resolve one requested iBOM field value from a :class:`DatasheetRow`."""
    normalized = _normalize_field_name(field_name)
    if normalized == "details":
        return _render_details_field(row)
    if normalized == "datasheet_name":
        return row.datasheet_name
    if normalized in {"manufacturer"}:
        return row.manufacturer
    if normalized in {"mpn", "mfgpn", "manufacturer_part_number", "part_number"}:
        return row.mpn or row.mfgpn
    if normalized in {
        "fabricator_part_number",
        "supplier_part_number",
        "fabricator_pn",
        "spn",
        "lcsc",
    }:
        return row.fabricator_part_number
    if normalized == "description":
        return row.description
    if normalized == "datasheet":
        datasheet_url = _datasheet_url_from_row(row)
        if not datasheet_url:
            return ""
        return _render_datasheet_anchor(datasheet_url)
    if normalized in {"dnp", "kicad_dnp"}:
        return "DNP" if _is_dnp_marker(row.dnp) else ""
    return ""


def _write_extra_data_xml(
    output_path: Path,
    rows: Sequence[DatasheetRow],
    extra_fields: Sequence[str],
) -> None:
    """Write iBOM-compatible XML extra-data with one ``comp`` per reference."""
    root = ElementTree.Element("export")
    components = ElementTree.SubElement(root, "components")

    for row in rows:
        reference = row.reference.strip()
        if not reference:
            continue

        comp = ElementTree.SubElement(components, "comp", {"ref": reference})
        datasheet_url = _resolve_extra_field_value("datasheet", row)
        if datasheet_url:
            ElementTree.SubElement(comp, "datasheet").text = datasheet_url
        if _is_dnp_marker(row.dnp):
            ElementTree.SubElement(comp, "property", {"name": "dnp"})

        for field_name in extra_fields:
            if _normalize_field_name(field_name) == "datasheet":
                # Prefer iBOM's dedicated <datasheet> tag over duplicate field.
                continue
            value = _resolve_extra_field_value(field_name, row)
            if not value:
                continue
            ElementTree.SubElement(comp, "field", {"name": field_name}).text = value

    ElementTree.ElementTree(root).write(output_path, encoding="utf-8", xml_declaration=True)
