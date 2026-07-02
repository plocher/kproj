"""Unit tests for :class:`kproj.services.site_publisher.SitePublisher`.

Change detection is delegated to git (see the module docstring), so the
noop/refresh/publish discrimination is proven interactively rather than
with mocked-git unit tests.  What remains here is the git-independent
behaviour:

- :meth:`SitePublisher.publish` - atomic writes, journal registration,
  the ``git add`` staging set, dry-run, no-push, findings passthrough.
- :func:`_build_project_index_content` - the project section-index body.
- :class:`ChangeJournal` rollback of files written by ``publish``.

``_git_run`` is monkeypatched so no real git repo is required; the git
diff/commit path itself is validated interactively, not here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

from kproj.config import GENERIC_SITE_PROFILE
from kproj.model.analysis_info import AnalysisInfo
from kproj.model.finding import Finding
from kproj.model.project_info import ProjectInfo, Status
from kproj.model.publication import Publication
from kproj.model.publish_result import PublishResult
from kproj.model.severity import Severity
from kproj.services.change_journal import ChangeJournal
from kproj.services.site_publisher import SitePublisher, _build_project_index_content

# Tests reference GENERIC_SITE_PROFILE's directory constants rather than
# string literals so they exercise the abstraction contract ("the version
# file lands under the profile's versions_dir") rather than pinning to a
# specific backend's layout.  See ``docs/DESIGN.md`` § *SiteProfile*.

# ──────────────────────────── fixtures / helpers ────────────────────────────


def _pi(**kwargs: Any) -> ProjectInfo:
    defaults: dict[str, Any] = {
        "project": "Demo",
        "title": "Demo Board",
        "company": "MRCS",
        "design_rev": "1.0",
        "board_rev": "1.0B",
        "date": "2026.04",
        "designer": "Alice Designer",
        "tagline": "Demo tagline",
        "overview": "Demo overview",
        "status": Status.ACTIVE,
        "tags": ("MRCS", "kicad"),
    }
    defaults.update(kwargs)
    return ProjectInfo(**defaults)


def _pub(project_info: ProjectInfo | None = None, **kwargs: Any) -> Publication:
    return Publication(
        project_info=project_info or _pi(),
        analysis_info=AnalysisInfo(),
        body_md="## Metadata Audit\n\n_No findings._",
        readme_md="# Demo\nA demo project.",
        **kwargs,
    )


def _open_journal(site_repo: Path, *, dry_run: bool = False) -> ChangeJournal:
    return ChangeJournal(site_repo, dry_run=dry_run)


def _write_version_file(
    site_repo: Path,
    P: str,
    R: str,
    content: str,
) -> Path:
    """Write a version file under the GENERIC profile's versions_dir."""
    path = site_repo / GENERIC_SITE_PROFILE.versions_dir / P / f"{R}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_pages_file(site_repo: Path, P: str, content: str) -> Path:
    """Write the project section index (``<versions_dir>/<P>/_index.md``)."""
    path = GENERIC_SITE_PROFILE.project_index_path(site_repo, P)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ──────────────────────────── publish ────────────────────────────────────────


