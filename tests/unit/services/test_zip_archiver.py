"""Unit tests for :mod:`kproj.services.zip_archiver`."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from kproj.model.export_result import ExportResult
from kproj.services.zip_archiver import ZipArchiver


@pytest.fixture
def archiver() -> ZipArchiver:
    """Return a fresh :class:`ZipArchiver` instance."""
    return ZipArchiver()


def _make_source_tree(root: Path) -> list[Path]:
    """Create a small mixed file/directory layout under *root*."""
    (root / "a.txt").write_text("alpha")
    (root / "sub").mkdir()
    (root / "sub" / "b.txt").write_text("bravo")
    (root / "sub" / "deep").mkdir()
    (root / "sub" / "deep" / "c.txt").write_text("charlie")
    return [root / "a.txt", root / "sub"]


def test_archive_returns_export_result(archiver: ZipArchiver, tmp_path: Path) -> None:
    """``ZipArchiver.archive`` returns an :class:`ExportResult`."""
    src = tmp_path / "src"
    src.mkdir()
    sources = _make_source_tree(src)
    output = tmp_path / "out.zip"
    result = archiver.archive(sources, output, root=src)
    assert isinstance(result, ExportResult)
    assert result.path == output
    assert result.command is None  # in-process; no subprocess
    assert result.skipped is False


def test_archive_writes_zip_with_expected_entries(archiver: ZipArchiver, tmp_path: Path) -> None:
    """The zip contains every source file with paths relative to *root*."""
    src = tmp_path / "src"
    src.mkdir()
    _make_source_tree(src)
    output = tmp_path / "out.zip"
    archiver.archive([src / "a.txt", src / "sub"], output, root=src)
    with zipfile.ZipFile(output) as zf:
        assert sorted(zf.namelist()) == sorted(["a.txt", "sub/b.txt", "sub/deep/c.txt"])


def test_archive_preserves_file_contents(archiver: ZipArchiver, tmp_path: Path) -> None:
    """File contents inside the zip match the originals byte-for-byte."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "alpha.txt").write_text("hello")
    output = tmp_path / "out.zip"
    archiver.archive([src / "alpha.txt"], output, root=src)
    with zipfile.ZipFile(output) as zf:
        assert zf.read("alpha.txt").decode() == "hello"


def test_archive_creates_parent_directories(archiver: ZipArchiver, tmp_path: Path) -> None:
    """Missing parent directories of the output path are created."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "f.txt").write_text("x")
    output = tmp_path / "nested" / "out.zip"
    archiver.archive([src / "f.txt"], output, root=src)
    assert output.exists()


def test_archive_rejects_sources_outside_root(archiver: ZipArchiver, tmp_path: Path) -> None:
    """A source outside *root* is rejected at intake."""
    src = tmp_path / "src"
    src.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("nope")
    with pytest.raises(ValueError, match="outside root"):
        archiver.archive([outside], tmp_path / "out.zip", root=src)


def test_archive_handles_empty_source_list(archiver: ZipArchiver, tmp_path: Path) -> None:
    """An empty source list produces an empty zip (no skipped, no error)."""
    src = tmp_path / "src"
    src.mkdir()
    output = tmp_path / "empty.zip"
    result = archiver.archive([], output, root=src)
    assert output.exists()
    assert result.skipped is False
    with zipfile.ZipFile(output) as zf:
        assert zf.namelist() == []
