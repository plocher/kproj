"""Unit tests for :mod:`kproj.services.thumbnail_generator`.

v1 recipe (grey-scale): the thumbnail is a deterministic copy of the
top render so the front-matter ``image_path`` resolves on the built
site without a runtime image library. These tests pin that contract +
the journal/rollback wiring + the missing-source failure mode.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kproj.model.export_result import ExportResult
from kproj.services.change_journal import ChangeJournal
from kproj.services.thumbnail_generator import ThumbnailGenerator


def _write_top(tmp_path: Path) -> Path:
    """Create a stand-in top render PNG and return its path."""
    top = tmp_path / "Demo-1.0B.top.png"
    top.write_bytes(b"\x89PNG\r\n\x1a\n-fake-top-render-bytes")
    return top


def test_generate_copies_top_render_to_thumbnail(tmp_path: Path) -> None:
    """The produced thumbnail is a byte-for-byte copy of the top render."""
    top = _write_top(tmp_path)
    output = tmp_path / "out" / "Demo-1.0B.thumbnail.png"

    result = ThumbnailGenerator().generate(top, output)

    assert isinstance(result, ExportResult)
    assert result.path == output
    assert result.command is None  # pure-Python producer
    assert output.exists()
    assert output.read_bytes() == top.read_bytes()


def test_generate_registers_with_change_journal(tmp_path: Path) -> None:
    """The final thumbnail path is registered for rollback via the journal."""
    site_repo = tmp_path / "site"
    site_repo.mkdir()
    top = _write_top(tmp_path)
    output = site_repo / "versions" / "Demo" / "1.0B" / "Demo-1.0B.thumbnail.png"

    with ChangeJournal(site_repo) as journal:
        ThumbnailGenerator().generate(top, output, journal=journal)
        assert output in set(journal.all_paths())


def test_generate_raises_when_source_missing(tmp_path: Path) -> None:
    """A missing top render raises FileNotFoundError (workflow -> failed)."""
    output = tmp_path / "Demo-1.0B.thumbnail.png"
    with pytest.raises(FileNotFoundError):
        ThumbnailGenerator().generate(tmp_path / "no-such-top.png", output)
    assert not output.exists()


def test_generate_leaves_no_temp_files(tmp_path: Path) -> None:
    """The atomic sibling tempfile is cleaned up (only the final file remains)."""
    top = _write_top(tmp_path)
    output = tmp_path / "Demo-1.0B.thumbnail.png"
    ThumbnailGenerator().generate(top, output)
    siblings = sorted(p.name for p in output.parent.iterdir())
    assert siblings == ["Demo-1.0B.thumbnail.png", "Demo-1.0B.top.png"]
