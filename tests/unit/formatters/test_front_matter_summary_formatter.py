"""Unit tests for :class:`kproj.formatters.front_matter_summary_formatter.FrontMatterSummaryFormatter`.

Per ``docs/DESIGN.md`` § *Front-matter shape*, this formatter is
responsible for the authoritative YAML front-matter emitted into
``_versions/<P>/<R>.md`` — including the ``libraries:`` section
(kproj#4 wave-3 scope).
"""

from __future__ import annotations

import yaml

from kproj.formatters.front_matter_summary_formatter import FrontMatterSummaryFormatter
from kproj.model.analysis_info import AnalysisInfo
from kproj.model.finding import Finding
from kproj.model.library_ref import LibraryRef
from kproj.model.project_info import ProjectInfo, Status
from kproj.model.publication import AssetRef, Publication
from kproj.model.severity import Severity


# ──────────────────────────── helpers ────────────────────────────


def _pi(**kwargs: object) -> ProjectInfo:
    """Build a ProjectInfo with sane defaults."""
    from kproj.model.raw_title_block import RawTitleBlock

    defaults: dict[str, object] = {
        "project": "MyProject",
        "title": "My Board",
        "company": "MRCS",
        "design_rev": "1.0",
        "board_rev": "1.0B",
        "date": "2026.04",
        "designer": "Alice Designer",
        "tagline": "A tagline",
        "overview": "An overview",
        "status": Status.ACTIVE,
        "tags": ("MRCS", "kicad"),
    }
    defaults.update(kwargs)
    return ProjectInfo(**defaults)  # type: ignore[arg-type]


def _pub(**kwargs: object) -> Publication:
    """Build a Publication using _pi() defaults."""
    pi = kwargs.pop("project_info", _pi())
    ai = kwargs.pop("analysis_info", AnalysisInfo())
    return Publication(
        project_info=pi,
        analysis_info=ai,
        body_md="",
        **kwargs,  # type: ignore[arg-type]
    )


def _parse(pub: Publication) -> dict:  # type: ignore[type-arg]
    """Render and parse front-matter YAML as a dict."""
    return yaml.safe_load(FrontMatterSummaryFormatter().render(pub))


# ──────────────────────────── tests ─────────────────────────────


class TestRenderReturnType:
    def test_returns_string(self) -> None:
        assert isinstance(FrontMatterSummaryFormatter().render(_pub()), str)

    def test_is_valid_yaml(self) -> None:
        parsed = _parse(_pub())
        assert isinstance(parsed, dict)


class TestRequiredTopLevelFields:
    def test_iskicad_true_for_active(self) -> None:
        assert _parse(_pub())["iskicad"] is True

    def test_layout_eagle(self) -> None:
        assert _parse(_pub())["layout"] == "eagle"

    def test_sidebar(self) -> None:
        assert _parse(_pub())["sidebar"] == "spcoast_sidebar"

    def test_project_field(self) -> None:
        assert _parse(_pub())["project"] == "MyProject"

    def test_title_is_board_rev(self) -> None:
        assert _parse(_pub())["title"] == "1.0B"

    def test_board_rev_field(self) -> None:
        assert _parse(_pub())["board_rev"] == "1.0B"

    def test_design_rev_field(self) -> None:
        assert _parse(_pub())["design_rev"] == "1.0"

    def test_date_field(self) -> None:
        assert _parse(_pub())["date"] == "2026.04"

    def test_status_field(self) -> None:
        assert _parse(_pub())["status"] == "active"

    def test_publish_true(self) -> None:
        assert _parse(_pub())["publish"] is True

    def test_tagline_field(self) -> None:
        assert _parse(_pub())["tagline"] == "A tagline"

    def test_overview_field(self) -> None:
        assert _parse(_pub())["overview"] == "An overview"

    def test_company_field(self) -> None:
        assert _parse(_pub())["company"] == "MRCS"

    def test_designer_field(self) -> None:
        assert _parse(_pub())["designer"] == "Alice Designer"


class TestIskicadObsolete:
    def test_retired_status_emits_obsolete(self) -> None:
        pub = _pub(project_info=_pi(status=Status.RETIRED))
        assert _parse(pub)["iskicad"] == "obsolete"

    def test_replaced_by_status_emits_obsolete(self) -> None:
        pub = _pub(project_info=_pi(status=Status.REPLACED_BY))
        assert _parse(pub)["iskicad"] == "obsolete"

    def test_experimental_status_emits_true(self) -> None:
        pub = _pub(project_info=_pi(status=Status.EXPERIMENTAL))
        assert _parse(pub)["iskicad"] is True

    def test_broken_status_emits_true(self) -> None:
        pub = _pub(project_info=_pi(status=Status.BROKEN))
        assert _parse(pub)["iskicad"] is True


