"""Unit tests for :mod:`kproj.common.datasheet_library` (kproj#29).

Covers the deterministic URL constructor, the live ``jbom bom``
datasheet-name lookup, and the advisory-only (read-only,
never-blocking) publish guard. All fixtures are built under
``tmp_path``; the jbom invocation is faked via the ``jbom_command``
test seam so no real jBOM subprocess or network access is required.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

from kproj.common.datasheet_library import (
    DATASHEET_BOM_FIELDS,
    IBOM_BOM_FIELDS,
    _default_jbom_command,
    build_datasheet_link,
    check_datasheet_links,
    distinct_datasheet_names,
    read_datasheet_names,
    read_datasheet_rows,
    read_ibom_rows,
)
from kproj.model.datasheet_link import DatasheetLink
from kproj.model.datasheet_row import DatasheetRow

# ----------------------------------------------------------------------
# build_datasheet_link
# ----------------------------------------------------------------------


def test_build_datasheet_link_constructs_view_and_download_urls() -> None:
    """The view + download URLs follow the jBOM#350 URL contract."""
    link = build_datasheet_link("yageo_rc0805_resistor")
    assert link == DatasheetLink(
        name="yageo_rc0805_resistor",
        view_url=(
            "https://github.com/plocher/SPCoast-inventory/blob/main/"
            "datasheets/yageo_rc0805_resistor.pdf"
        ),
        download_url=(
            "https://raw.githubusercontent.com/plocher/SPCoast-inventory/main/"
            "datasheets/yageo_rc0805_resistor.pdf"
        ),
    )


def test_build_datasheet_link_strips_redundant_pdf_suffix() -> None:
    """A BOM value already carrying ``.pdf`` doesn't double up."""
    link = build_datasheet_link("Cap-Foo.pdf")
    assert link.name == "Cap-Foo"
    assert link.view_url.endswith("/datasheets/Cap-Foo.pdf")
    assert link.download_url.endswith("/datasheets/Cap-Foo.pdf")


def test_build_datasheet_link_url_encodes_reserved_characters() -> None:
    """A name containing a space (or other reserved char) is percent-encoded.

    Nothing upstream enforces the hyphenated-ASCII convention the real
    library currently follows; a future curated name with a space must
    still produce a well-formed URL rather than a broken one.
    """
    link = build_datasheet_link("Resistor Series A")
    assert link.name == "Resistor Series A", "the raw name field is left unencoded"
    assert " " not in link.view_url
    assert " " not in link.download_url
    assert "Resistor%20Series%20A" in link.view_url
    assert "Resistor%20Series%20A" in link.download_url


# ----------------------------------------------------------------------
# read_datasheet_names (live `jbom bom` invocation, faked via jbom_command)
# ----------------------------------------------------------------------


def _fake_jbom_script(tmp_path: Path, *, stdout: str, exit_code: int = 0) -> list[str]:
    """Write a tiny script standing in for ``python -m jbom bom ...`` and
    return the argv (``jbom_command``) that runs it.

    Echoes the pre-baked *stdout* and exits with *exit_code*, regardless
    of its own argv - the test seam only needs to control jbom's output,
    not verify jbom's own argument parsing (that's jBOM's test suite's job).
    """
    script = tmp_path / "fake_jbom.py"
    script.write_text(
        f"import sys\nsys.stdout.write({stdout!r})\nsys.exit({exit_code})\n",
        encoding="utf-8",
    )
    return [sys.executable, str(script)]


def test_read_datasheet_names_returns_distinct_curated_names(tmp_path: Path) -> None:
    """Only rows with a populated Datasheet Name contribute a name."""
    stdout = (
        "Reference,Datasheet,Datasheet Name\n"
        "R1,https://example.com/rc0805.pdf,yageo_rc0805_resistor\n"
        "R2,https://example.com/rc0805.pdf,yageo_rc0805_resistor\n"
        "R3,1K,\n"
    )
    command = _fake_jbom_script(tmp_path, stdout=stdout)
    names, findings = read_datasheet_names(tmp_path, jbom_command=command)
    assert names == ("yageo_rc0805_resistor",)
    assert findings == ()


