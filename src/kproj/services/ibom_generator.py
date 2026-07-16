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
        --layer-view F
        --extra-fields <configured-extra-fields>
        --include-tracks
        <pcb>

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
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Sequence
from pathlib import Path

from ..common.datasheet_library import build_datasheet_link
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
_IBOM_DEFAULT_LAYER_VIEW = "F"
"""Preferred initial PCB layer view for generated iBOM pages."""

_IBOM_DEFAULT_HIDDEN_COLUMNS = (
    'if (hcols === null) {\n    hcols = ["checkboxes", "Footprint"];\n  }'
)
"""JS snippet used to hide checkboxes + footprint columns by default."""

_IBOM_RENAME_REFERENCES_LABEL = "References"
_IBOM_REFERENCE_LABEL = "Ref"


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
                _IBOM_DEFAULT_LAYER_VIEW,
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
            _customize_ibom_html_defaults(produced)
            os.replace(produced, output_file)

        return ExportResult(
            path=output_file,
            command=result.command,
            elapsed_seconds=elapsed,
        )


def _customize_ibom_html_defaults(output_path: Path) -> None:
    """Apply SPCoast iBOM UI defaults in the generated HTML payload."""
    text = output_path.read_text(encoding="utf-8")

    updated = text.replace(
        f'"{_IBOM_RENAME_REFERENCES_LABEL}"',
        f'"{_IBOM_REFERENCE_LABEL}"',
    )
    updated = re.sub(
        r'(id="referencesCheckbox"[^>]*>\s*)References(\s*</label>)',
        rf"\1{_IBOM_REFERENCE_LABEL}\2",
        updated,
        count=1,
    )
    updated = updated.replace(
        "if (hcols === null) {\n    hcols = [];\n  }",
        _IBOM_DEFAULT_HIDDEN_COLUMNS,
        1,
    )

    if updated == text:
        return
    output_path.write_text(updated, encoding="utf-8")


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
