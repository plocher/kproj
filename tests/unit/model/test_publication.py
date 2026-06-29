"""Unit tests for :mod:`kproj.model.publication`."""

from __future__ import annotations

import dataclasses

import pytest

from kproj.model.analysis_info import AnalysisInfo
from kproj.model.project_info import ProjectInfo, Status
from kproj.model.publication import AssetRef, Publication


def _project() -> ProjectInfo:
    return ProjectInfo(
        project="cpNode-Xiao-68x90",
        title="cpNode-Xiao-68x90",
        company="MRCS",
        design_rev="1.0",
        board_rev="1.0B",
        date="2026.06",
        designer="John Plocher",
        tagline="MRCS cpNode",
        overview="MRCS cpNode controller",
        status=Status.ACTIVE,
    )


def test_asset_ref_is_frozen() -> None:
    """``AssetRef`` is immutable."""
    asset = AssetRef(path="/versions/x/1.0B/top.png", tag="render-top")
    with pytest.raises(dataclasses.FrozenInstanceError):
        asset.path = "/other"  # type: ignore[misc]


def test_asset_ref_optional_fields_default_to_empty() -> None:
    """``title`` and ``post`` default to empty strings."""
    asset = AssetRef(path="/p", tag="t")
    assert asset.title == ""
    assert asset.post == ""


def test_publication_is_frozen() -> None:
    """``Publication`` is immutable."""
    pub = Publication(project_info=_project(), analysis_info=AnalysisInfo(findings=()), body_md="")
    with pytest.raises(dataclasses.FrozenInstanceError):
        pub.body_md = "x"  # type: ignore[misc]


def test_publication_default_asset_lists_are_empty_tuples() -> None:
    """``images`` and ``artifacts`` default to empty tuples."""
    pub = Publication(project_info=_project(), analysis_info=AnalysisInfo(findings=()), body_md="")
    assert pub.images == ()
    assert pub.artifacts == ()