def test_read_datasheet_rows_returns_structured_per_reference_rows(tmp_path: Path) -> None:
    """The live lookup keeps reference, datasheet URL, and curated name per row."""
    stdout = (
        "Reference,Datasheet,Datasheet Name\n"
        "R1,https://example.com/r1.pdf,yageo_rc0805_resistor\n"
        "R2,https://example.com/r2.pdf,\n"
    )
    command = _fake_jbom_script(tmp_path, stdout=stdout)
    rows, findings = read_datasheet_rows(
        tmp_path,
        inventory=tmp_path / "inventory.csv",
        jbom_command=command,
    )
    assert rows == (
        DatasheetRow(
            reference="R1",
            datasheet="https://example.com/r1.pdf",
            datasheet_name="yageo_rc0805_resistor",
        ),
        DatasheetRow(reference="R2", datasheet="https://example.com/r2.pdf", datasheet_name=""),
    )
    assert distinct_datasheet_names(rows) == ("yageo_rc0805_resistor",)
    assert findings == ()


def test_read_ibom_rows_expands_grouped_references_and_maps_inventory_fields(
    tmp_path: Path,
) -> None:
    """Grouped BOM refs are exploded to per-reference rows for iBOM matching."""
    stdout = (
        "Reference,Datasheet,Datasheet Name,Manufacturer,MFGPN,Fabricator Part Number,Description,DNP\n"
        "R8,https://example.com/r.pdf,res_doc,Yageo,RC0603-10K,LCSC123,10K resistor,\n"
        "R9,https://example.com/r.pdf,res_doc,Yageo,RC0603-10K,LCSC123,10K resistor,\n"
        '"Q8, Q9",https://example.com/mosfet.pdf,mos_doc,ON Semi,BSS138,LCSC999,MOSFET,DNP\n'
    )
    command = _fake_jbom_script(tmp_path, stdout=stdout)
    rows, findings = read_ibom_rows(
        tmp_path,
        inventory=tmp_path / "inventory.csv",
        jbom_command=command,
    )
    assert findings == ()
    assert [row.reference for row in rows] == ["R8", "R9", "Q8", "Q9"]
    assert rows[0].manufacturer == "Yageo"
    assert rows[0].mfgpn == "RC0603-10K"
    assert rows[0].mpn == "RC0603-10K"
    assert rows[0].fabricator_part_number == "LCSC123"
    assert rows[0].description == "10K resistor"
    assert rows[2].dnp == "DNP"
    assert rows[3].datasheet_name == "mos_doc"


def test_read_ibom_rows_supports_jlc_header_aliases_and_grouped_designators(
    tmp_path: Path,
) -> None:
    """JLC header aliases map to canonical row fields for iBOM enrichment."""
    stdout = (
        "Designator,Datasheet,Datasheet Name,Manufacturer,MFGPN,LCSC Part #,Comment,DNP\n"
        '"Q8, Q9",https://example.com/mosfet.pdf,mos_doc,ON Semi,BSS138,LCSC999,MOSFET,DNP\n'
    )
    command = _fake_jbom_script(tmp_path, stdout=stdout)
    rows, findings = read_ibom_rows(
        tmp_path,
        inventory=tmp_path / "inventory.csv",
        jbom_command=command,
    )
    assert findings == ()
    assert [row.reference for row in rows] == ["Q8", "Q9"]
    assert rows[0].description == "MOSFET"
    assert rows[0].fabricator_part_number == "LCSC999"
    assert rows[0].datasheet_name == "mos_doc"


def test_read_datasheet_names_sorted_case_insensitively(tmp_path: Path) -> None:
    """Distinct names come back case-insensitively sorted."""
    stdout = "Reference,Datasheet Name\nR1,beta_doc\nR2,Alpha_doc\n"
    command = _fake_jbom_script(tmp_path, stdout=stdout)
    names, findings = read_datasheet_names(tmp_path, jbom_command=command)
    assert names == ("Alpha_doc", "beta_doc")
    assert findings == ()


def test_read_datasheet_names_nonzero_exit_emits_advisory_finding(tmp_path: Path) -> None:
    """A failing jbom invocation (e.g. too old, or crashes): advisory, not fatal."""
    command = _fake_jbom_script(tmp_path, stdout="", exit_code=1)
    names, findings = read_datasheet_names(tmp_path, project="Demo", jbom_command=command)
    assert names == ()
    assert len(findings) == 1
    assert findings[0].field == "datasheet_field_missing"
    assert findings[0].severity.value == "warning"
    assert findings[0].project == "Demo"


def test_read_datasheet_names_missing_jbom_emits_advisory_finding(tmp_path: Path) -> None:
    """jbom not runnable at all (e.g. missing): advisory, not fatal."""
    names, findings = read_datasheet_names(
        tmp_path, project="Demo", jbom_command=[str(tmp_path / "no-such-executable")]
    )
    assert names == ()
    assert len(findings) == 1
    assert findings[0].field == "datasheet_field_missing"


