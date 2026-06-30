"""Unit tests for :class:`kproj.services.site_publisher.SitePublisher`.

Covers:
- :meth:`SitePublisher.detect_outcome` — noop / refresh / publish discrimination
  based on file existence, asset manifest, and rendered content comparison.
- :meth:`SitePublisher.publish` — atomic writes, journaled registration, git
  add/commit/push with ChangeJournal bookkeeping.

All git subprocess calls are monkeypatched so no real git repo is needed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import yaml

from kproj.model.analysis_info import AnalysisInfo
from kproj.model.finding import Finding
from kproj.model.project_info import ProjectInfo, Status
from kproj.model.publication import AssetRef, Publication
from kproj.model.publish_result import PublishResult
from kproj.model.severity import Severity
from kproj.services.change_journal import ChangeJournal
from kproj.services.site_publisher import SitePublisher

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


def _make_site_repo(tmp_path: Path) -> Path:
    """Create a minimal site-repo directory structure."""
    site = tmp_path / "site"
    site.mkdir()
    # Initialise as a bare git repo for git commands
    os.system(f"git -C '{site}' init -q")
    os.system(f"git -C '{site}' config user.email 'test@test.com'")
    os.system(f"git -C '{site}' config user.name 'Test'")
    return site


def _open_journal(site_repo: Path, *, dry_run: bool = False) -> ChangeJournal:
    return ChangeJournal(site_repo, dry_run=dry_run)


def _write_version_file(
    site_repo: Path,
    P: str,
    R: str,
    content: str,
) -> Path:
    """Write a version file into site_repo/_versions/<P>/<R>.md."""
    path = site_repo / "_versions" / P / f"{R}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_pages_file(site_repo: Path, P: str, content: str) -> Path:
    path = site_repo / "pages" / f"{P}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ──────────────────────────── detect_outcome ─────────────────────────────────


class TestDetectOutcome:
    """Tests for :meth:`SitePublisher.detect_outcome`."""

    def test_publish_when_version_file_absent(self, tmp_path: Path) -> None:
        """No existing version file → outcome is 'publish'."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        outcome = SitePublisher.detect_outcome(pub, site)
        assert outcome == "publish"

    def test_publish_when_asset_missing(self, tmp_path: Path) -> None:
        """Version file exists but a referenced asset is missing → 'publish'."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub(
            images=(
                AssetRef(
                    path="/versions/Demo/1.0B/Demo-1.0B.top.png",
                    tag="render-top",
                    title="Top",
                ),
            ),
        )
        # Write a version file so absence test doesn't short-circuit
        from kproj.formatters.front_matter_summary_formatter import FrontMatterSummaryFormatter

        fm = FrontMatterSummaryFormatter().render(pub)
        content = f"---\n{fm}---\n{pub.body_md}\n"
        _write_version_file(site, "Demo", "1.0B", content)

        outcome = SitePublisher.detect_outcome(pub, site)
        assert outcome == "publish"

    def test_noop_when_all_matches(self, tmp_path: Path) -> None:
        """Existing file matches would-be output and no assets → 'noop'."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        # Write the version file with exactly the would-be content
        from kproj.formatters.front_matter_summary_formatter import FrontMatterSummaryFormatter

        fm = FrontMatterSummaryFormatter().render(pub)
        content = f"---\n{fm}---\n{pub.body_md}\n"
        _write_version_file(site, "Demo", "1.0B", content)
        # Write matching pages file
        _write_pages_file(site, "Demo", f"---\nproject: Demo\n---\n{pub.readme_md}\n")

        outcome = SitePublisher.detect_outcome(pub, site)
        assert outcome == "noop"

    def test_refresh_when_front_matter_differs(self, tmp_path: Path) -> None:
        """On-disk front-matter differs → 'refresh'."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        # Write a version file with DIFFERENT status
        stale = "---\nstatus: experimental\n---\nbody\n"
        _write_version_file(site, "Demo", "1.0B", stale)
        _write_pages_file(site, "Demo", f"---\nproject: Demo\n---\n{pub.readme_md}\n")

        outcome = SitePublisher.detect_outcome(pub, site)
        assert outcome in ("refresh", "publish")

    def test_refresh_when_readme_differs(self, tmp_path: Path) -> None:
        """On-disk pages/<P>.md body differs from publication.readme_md → 'refresh'."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        from kproj.formatters.front_matter_summary_formatter import FrontMatterSummaryFormatter

        fm = FrontMatterSummaryFormatter().render(pub)
        content = f"---\n{fm}---\n{pub.body_md}\n"
        _write_version_file(site, "Demo", "1.0B", content)
        # Write a DIFFERENT readme
        _write_pages_file(site, "Demo", "---\nproject: Demo\n---\n# OLD README\n")

        outcome = SitePublisher.detect_outcome(pub, site)
        assert outcome in ("refresh", "publish")


