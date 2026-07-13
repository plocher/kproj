"""Unit tests for :mod:`kproj.common.datasheet_library` (kproj#29).

Covers the deterministic URL constructor, the live ``jbom bom``
datasheet-name lookup, and the advisory-only (read-only,
never-blocking) publish guard. All fixtures are built under
``tmp_path``; the jbom invocation is faked via the ``jbom_command``
test seam so no real jBOM subprocess or network access is required.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from kproj.common.datasheet_library import (
    build_datasheet_link,
    check_datasheet_links,
    read_datasheet_names,
)
from kproj.model.datasheet_link import DatasheetLink

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
        "Reference,Value,Datasheet Name\n"
        "R1,10K,yageo_rc0805_resistor\n"
        "R2,22K,yageo_rc0805_resistor\n"
        "R3,1K,\n"
    )
    command = _fake_jbom_script(tmp_path, stdout=stdout)
    names, findings = read_datasheet_names(tmp_path, jbom_command=command)
    assert names == ("yageo_rc0805_resistor",)
    assert findings == ()


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


def test_read_datasheet_names_omits_inventory_flag_when_unconfigured(tmp_path: Path) -> None:
    """With no jbom_command override, the default argv omits --inventory when unset."""
    from kproj.common.datasheet_library import _default_jbom_command

    command = _default_jbom_command(tmp_path, None)
    assert "--inventory" not in command


def test_read_datasheet_names_default_command_includes_inventory_when_configured(
    tmp_path: Path,
) -> None:
    """The default argv forwards --inventory when a path is configured."""
    from kproj.common.datasheet_library import _default_jbom_command

    inventory = tmp_path / "inventory.csv"
    command = _default_jbom_command(tmp_path, inventory)
    assert "--inventory" in command
    assert str(inventory) in command


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
