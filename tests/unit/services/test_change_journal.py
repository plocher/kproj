"""Unit tests for :mod:`kproj.services.change_journal`.

Validates the transactional contract per
``docs/adr/0005-writetracker-transactional-site-writes.md``:
register intent → on exception, rollback created files and restore
modified files; on success, leave the working tree intact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kproj.services import change_journal as change_journal_module
from kproj.services.change_journal import ChangeJournal


@pytest.fixture
def site_repo(tmp_path: Path) -> Path:
    """Return an isolated ``site_repo`` path under ``tmp_path``."""
    repo = tmp_path / "site"
    repo.mkdir()
    return repo


def test_change_journal_is_a_context_manager(site_repo: Path) -> None:
    """``ChangeJournal`` supports ``with`` use."""
    with ChangeJournal(site_repo) as journal:
        assert isinstance(journal, ChangeJournal)


def test_change_journal_records_created_paths(site_repo: Path) -> None:
    """``will_create`` records the path so it appears in ``all_paths()``."""
    target = site_repo / "_versions" / "demo" / "1.0B.md"
    with ChangeJournal(site_repo) as journal:
        journal.will_create(target)
        assert target in set(journal.all_paths())


def test_change_journal_rejects_paths_outside_site_repo(site_repo: Path, tmp_path: Path) -> None:
    """Paths outside *site_repo* are rejected at intake (validation at boundary)."""
    rogue = tmp_path / "outside.md"
    with ChangeJournal(site_repo) as journal, pytest.raises(ValueError, match="outside site_repo"):
        journal.will_create(rogue)


def test_change_journal_rollback_unlinks_created_files(site_repo: Path) -> None:
    """On exception, registered-as-created files are unlinked."""
    target = site_repo / "_versions" / "demo" / "1.0B.md"

    class _Boom(RuntimeError):
        pass

    with pytest.raises(_Boom), ChangeJournal(site_repo) as journal:
        target.parent.mkdir(parents=True)
        journal.will_create(target)
        target.write_text("body")
        raise _Boom("simulated mid-pipeline failure")
    assert not target.exists()


def test_change_journal_rollback_skips_missing_created_files(site_repo: Path) -> None:
    """Unlinking an already-missing path does not error."""
    target = site_repo / "phantom.md"

    class _Boom(RuntimeError):
        pass

    with pytest.raises(_Boom), ChangeJournal(site_repo) as journal:
        journal.will_create(target)
        raise _Boom


def test_change_journal_rollback_restores_modified_files(
    site_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Modified files are restored from ``HEAD`` via a git checkout."""
    target = site_repo / "pages" / "demo.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")

    captured: list[list[str]] = []

    def _fake_run(command: Any, **kwargs: Any) -> Any:
        captured.append(list(command))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""
            elapsed_seconds = 0.0

        return _Result()

    monkeypatch.setattr(change_journal_module, "subprocess_run", _fake_run)

    class _Boom(RuntimeError):
        pass

    with pytest.raises(_Boom), ChangeJournal(site_repo) as journal:
        journal.will_modify(target)
        target.write_text("modified")
        raise _Boom

    # Expect one git checkout invocation referencing the relative path.
    matching = [
        cmd for cmd in captured if cmd[:5] == ["git", "-C", str(site_repo), "checkout", "--"]
    ]
    assert len(matching) == 1
    assert matching[0][5] == str(target.relative_to(site_repo))


def test_change_journal_commit_then_failed_push_resets_head(
    site_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When mark_committed() ran but mark_pushed() didn't, rollback resets HEAD^."""
    captured: list[list[str]] = []

    def _fake_run(command: Any, **kwargs: Any) -> Any:
        captured.append(list(command))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""
            elapsed_seconds = 0.0

        return _Result()

    monkeypatch.setattr(change_journal_module, "subprocess_run", _fake_run)

    class _Boom(RuntimeError):
        pass

    with pytest.raises(_Boom), ChangeJournal(site_repo) as journal:
        journal.mark_committed()
        raise _Boom

    matching = [
        cmd for cmd in captured if cmd == ["git", "-C", str(site_repo), "reset", "--hard", "HEAD^"]
    ]
    assert len(matching) == 1


def test_change_journal_clean_exit_does_not_rollback(
    site_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On normal exit (no exception), no git commands run during teardown."""
    captured: list[list[str]] = []

    def _fake_run(command: Any, **kwargs: Any) -> Any:
        captured.append(list(command))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""
            elapsed_seconds = 0.0

        return _Result()

    monkeypatch.setattr(change_journal_module, "subprocess_run", _fake_run)
    target = site_repo / "x.md"
    with ChangeJournal(site_repo) as journal:
        journal.will_create(target)
        target.write_text("ok")
    assert captured == []
    assert target.exists()


def test_change_journal_dry_run_records_intent_without_calling_git(
    site_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In ``dry_run=True`` mode, rollback does not invoke git."""
    captured: list[list[str]] = []

    def _fake_run(command: Any, **kwargs: Any) -> Any:
        captured.append(list(command))

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""
            elapsed_seconds = 0.0

        return _Result()

    monkeypatch.setattr(change_journal_module, "subprocess_run", _fake_run)

    class _Boom(RuntimeError):
        pass

    target = site_repo / "pages" / "demo.md"
    target.parent.mkdir(parents=True)
    target.write_text("original")

    with pytest.raises(_Boom), ChangeJournal(site_repo, dry_run=True) as journal:
        journal.will_modify(target)
        journal.mark_committed()
        raise _Boom
    assert captured == []  # no git invoked in dry-run rollback


def test_change_journal_all_paths_deduplicates(site_repo: Path) -> None:
    """A path registered twice appears once in ``all_paths()``."""
    target = site_repo / "x.md"
    with ChangeJournal(site_repo) as journal:
        journal.will_create(target)
        journal.will_modify(target)  # idempotent / overrides nothing
        assert list(journal.all_paths()) == [target]


def test_register_output_dispatches_create_when_path_absent(site_repo: Path) -> None:
    """BLOCKER 3 helper: a path that does not exist registers as create."""
    target = site_repo / "_versions" / "demo" / "1.0B.md"
    with ChangeJournal(site_repo) as journal:
        journal.register_output(target)

        assert target in journal._created  # type: ignore[attr-defined]
        assert target not in journal._modified  # type: ignore[attr-defined]


def test_register_output_dispatches_modify_when_path_exists(site_repo: Path) -> None:
    """BLOCKER 3 helper: a pre-existing path registers as modify."""
    target = site_repo / "_versions" / "demo" / "1.0B.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("existing content")
    with ChangeJournal(site_repo) as journal:
        journal.register_output(target)
        assert target in journal._modified  # type: ignore[attr-defined]
        assert target not in journal._created  # type: ignore[attr-defined]
