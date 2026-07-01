"""Unit tests for :class:`kproj.formatters.front_matter_summary_formatter.FrontMatterSummaryFormatter`.

Per ``docs/DESIGN.md`` § *Front-matter shape*, this formatter is
responsible for the authoritative YAML front-matter emitted into the
per-version markdown file. Under :data:`~kproj.config.GENERIC_SITE_PROFILE`
(the abstract test anchor used throughout this module) the field set
omits the optional ``layout:`` key; production `HUGO_SITE_PROFILE` and
a Jekyll-shaped profile are exercised separately in
:class:`TestLayoutFieldProfileSensitivity`.

Tests reference :data:`GENERIC_SITE_PROFILE` at every call site — there
are no in-code default values on the formatter's ``render`` method.
"""

from __future__ import annotations

import yaml

from kproj.config import GENERIC_SITE_PROFILE, SiteProfile
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


def _parse(
    pub: Publication,
    site_profile: SiteProfile = GENERIC_SITE_PROFILE,
) -> dict:  # type: ignore[type-arg]
    """Render and parse front-matter YAML as a dict.

    Test-helper convenience: defaults to :data:`GENERIC_SITE_PROFILE`
    so individual tests don't repeat the constant.  The underlying
    :meth:`FrontMatterSummaryFormatter.render` has **no default** —
    the profile is passed explicitly here.  Pass an explicit
    *site_profile* to this helper to verify profile-specific field
    emission (e.g. Jekyll's ``layout: eagle``).
    """
    return yaml.safe_load(FrontMatterSummaryFormatter().render(pub, site_profile))


# ──────────────────────────── tests ─────────────────────────────


class TestRenderReturnType:
    def test_returns_string(self) -> None:
        assert isinstance(
            FrontMatterSummaryFormatter().render(_pub(), GENERIC_SITE_PROFILE),
            str,
        )

    def test_is_valid_yaml(self) -> None:
        parsed = _parse(_pub())
        assert isinstance(parsed, dict)


class TestRequiredTopLevelFields:
    def test_iskicad_true_for_active(self) -> None:
        assert _parse(_pub())["iskicad"] is True

    def test_no_layout_field_under_generic_profile(self) -> None:
        """Under GENERIC (Hugo), ``layout:`` is omitted — Hugo picks layout by section.

        Jekyll-specific emission is exercised in
        :class:`TestLayoutFieldProfileSensitivity` below.
        """
        assert "layout" not in _parse(_pub())

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


class TestLayoutFieldProfileSensitivity:
    """Confirm the ``layout:`` field emission tracks the SiteProfile.

    Two profiles cover the shape matrix: GENERIC (Hugo default; no
    layout emission) and a Jekyll-shaped profile that requests
    ``layout: eagle`` (the legacy pre-Hugo emission).
    """

    _JEKYLL_PROFILE = SiteProfile(
        name="jekyll-eagle",
        versions_dir="_versions",
        pages_dir="pages",
        layout_field="eagle",
    )

    def test_generic_profile_omits_layout(self) -> None:
        assert "layout" not in _parse(_pub(), GENERIC_SITE_PROFILE)

    def test_jekyll_profile_emits_layout_eagle(self) -> None:
        assert _parse(_pub(), self._JEKYLL_PROFILE)["layout"] == "eagle"

    def test_custom_profile_layout_value(self) -> None:
        custom = SiteProfile(
            name="custom",
            versions_dir="content/versions",
            pages_dir="content/pages",
            layout_field="kicad-version",
        )
        assert _parse(_pub(), custom)["layout"] == "kicad-version"


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
        ai = AnalysisInfo(
            findings=(Finding(severity=Severity.ERROR, field="f", value="", reason="r"),)
        )
        parsed = _parse(_pub(analysis_info=ai))
        assert parsed["audit"]["errors"] == 1
        assert parsed["audit"]["warnings"] == 0

    def test_audit_warning_count(self) -> None:
        ai = AnalysisInfo(
            findings=(Finding(severity=Severity.WARNING, field="g", value="", reason="r"),)
        )
        parsed = _parse(_pub(analysis_info=ai))
        assert parsed["audit"]["errors"] == 0
        assert parsed["audit"]["warnings"] == 1

    def test_drc_exclusions_counted_separately(self) -> None:
        ai = AnalysisInfo(
            findings=(
                Finding(severity=Severity.EXCLUSION, field="track_clearance", value="", reason="r"),
            )
        )
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

    def test_drc_error_does_not_inflate_audit_or_erc_counts(self) -> None:
        """M2 regression: a DRC finding counts only in the drc block.

        Pre-fix the audit / drc / erc counts were all the same merged
        total of every error/warning in the AnalysisInfo, so a single
        DRC error appeared three times.  After the fix-up, each block
        counts only findings whose :attr:`Finding.source` matches.
        """
        ai = AnalysisInfo(
            findings=(
                Finding(
                    severity=Severity.ERROR,
                    field="silk_overlap",
                    value="(10, 20)",
                    reason="silk over pad",
                    source="drc",
                ),
            )
        )
        parsed = _parse(_pub(analysis_info=ai))
        assert parsed["drc"]["errors"] == 1
        assert parsed["audit"]["errors"] == 0, (
            "M2: DRC error must not inflate audit.errors. "
            f"audit={parsed['audit']}, drc={parsed['drc']}, erc={parsed['erc']}"
        )
        assert parsed["erc"]["errors"] == 0, (
            "M2: DRC error must not inflate erc.errors. "
            f"audit={parsed['audit']}, drc={parsed['drc']}, erc={parsed['erc']}"
        )

    def test_audit_drc_erc_counts_each_from_own_source(self) -> None:
        """M2 regression: counts come from per-source partitioning."""
        ai = AnalysisInfo(
            findings=(
                Finding(
                    severity=Severity.WARNING,
                    field="comment9_missing",
                    value="",
                    reason="absent",
                    source="audit",
                ),
                Finding(
                    severity=Severity.ERROR,
                    field="track_clearance",
                    value="(1, 2)",
                    reason="clearance",
                    source="drc",
                ),
                Finding(
                    severity=Severity.WARNING,
                    field="unconnected_pin",
                    value="U1.1",
                    reason="floating",
                    source="erc",
                ),
            )
        )
        parsed = _parse(_pub(analysis_info=ai))
        assert parsed["audit"] == {"errors": 0, "warnings": 1}
        assert parsed["drc"]["errors"] == 1
        assert parsed["drc"]["warnings"] == 0
        assert parsed["erc"]["warnings"] == 1
        assert parsed["erc"]["errors"] == 0


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
        images = (AssetRef(path="/versions/P/R/P-R.top.png", tag="render-top", title="Top"),)
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
        ai = AnalysisInfo(
            findings=(Finding(severity=Severity.ERROR, field="f", value="", reason="r"),)
        )
        counts = FrontMatterSummaryFormatter().render_audit(ai)
        assert counts["errors"] == 1

    def test_counts_warnings(self) -> None:
        ai = AnalysisInfo(
            findings=(Finding(severity=Severity.WARNING, field="g", value="", reason="r"),)
        )
        counts = FrontMatterSummaryFormatter().render_audit(ai)
        assert counts["warnings"] == 1