class TestPublish:
    """Tests for :meth:`SitePublisher.publish` (git-independent behaviour)."""

    def test_publish_writes_version_file(self, tmp_path: Path) -> None:
        """publish() creates <versions_dir>/<P>/<R>.md."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            result = sp.publish(
                pub, site, no_push=True, dry_run=False, site_profile=GENERIC_SITE_PROFILE
            )

        version_file = site / GENERIC_SITE_PROFILE.versions_dir / "Demo" / "1.0B.md"
        assert version_file.exists()
        assert isinstance(result, PublishResult)

    def test_publish_writes_project_index(self, tmp_path: Path) -> None:
        """publish() creates the project section index <versions_dir>/<P>/_index.md."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=False, site_profile=GENERIC_SITE_PROFILE)

        index_file = GENERIC_SITE_PROFILE.project_index_path(site, "Demo")
        assert index_file.exists()
        assert "demo project" in index_file.read_text().lower()

    def test_publish_version_file_contains_valid_yaml_front_matter(self, tmp_path: Path) -> None:
        """The written version page has parseable YAML front-matter."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=False, site_profile=GENERIC_SITE_PROFILE)

        version_file = site / GENERIC_SITE_PROFILE.versions_dir / "Demo" / "1.0B.md"
        raw = version_file.read_text()
        # Strip fences and parse YAML
        parts = raw.split("---\n", 2)
        assert len(parts) >= 3, f"Expected front-matter fences, got: {raw[:200]}"
        parsed = yaml.safe_load(parts[1])
        assert parsed["project"] == "Demo"
        assert parsed["publish"] is True

    def test_publish_registers_paths_with_journal(self, tmp_path: Path) -> None:
        """publish() registers the written paths with the ChangeJournal."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=False, site_profile=GENERIC_SITE_PROFILE)

        tracked = list(journal.all_paths())
        assert any("1.0B.md" in str(p) for p in tracked)
        assert any("_index.md" in str(p) for p in tracked)

    def test_dry_run_does_not_write_files(self, tmp_path: Path) -> None:
        """dry_run=True must not write any files to site_repo."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=True, site_profile=GENERIC_SITE_PROFILE)

        version_file = site / GENERIC_SITE_PROFILE.versions_dir / "Demo" / "1.0B.md"
        assert not version_file.exists()

    def test_no_push_skips_git_push(self, tmp_path: Path) -> None:
        """no_push=True must not invoke git push."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=False, site_profile=GENERIC_SITE_PROFILE)

        push_calls = [c for c in mock_git.call_args_list if "push" in (c.args[0] if c.args else [])]
        assert not push_calls

    def test_publish_stages_every_journaled_path(self, tmp_path: Path) -> None:
        """``git add`` must cover ALL journal paths (ADR 0005 / BLOCKER 2).

        Producers register every generated asset with the
        :class:`ChangeJournal`; ``SitePublisher.publish`` must stage every
        path in ``journal.all_paths()`` (deduplicated, relative to
        ``site_repo``) plus the version page + project section index.
        """
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        # Simulate producer side-effects: real asset files on disk plus
        # journal registration.
        asset_dir = site / "versions" / "Demo" / "1.0B"
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset_files = [
            asset_dir / "Demo-1.0B.top.png",
            asset_dir / "Demo-1.0B.bottom.png",
            asset_dir / "Demo-1.0B.sch.svg",
            asset_dir / "Demo-1.0B.sch.pdf",
            asset_dir / "Demo-1.0B.ibom.html",
            asset_dir / "Demo-1.0B.step",
            asset_dir / "Demo-1.0B.source.zip",
        ]
        for asset in asset_files:
            asset.write_bytes(b"placeholder")
            journal.will_create(asset)

        # Capture the arguments passed to git add.
        added_paths: list[str] = []

        def _fake_git(cmd: list[str], **kwargs: Any) -> None:
            if cmd and cmd[0] == "add":
                added_paths.extend(cmd[1:])

        with patch("kproj.services.site_publisher._git_run", side_effect=_fake_git):
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=False, site_profile=GENERIC_SITE_PROFILE)

        for asset in asset_files:
            rel = str(asset.relative_to(site))
            assert rel in added_paths, (
                f"asset {rel} was not staged for commit; "
                f"SitePublisher must stage every journal.all_paths() entry. "
                f"added_paths={added_paths}"
            )
        assert f"{GENERIC_SITE_PROFILE.versions_dir}/Demo/1.0B.md" in added_paths
        assert f"{GENERIC_SITE_PROFILE.versions_dir}/Demo/_index.md" in added_paths

    def test_findings_passed_through_result(self, tmp_path: Path) -> None:
        """Findings from the publication appear in the returned PublishResult."""
        site = tmp_path / "site"
        site.mkdir()
        ai = AnalysisInfo(
            findings=(
                Finding(
                    severity=Severity.WARNING,
                    field="comment9_missing",
                    value="",
                    reason="COMMENT9 absent",
                ),
            )
        )
        pub = _pub()
        pub = Publication(
            project_info=pub.project_info,
            analysis_info=ai,
            body_md=pub.body_md,
            readme_md=pub.readme_md,
        )
        journal = _open_journal(site, dry_run=True)

        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            result = sp.publish(
                pub, site, no_push=True, dry_run=False, site_profile=GENERIC_SITE_PROFILE
            )

        assert any(f.field == "comment9_missing" for f in result.findings)


# ──────────────────────────── rollback interaction ────────────────────────────


class TestJournalRollback:
    """Verify journal rollback cleans up files written by publish()."""

    def test_rollback_removes_written_files(self, tmp_path: Path) -> None:
        """A ChangeJournal rollback deletes files written by publish()."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = ChangeJournal(site, dry_run=True)

        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=False, site_profile=GENERIC_SITE_PROFILE)

        version_file = site / GENERIC_SITE_PROFILE.versions_dir / "Demo" / "1.0B.md"
        assert version_file.exists()

        # Simulate rollback
        journal.rollback()

        assert not version_file.exists()


# ──────────────────────────── project index rendering ─────────────────────────


class TestBuildProjectIndexContent:
    """Tests for the project section-index body (README + DESCRIPTION + datasheets)."""

    def test_readme_only_matches_legacy_output(self) -> None:
        """A README-only project renders exactly as the pre-datasheet format."""
        pub = _pub()  # readme set, description="", datasheets=()
        assert _build_project_index_content(pub) == (
            "---\ntitle: Demo\nproject: Demo\n---\n# Demo\nA demo project.\n"
        )

    def test_bare_when_no_docs(self) -> None:
        """No README / DESCRIPTION / datasheets yields an empty body."""
        pub = Publication(
            project_info=_pi(), analysis_info=AnalysisInfo(), body_md="", readme_md=""
        )
        assert _build_project_index_content(pub) == ("---\ntitle: Demo\nproject: Demo\n---\n\n")

    def test_description_and_datasheets_rendered_in_order(self) -> None:
        """README, then DESCRIPTION prose, then a ``## Datasheets`` bullet list."""
        pub = _pub(
            description="Prose about the board.",
            datasheets=("Cap-Foo.pdf", "Regulator-Bar.pdf"),
        )
        content = _build_project_index_content(pub)
        body = content.split("---\n", 2)[2]
        assert body == (
            "# Demo\nA demo project.\n\n"
            "Prose about the board.\n\n"
            "## Datasheets\n\n- Cap-Foo.pdf\n- Regulator-Bar.pdf\n"
        )

    def test_datasheets_without_readme_or_description(self) -> None:
        """Datasheets alone render under the heading with no stray blank lead."""
        pub = Publication(
            project_info=_pi(),
            analysis_info=AnalysisInfo(),
            body_md="",
            readme_md="",
            datasheets=("Only.pdf",),
        )
        body = _build_project_index_content(pub).split("---\n", 2)[2]
        assert body == "## Datasheets\n\n- Only.pdf\n"
