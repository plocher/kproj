"""Unit tests for :mod:`kproj.common.install_info`."""

from __future__ import annotations

import json
from importlib import metadata
from typing import Any

import pytest

from kproj.common.install_info import (
    InstallInfo,
    detect_install_info,
    format_provenance,
)


class _FakeDistribution:
    """Minimal stand-in for :class:`importlib.metadata.Distribution`."""

    def __init__(self, direct_url_text: str | None) -> None:
        self._direct_url_text = direct_url_text

    def read_text(self, filename: str) -> str | None:
        assert filename == "direct_url.json"
        return self._direct_url_text


def test_detect_install_info_reports_editable_for_pep660_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An editable install's ``direct_url.json`` sets ``install_type=\"editable\"``."""
    direct_url = json.dumps(
        {
            "url": "file:///Users/dev/Dropbox/KiCad/kproj",
            "dir_info": {"editable": True},
        }
    )
    monkeypatch.setattr(metadata, "distribution", lambda name: _FakeDistribution(direct_url))

    info = detect_install_info()

    assert info.install_type == "editable"
    assert info.location == "/Users/dev/Dropbox/KiCad/kproj"


def test_detect_install_info_reports_release_when_not_editable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normal (non-editable) install falls back to ``install_type=\"release\"``."""
    direct_url = json.dumps({"url": "https://files.pythonhosted.org/whl/kproj-0.10.5.whl"})
    monkeypatch.setattr(metadata, "distribution", lambda name: _FakeDistribution(direct_url))

    info = detect_install_info()

    assert info.install_type == "release"
    assert info.location == ""


def test_detect_install_info_falls_back_when_distribution_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing distribution (e.g. a frozen/zipapp build) falls back to release."""

    def _raise(name: str) -> Any:
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "distribution", _raise)

    info = detect_install_info()

    assert info.install_type == "release"
    assert info.location == ""


def test_detect_install_info_falls_back_when_direct_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``direct_url.json`` at all (e.g. most Homebrew/pip installs) is release."""
    monkeypatch.setattr(metadata, "distribution", lambda name: _FakeDistribution(None))

    info = detect_install_info()

    assert info.install_type == "release"


def test_detect_install_info_falls_back_when_direct_url_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed JSON never raises; falls back to release."""
    monkeypatch.setattr(metadata, "distribution", lambda name: _FakeDistribution("not json"))

    info = detect_install_info()

    assert info.install_type == "release"


def test_detect_install_info_uses_current_kproj_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reported version always matches ``kproj.__version__``."""
    monkeypatch.setattr(metadata, "distribution", lambda name: _FakeDistribution(None))
    import kproj

    info = detect_install_info()

    assert info.version == kproj.__version__


def test_format_provenance_release_without_watermark() -> None:
    """Release installs format without a trailing bracketed tag."""
    info = InstallInfo(install_type="release", version="0.10.5")

    assert format_provenance(info) == "kproj 0.10.5 (release)"


def test_format_provenance_editable_with_watermark() -> None:
    """A non-empty watermark is appended in brackets."""
    info = InstallInfo(install_type="editable", version="0.10.5")

    assert format_provenance(info, watermark="my-test-tag") == (
        "kproj 0.10.5 (editable) [my-test-tag]"
    )


def test_format_provenance_empty_watermark_is_omitted() -> None:
    """An empty-string watermark does not add an empty bracket pair."""
    info = InstallInfo(install_type="release", version="0.10.5")

    assert format_provenance(info, watermark="") == "kproj 0.10.5 (release)"
