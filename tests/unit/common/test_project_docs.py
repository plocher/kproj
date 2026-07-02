"""Unit tests for :mod:`kproj.common.project_docs`.

Covers recursive datasheet discovery (with pruning of generated / VCS /
backup subtrees) and DESCRIPTION prose resolution. All fixtures are built
under ``tmp_path`` so no real KiCad project is required.
"""

from __future__ import annotations

from pathlib import Path

from kproj.common.project_docs import (
    discover_datasheet_files,
    discover_datasheets,
    read_description,
)


def _touch(path: Path) -> None:
    """Create ``path`` (and any parents) as an empty file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")


# ----------------------------------------------------------------------
# discover_datasheets
# ----------------------------------------------------------------------


def test_discover_datasheets_empty_when_no_pdfs(tmp_path: Path) -> None:
    """A project with no PDFs yields an empty tuple."""
    (tmp_path / "README.md").write_text("hi")
    assert discover_datasheets(tmp_path) == ()


def test_discover_datasheets_returns_empty_for_missing_dir(tmp_path: Path) -> None:
    """A non-existent directory yields an empty tuple, not an error."""
    assert discover_datasheets(tmp_path / "no-such") == ()


def test_discover_datasheets_finds_root_pdfs_sorted_case_insensitively(
    tmp_path: Path,
) -> None:
    """Root-level PDFs are returned, sorted case-insensitively."""
    _touch(tmp_path / "beta.pdf")
    _touch(tmp_path / "Alpha.pdf")
    assert discover_datasheets(tmp_path) == ("Alpha.pdf", "beta.pdf")


def test_discover_datasheets_recurses_into_subdirs(tmp_path: Path) -> None:
    """Datasheets are found wherever they are stored (docs/, ds-downloads/)."""
    _touch(tmp_path / "Root.pdf")
    _touch(tmp_path / "docs" / "InDocs.pdf")
    _touch(tmp_path / "ds-downloads" / "Nested" / "Deep.pdf")
    assert discover_datasheets(tmp_path) == ("Deep.pdf", "InDocs.pdf", "Root.pdf")


def test_discover_datasheets_finds_uppercase_extension(tmp_path: Path) -> None:
    """The ``.pdf`` match is case-insensitive on the extension."""
    _touch(tmp_path / "Loud.PDF")
    assert discover_datasheets(tmp_path) == ("Loud.PDF",)


def test_discover_datasheets_prunes_hidden_dirs(tmp_path: Path) -> None:
    """Hidden trees (.git, .history) are not scanned."""
    _touch(tmp_path / "Keep.pdf")
    _touch(tmp_path / ".git" / "Ignored.pdf")
    _touch(tmp_path / ".history" / "sub" / "Ignored2.pdf")
    assert discover_datasheets(tmp_path) == ("Keep.pdf",)


def test_discover_datasheets_prunes_backup_dirs(tmp_path: Path) -> None:
    """KiCad ``*-backups`` directories are excluded."""
    _touch(tmp_path / "Keep.pdf")
    _touch(tmp_path / "myproj-backups" / "Old.pdf")
    assert discover_datasheets(tmp_path) == ("Keep.pdf",)


def test_discover_datasheets_prunes_production_dir(tmp_path: Path) -> None:
    """The fab ``production/`` tree (generated output) is excluded."""
    _touch(tmp_path / "Keep.pdf")
    _touch(tmp_path / "production" / "drill-map.pdf")
    _touch(tmp_path / "production" / "backups" / "old-drill.pdf")
    assert discover_datasheets(tmp_path) == ("Keep.pdf",)


def test_discover_datasheets_dedupes_by_basename(tmp_path: Path) -> None:
    """The same basename in two locations collapses to a single entry."""
    _touch(tmp_path / "docs" / "Same.pdf")
    _touch(tmp_path / "ds-downloads" / "Same.pdf")
    assert discover_datasheets(tmp_path) == ("Same.pdf",)


# ----------------------------------------------------------------------
# discover_datasheet_files
# ----------------------------------------------------------------------


def test_discover_datasheet_files_returns_source_paths(tmp_path: Path) -> None:
    """Returns the actual source paths, sorted case-insensitively by basename."""
    _touch(tmp_path / "beta.pdf")
    _touch(tmp_path / "docs" / "Alpha.pdf")
    assert discover_datasheet_files(tmp_path) == (
        tmp_path / "docs" / "Alpha.pdf",
        tmp_path / "beta.pdf",
    )


def test_discover_datasheet_files_dedupes_by_basename(tmp_path: Path) -> None:
    """One source path per unique basename (matches discover_datasheets)."""
    _touch(tmp_path / "docs" / "Same.pdf")
    _touch(tmp_path / "ds-downloads" / "Same.pdf")
    files = discover_datasheet_files(tmp_path)
    assert len(files) == 1
    assert tuple(p.name for p in files) == ("Same.pdf",)


# ----------------------------------------------------------------------
# read_description
# ----------------------------------------------------------------------


def test_read_description_empty_when_absent(tmp_path: Path) -> None:
    """No DESCRIPTION file yields an empty string."""
    assert read_description(tmp_path) == ""


def test_read_description_reads_markdown_content(tmp_path: Path) -> None:
    """DESCRIPTION.md content is returned verbatim."""
    (tmp_path / "DESCRIPTION.md").write_text("Project prose.\n", encoding="utf-8")
    assert read_description(tmp_path) == "Project prose.\n"


def test_read_description_prefers_md_over_txt_and_bare(tmp_path: Path) -> None:
    """When several candidates exist, ``.md`` wins (first in preference order)."""
    (tmp_path / "DESCRIPTION.md").write_text("md", encoding="utf-8")
    (tmp_path / "DESCRIPTION.txt").write_text("txt", encoding="utf-8")
    (tmp_path / "DESCRIPTION").write_text("bare", encoding="utf-8")
    assert read_description(tmp_path) == "md"