def test_read_datasheet_names_missing_column_emits_advisory_finding(tmp_path: Path) -> None:
    """jbom output present but without the Datasheet Name column (old jBOM)."""
    command = _fake_jbom_script(tmp_path, stdout="Reference,Value\nR1,10K\n")
    names, findings = read_datasheet_names(tmp_path, jbom_command=command)
    assert names == ()
    assert len(findings) == 1
    assert findings[0].field == "datasheet_field_missing"


def test_read_datasheet_names_empty_when_no_curated_rows(tmp_path: Path) -> None:
    """Column present but every row uncurated: no names, no finding."""
    command = _fake_jbom_script(tmp_path, stdout="Reference,Datasheet Name\nR1,\nR2,\n")
    names, findings = read_datasheet_names(tmp_path, jbom_command=command)
    assert names == ()
    assert findings == ()


def test_read_datasheet_names_dedups_case_insensitively(tmp_path: Path) -> None:
    """Two rows differing only in casing collapse to one name.

    The library's stated uniqueness invariant (SPCoast-inventory's
    glossary: "Names are unique case-insensitively") means a curation
    slip upstream that produces two different casings of the same
    document must not survive as two distinct links.
    """
    stdout = "Reference,Datasheet Name\nR1,Yageo_RC0805\nR2,yageo_rc0805\n"
    command = _fake_jbom_script(tmp_path, stdout=stdout)
    names, findings = read_datasheet_names(tmp_path, jbom_command=command)
    assert names == ("Yageo_RC0805",), "first-seen casing wins; only one entry survives"
    assert findings == ()


def test_read_datasheet_names_omits_inventory_flag_when_unconfigured(tmp_path: Path) -> None:
    """With no inventory configured, the real jbom subprocess is skipped entirely."""
    names, findings = read_datasheet_names(tmp_path, inventory=None)
    assert names == ()
    assert findings == ()


def test_default_jbom_command_returns_none_when_inventory_unconfigured(tmp_path: Path) -> None:
    """No inventory means no jbom command is built or run."""
    assert _default_jbom_command(tmp_path, None) is None


def test_read_datasheet_names_default_command_includes_inventory_when_configured(
    tmp_path: Path,
) -> None:
    """The default argv uses PATH jbom and the extensible multi-field field list."""

    inventory = tmp_path / "inventory.csv"
    command = _default_jbom_command(tmp_path, inventory)
    assert command is not None
    # -q is jBOM's *global* quiet flag (kproj#41): it must precede the
    # bom subcommand, not follow it.
    assert command[-11:] == [
        "-q",
        "bom",
        str(tmp_path),
        "--inventory",
        str(inventory),
        "--fabricator",
        "jlc",
        "-f",
        DATASHEET_BOM_FIELDS,
        "-o",
        "-",
    ]
    assert command[0].endswith("jbom") or command[:3] == [sys.executable, "-m", "jbom"]


def test_default_jbom_command_supports_ibom_field_token_set(tmp_path: Path) -> None:
    """The command builder threads a custom field-token list unchanged."""
    inventory = tmp_path / "inventory.csv"
    command = _default_jbom_command(tmp_path, inventory, fields=IBOM_BOM_FIELDS)
    assert command is not None
    assert "--fabricator" in command
    assert command[command.index("--fabricator") + 1] == "jlc"
    assert command[-3:] == [IBOM_BOM_FIELDS, "-o", "-"]


def test_default_jbom_command_supports_custom_fabricator(tmp_path: Path) -> None:
    """A non-default fabricator is threaded into the generated argv."""
    inventory = tmp_path / "inventory.csv"
    command = _default_jbom_command(tmp_path, inventory, fabricator="pcbway")
    assert command is not None
    assert "--fabricator" in command
    assert command[command.index("--fabricator") + 1] == "pcbway"


def test_real_jbom_supports_datasheet_lookup_field_list(tmp_path: Path) -> None:
    """Real jBOM accepts the production field token list and emits every header."""
    from tests._kicad_fixtures import make_minimal_project

    project_dir = make_minimal_project(tmp_path / "demo", "demo")
    inventory = tmp_path / "inventory.csv"
    inventory.write_text(
        "IPN,Category,Value,Package,Manufacturer,MFGPN,Datasheet,Datasheet Name\n",
        encoding="utf-8",
    )
    command = _default_jbom_command(project_dir, inventory)
    assert command is not None
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    header = next(csv.reader([completed.stdout.splitlines()[0]]))
    assert any(column in {"Reference", "Designator"} for column in header)
    assert "Datasheet" in header
    assert "Datasheet Name" in header