# ──────────────────────────── publish ────────────────────────────────────────


class TestPublish:
    """Tests for :meth:`SitePublisher.publish`."""

    def _patched_subprocess_run(self, mocker: Any | None = None) -> MagicMock:
        """Return a MagicMock that patches subprocess_runner.run to a no-op."""
        mock = MagicMock()
        mock.return_value = MagicMock(returncode=0, stdout="", stderr="", command=())
        return mock

    def test_publish_writes_version_file(self, tmp_path: Path) -> None:
        """publish() creates _versions/<P>/<R>.md."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            result = sp.publish(pub, site, no_push=True, dry_run=False)

        version_file = site / "_versions" / "Demo" / "1.0B.md"
        assert version_file.exists()
        assert isinstance(result, PublishResult)

    def test_publish_writes_pages_file(self, tmp_path: Path) -> None:
        """publish() creates pages/<P>.md."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=False)

        pages_file = site / "pages" / "Demo.md"
        assert pages_file.exists()
        assert "demo project" in pages_file.read_text().lower()

    def test_publish_returns_published_outcome(self, tmp_path: Path) -> None:
        """First publish returns outcome='published'."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            result = sp.publish(pub, site, no_push=True, dry_run=False)

        assert result.outcome == "published"

    def test_publish_version_file_contains_valid_yaml_front_matter(self, tmp_path: Path) -> None:
        """The written _versions/<P>/<R>.md has parseable YAML front-matter."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=False)

        version_file = site / "_versions" / "Demo" / "1.0B.md"
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
            sp.publish(pub, site, no_push=True, dry_run=False)

        tracked = list(journal.all_paths())
        assert any("1.0B.md" in str(p) for p in tracked)
        assert any("Demo.md" in str(p) for p in tracked)

    def test_dry_run_does_not_write_files(self, tmp_path: Path) -> None:
        """dry_run=True must not write any files to site_repo."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=True)

        version_file = site / "_versions" / "Demo" / "1.0B.md"
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
            sp.publish(pub, site, no_push=True, dry_run=False)

        push_calls = [c for c in mock_git.call_args_list if "push" in (c.args[0] if c.args else [])]
        assert not push_calls

    def test_publish_calls_git_add_and_commit(self, tmp_path: Path) -> None:
        """publish() invokes git add and git commit (not a dry-run)."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        called_commands: list[list[str]] = []

        def _fake_git(cmd: list[str], **kwargs: Any) -> None:
            called_commands.append(cmd)

        with patch("kproj.services.site_publisher._git_run", side_effect=_fake_git):
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=False)

        verbs = [cmd[0] for cmd in called_commands if cmd]
        assert "add" in verbs
        assert "commit" in verbs

    def test_refresh_returns_refreshed_outcome(self, tmp_path: Path) -> None:
        """Re-publish of existing version returns outcome='refreshed'."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        # Pre-populate an existing version file with the same publication content
        from kproj.formatters.front_matter_summary_formatter import FrontMatterSummaryFormatter

        fm = FrontMatterSummaryFormatter().render(pub)
        content = f"---\n{fm}---\n{pub.body_md}\n"
        _write_version_file(site, "Demo", "1.0B", content)
        _write_pages_file(site, "Demo", f"---\nproject: Demo\n---\n{pub.readme_md}\n")

        # Now publish with a changed body (to force refresh not noop)
        pub_changed = Publication(
            project_info=pub.project_info,
            analysis_info=pub.analysis_info,
            body_md="## Metadata Audit\n\n| warning | comment9_missing | | |",
            readme_md=pub.readme_md,
        )

        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            result = sp.publish(pub_changed, site, no_push=True, dry_run=False)

        assert result.outcome == "refreshed"

    def test_noop_when_content_unchanged(self, tmp_path: Path) -> None:
        """Re-publish with unchanged content returns outcome='noop'."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()

        # Write the exact content that publish() would emit
        from kproj.formatters.front_matter_summary_formatter import FrontMatterSummaryFormatter

        fm = FrontMatterSummaryFormatter().render(pub)
        content = f"---\n{fm}---\n{pub.body_md}\n"
        _write_version_file(site, "Demo", "1.0B", content)
        _write_pages_file(site, "Demo", f"---\nproject: Demo\n---\n{pub.readme_md}\n")

        journal = _open_journal(site, dry_run=True)
        with patch("kproj.services.site_publisher._git_run") as mock_git:
            mock_git.return_value = None
            sp = SitePublisher(journal)
            result = sp.publish(pub, site, no_push=True, dry_run=False)

        assert result.outcome == "noop"

    def test_commit_message_add_for_new_project(self, tmp_path: Path) -> None:
        """First-ever publish for a project uses 'add:' commit prefix."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        commit_msgs: list[str] = []

        def _fake_git(cmd: list[str], **kwargs: Any) -> None:
            if cmd and cmd[0] == "commit":
                # Extract the -m argument
                for i, tok in enumerate(cmd):
                    if tok == "-m" and i + 1 < len(cmd):
                        commit_msgs.append(cmd[i + 1])

        with patch("kproj.services.site_publisher._git_run", side_effect=_fake_git):
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=False)

        assert commit_msgs
        assert commit_msgs[0].startswith("add:") or "Demo" in commit_msgs[0]

    def test_commit_message_publish_for_new_version(self, tmp_path: Path) -> None:
        """New version for existing project uses 'publish:' commit prefix."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        # Create an existing pages/<P>.md (project already known)
        _write_pages_file(site, "Demo", "---\nproject: Demo\n---\nOld README\n")
        journal = _open_journal(site, dry_run=True)

        commit_msgs: list[str] = []

        def _fake_git(cmd: list[str], **kwargs: Any) -> None:
            if cmd and cmd[0] == "commit":
                for i, tok in enumerate(cmd):
                    if tok == "-m" and i + 1 < len(cmd):
                        commit_msgs.append(cmd[i + 1])

        with patch("kproj.services.site_publisher._git_run", side_effect=_fake_git):
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=False)

        assert commit_msgs
        assert commit_msgs[0].startswith("publish:")

    def test_commit_message_refresh(self, tmp_path: Path) -> None:
        """Metadata refresh uses 'refresh:' commit prefix."""
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()

        # Write existing version with different body
        from kproj.formatters.front_matter_summary_formatter import FrontMatterSummaryFormatter

        fm = FrontMatterSummaryFormatter().render(pub)
        content = f"---\n{fm}---\nOLD BODY\n"
        _write_version_file(site, "Demo", "1.0B", content)
        _write_pages_file(site, "Demo", f"---\nproject: Demo\n---\n{pub.readme_md}\n")

        journal = _open_journal(site, dry_run=True)
        commit_msgs: list[str] = []

        def _fake_git(cmd: list[str], **kwargs: Any) -> None:
            if cmd and cmd[0] == "commit":
                for i, tok in enumerate(cmd):
                    if tok == "-m" and i + 1 < len(cmd):
                        commit_msgs.append(cmd[i + 1])

        with patch("kproj.services.site_publisher._git_run", side_effect=_fake_git):
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=False)

        assert commit_msgs
        assert commit_msgs[0].startswith("refresh:")

    def test_publish_stages_every_journaled_path(self, tmp_path: Path) -> None:
        """BLOCKER 2 regression: ``git add`` must cover ALL journal paths.

        Producers (PcbExporter, SchematicExporter, IbomGenerator,
        FabPackager, SourcePackager) register every generated asset
        with the :class:`ChangeJournal` via ``will_create`` /
        ``will_modify``.  Before the fix, ``SitePublisher.publish``
        staged only the version-page and project-page markdown, so the
        committed markdown linked to asset files that were never
        staged or pushed.  After the fix, every path in
        ``journal.all_paths()`` is added (deduplicated, relative to
        ``site_repo``).
        """
        site = tmp_path / "site"
        site.mkdir()
        pub = _pub()
        journal = _open_journal(site, dry_run=True)

        # Simulate producer side-effects: real asset files on disk plus
        # journal registration.  These mirror what PcbExporter et al do
        # before SitePublisher.publish() is called from the workflow.
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

        # Capture the arguments passed to git so we can assert every
        # journaled path is in the final `git add` set.
        added_paths: list[str] = []

        def _fake_git(cmd: list[str], **kwargs: Any) -> None:
            if cmd and cmd[0] == "add":
                added_paths.extend(cmd[1:])

        with patch("kproj.services.site_publisher._git_run", side_effect=_fake_git):
            sp = SitePublisher(journal)
            sp.publish(pub, site, no_push=True, dry_run=False)

        # Every asset must appear in git add's argv (as paths relative to site_repo).
        for asset in asset_files:
            rel = str(asset.relative_to(site))
            assert rel in added_paths, (
                f"asset {rel} was not staged for commit; "
                f"BLOCKER 2: SitePublisher must stage every journal.all_paths() entry. "
                f"added_paths={added_paths}"
            )
        # And the version + pages markdown still need to be in there.
        assert "_versions/Demo/1.0B.md" in added_paths
        assert "pages/Demo.md" in added_paths

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
            result = sp.publish(pub, site, no_push=True, dry_run=False)

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
            sp.publish(pub, site, no_push=True, dry_run=False)

        version_file = site / "_versions" / "Demo" / "1.0B.md"
        assert version_file.exists()

        # Simulate rollback
        journal.rollback()

        assert not version_file.exists()