class TestAuditDrcCounts:
    def test_audit_error_count(self) -> None:
        ai = AnalysisInfo(findings=(
            Finding(severity=Severity.ERROR, field="f", value="", reason="r"),
        ))
        parsed = _parse(_pub(analysis_info=ai))
        assert parsed["audit"]["errors"] == 1
        assert parsed["audit"]["warnings"] == 0

    def test_audit_warning_count(self) -> None:
        ai = AnalysisInfo(findings=(
            Finding(severity=Severity.WARNING, field="g", value="", reason="r"),
        ))
        parsed = _parse(_pub(analysis_info=ai))
        assert parsed["audit"]["errors"] == 0
        assert parsed["audit"]["warnings"] == 1

    def test_drc_exclusions_counted_separately(self) -> None:
        ai = AnalysisInfo(findings=(
            Finding(severity=Severity.EXCLUSION, field="track_clearance",
                    value="", reason="r"),
        ))
        parsed = _parse(_pub(analysis_info=ai))
        # exclusions should appear in drc or erc section, not in audit
        # and should NOT bump errors or warnings
        assert parsed["audit"]["errors"] == 0
        assert parsed["audit"]["warnings"] == 0

    def test_drc_block_present(self) -> None:
        parsed = _parse(_pub())
        assert "drc" in parsed
        assert "errors" in parsed["drc"]
        assert "warnings" in parsed["drc"]
        assert "exclusions" in parsed["drc"]

    def test_erc_block_present(self) -> None:
        parsed = _parse(_pub())
        assert "erc" in parsed


class TestLibrariesSection:
    def test_three_bucket_libraries_rendered(self) -> None:
        libs = (
            LibraryRef(name="InternalLib", source="internal"),
            LibraryRef(name="ExternalLib", source="external"),
            LibraryRef(name="AmbigLib", source="ambiguous"),
        )
        parsed = _parse(_pub(libraries=libs))
        assert "libraries" in parsed
        assert "InternalLib" in parsed["libraries"]["internal"]
        assert "ExternalLib" in parsed["libraries"]["external"]
        assert "AmbigLib" in parsed["libraries"]["ambiguous"]

    def test_empty_libraries_handled_gracefully(self) -> None:
        parsed = _parse(_pub(libraries=()))
        # Either absent or all three buckets empty/absent
        if "libraries" in parsed:
            for bucket in ("internal", "external", "ambiguous"):
                assert not parsed["libraries"].get(bucket, [])

    def test_multiple_internal_libs(self) -> None:
        libs = (
            LibraryRef(name="Lib1", source="internal"),
            LibraryRef(name="Lib2", source="internal"),
        )
        parsed = _parse(_pub(libraries=libs))
        internal = parsed["libraries"]["internal"]
        assert "Lib1" in internal
        assert "Lib2" in internal

    def test_buckets_ordered_alphabetically(self) -> None:
        """Within each bucket, libraries are sorted by name."""
        libs = (
            LibraryRef(name="ZZZ", source="internal"),
            LibraryRef(name="AAA", source="internal"),
        )
        parsed = _parse(_pub(libraries=libs))
        internal = parsed["libraries"]["internal"]
        assert internal == sorted(internal)


class TestImagePath:
    def test_thumbnail_image_path(self) -> None:
        parsed = _parse(_pub())
        expected = "/versions/MyProject/1.0B/MyProject-1.0B.thumbnail.png"
        assert parsed["image_path"] == expected


class TestImagesAndArtifacts:
    def test_images_list_rendered(self) -> None:
        images = (
            AssetRef(path="/versions/P/R/P-R.top.png", tag="render-top", title="Top"),
        )
        parsed = _parse(_pub(images=images))
        assert len(parsed["images"]) == 1
        assert parsed["images"][0]["image_path"] == "/versions/P/R/P-R.top.png"
        assert parsed["images"][0]["title"] == "Top"

    def test_artifacts_list_rendered(self) -> None:
        artifacts = (
            AssetRef(
                path="/versions/P/R/P-R.sch.pdf",
                tag="schematic-pdf",
                post="Full schematic (all sheets)",
            ),
        )
        parsed = _parse(_pub(artifacts=artifacts))
        assert len(parsed["artifacts"]) == 1
        entry = parsed["artifacts"][0]
        assert entry["path"] == "/versions/P/R/P-R.sch.pdf"
        assert entry["tag"] == "schematic-pdf"
        assert entry["type"] == "download"
        assert entry["post"] == "Full schematic (all sheets)"

    def test_empty_images_list_present(self) -> None:
        parsed = _parse(_pub(images=()))
        assert "images" in parsed
        assert isinstance(parsed["images"], list)

    def test_empty_artifacts_list_present(self) -> None:
        parsed = _parse(_pub(artifacts=()))
        assert "artifacts" in parsed
        assert isinstance(parsed["artifacts"], list)


class TestRenderAuditMethod:
    """Validate the legacy render_audit(AnalysisInfo) -> dict helper."""

    def test_returns_dict(self) -> None:
        counts = FrontMatterSummaryFormatter().render_audit(AnalysisInfo())
        assert isinstance(counts, dict)

    def test_keys_errors_warnings(self) -> None:
        counts = FrontMatterSummaryFormatter().render_audit(AnalysisInfo())
        assert "errors" in counts
        assert "warnings" in counts

    def test_counts_errors(self) -> None:
        ai = AnalysisInfo(findings=(
            Finding(severity=Severity.ERROR, field="f", value="", reason="r"),
        ))
        counts = FrontMatterSummaryFormatter().render_audit(ai)
        assert counts["errors"] == 1

    def test_counts_warnings(self) -> None:
        ai = AnalysisInfo(findings=(
            Finding(severity=Severity.WARNING, field="g", value="", reason="r"),
        ))
        counts = FrontMatterSummaryFormatter().render_audit(ai)
        assert counts["warnings"] == 1