# ----------------------------------------------------------------------
# check_datasheet_links
# ----------------------------------------------------------------------


def _init_pushed_repo(repo_dir: Path, *, remote_dir: Path) -> None:
    """Init *repo_dir* as a git repo whose HEAD matches an upstream."""
    remote_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "--bare", str(remote_dir)], check=True)
    repo_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repo_dir)], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.email", "t@t.com"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "config", "user.name", "T"], check=True)
    (repo_dir / "README.md").write_text("lib\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_dir), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "commit", "-q", "-m", "init"], check=True)
    subprocess.run(
        ["git", "-C", str(repo_dir), "remote", "add", "origin", str(remote_dir)], check=True
    )
    subprocess.run(["git", "-C", str(repo_dir), "push", "-q", "-u", "origin", "HEAD"], check=True)


def test_check_datasheet_links_no_names_is_a_noop(tmp_path: Path) -> None:
    """No names to check means no findings, regardless of the library repo."""
    assert check_datasheet_links((), tmp_path / "missing") == ()


def test_check_datasheet_links_missing_clone_emits_one_finding(tmp_path: Path) -> None:
    """A non-existent local library clone emits a single summary warning."""
    findings = check_datasheet_links(("a", "b"), tmp_path / "no-such-clone", project="Demo")
    assert len(findings) == 1
    assert findings[0].field == "datasheet_library_missing"
    assert findings[0].project == "Demo"


def test_check_datasheet_links_unresolvable_name_warns(tmp_path: Path) -> None:
    """A pushed clone missing the named PDF warns 'datasheet_unresolvable'."""
    library_repo = tmp_path / "lib"
    _init_pushed_repo(library_repo, remote_dir=tmp_path / "remote.git")

    findings = check_datasheet_links(("missing_doc",), library_repo, project="Demo")
    assert [f.field for f in findings] == ["datasheet_unresolvable"]
    assert findings[0].value == "missing_doc"


def test_check_datasheet_links_resolvable_and_pushed_is_clean(tmp_path: Path) -> None:
    """A pushed clone with the named PDF present emits no findings."""
    library_repo = tmp_path / "lib"
    _init_pushed_repo(library_repo, remote_dir=tmp_path / "remote.git")
    (library_repo / "datasheets").mkdir()
    (library_repo / "datasheets" / "present_doc.pdf").write_bytes(b"%PDF-1.4")

    assert check_datasheet_links(("present_doc",), library_repo) == ()


def test_check_datasheet_links_tolerates_is_file_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An OSError from the per-name existence check degrades to a warning.

    ``Path.is_file()`` can raise for reasons unrelated to "not found"
    (e.g. ``ELOOP`` on a symlink cycle, permission-denied walking a
    parent directory). Before the fix, this propagated uncaught through
    ``check_datasheet_links`` - proven here by monkeypatching
    ``Path.is_file`` to always raise and asserting the guard still
    returns a warning `Finding` instead of raising.
    """
    library_repo = tmp_path / "lib"
    _init_pushed_repo(library_repo, remote_dir=tmp_path / "remote.git")
    (library_repo / "datasheets").mkdir()

    def _raising_is_file(self: Path) -> bool:
        raise OSError("simulated ELOOP on a symlink cycle")

    monkeypatch.setattr(Path, "is_file", _raising_is_file)  # type: ignore[attr-defined]

    findings = check_datasheet_links(("any_doc",), library_repo, project="Demo")
    assert [f.field for f in findings] == ["datasheet_unresolvable"]


def test_check_datasheet_links_not_pushed_warns_once(tmp_path: Path) -> None:
    """An unpushed local commit warns 'datasheet_library_unpushed' (checked once)."""
    library_repo = tmp_path / "lib"
    library_repo.mkdir()
    subprocess.run(["git", "init", "-q", str(library_repo)], check=True)
    subprocess.run(["git", "-C", str(library_repo), "config", "user.email", "t@t.com"], check=True)
    subprocess.run(["git", "-C", str(library_repo), "config", "user.name", "T"], check=True)
    (library_repo / "README.md").write_text("lib\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(library_repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(library_repo), "commit", "-q", "-m", "init"], check=True)
    # No remote configured at all -> not confirmed pushed.

    findings = check_datasheet_links(("a", "b"), library_repo)
    unpushed = [f for f in findings if f.field == "datasheet_library_unpushed"]
    assert len(unpushed) == 1
