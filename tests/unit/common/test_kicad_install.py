"""Unit tests for :mod:`kproj.common.kicad_install`.

Validates the per-platform probe order defined in
``docs/adr/0009-kicad-install-locator.md``. Real KiCad binaries are
not required \u2014 we monkeypatch :func:`os.environ`,
:func:`shutil.which`, :func:`pathlib.Path.exists`, and
:func:`kproj.common.subprocess_runner.run` (when wired) to stand in
for filesystem presence.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from pathlib import Path

import pytest

from kproj.common import kicad_install
from kproj.common.kicad_install import (
    SUPPORTED_KICAD_MAJORS,
    KicadNotFoundError,
    find_ibom_script,
    find_kicad_cli,
    find_plugins_dir,
    kicad_version,
)

# ----------------------------------------------------------------------
# find_kicad_cli
# ----------------------------------------------------------------------


def test_find_kicad_cli_returns_explicit_env_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``KPROJ_KICAD_CLI`` env var takes precedence when the file exists."""
    explicit = tmp_path / "explicit-kicad-cli"
    explicit.write_text("")
    monkeypatch.setenv("KPROJ_KICAD_CLI", str(explicit))
    assert find_kicad_cli() == explicit


def test_find_kicad_cli_rejects_explicit_env_path_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An explicit override that doesn't exist raises rather than silently fall through."""
    monkeypatch.setenv("KPROJ_KICAD_CLI", str(tmp_path / "no-such-binary"))
    with pytest.raises(KicadNotFoundError):
        find_kicad_cli()


def test_find_kicad_cli_falls_back_to_shutil_which(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When no env / platform default applies, ``shutil.which`` is consulted."""
    fake = tmp_path / "kicad-cli"
    fake.write_text("")
    monkeypatch.delenv("KPROJ_KICAD_CLI", raising=False)
    # neutralize platform-specific defaults
    monkeypatch.setattr(kicad_install, "_PLATFORM_KICAD_CLI_CANDIDATES", ())
    monkeypatch.setattr(
        kicad_install.shutil, "which", lambda name: str(fake) if name == "kicad-cli" else None
    )
    assert find_kicad_cli() == fake


def test_find_kicad_cli_uses_first_platform_default_that_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each platform default is tried in declared order; first hit wins."""
    bad = tmp_path / "no-such"
    good = tmp_path / "kicad-cli"
    good.write_text("")
    monkeypatch.delenv("KPROJ_KICAD_CLI", raising=False)
    monkeypatch.setattr(kicad_install, "_PLATFORM_KICAD_CLI_CANDIDATES", (bad, good))
    monkeypatch.setattr(kicad_install.shutil, "which", lambda name: None)
    assert find_kicad_cli() == good


def test_find_kicad_cli_raises_when_no_candidate_resolves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A missing locator everywhere produces ``KicadNotFoundError``."""
    monkeypatch.delenv("KPROJ_KICAD_CLI", raising=False)
    monkeypatch.setattr(kicad_install, "_PLATFORM_KICAD_CLI_CANDIDATES", ())
    monkeypatch.setattr(kicad_install.shutil, "which", lambda name: None)
    with pytest.raises(KicadNotFoundError):
        find_kicad_cli()


# ----------------------------------------------------------------------
# find_plugins_dir
# ----------------------------------------------------------------------


def test_find_plugins_dir_returns_explicit_kicad9_env_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``KICAD9_3RD_PARTY`` env var wins when the directory exists."""
    plugins = tmp_path / "3rdparty"
    plugins.mkdir()
    monkeypatch.delenv("KICAD10_3RD_PARTY", raising=False)
    monkeypatch.setenv("KICAD9_3RD_PARTY", str(plugins))
    assert find_plugins_dir() == plugins


def test_find_plugins_dir_returns_explicit_kicad10_env_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``KICAD10_3RD_PARTY`` env var wins when the directory exists."""
    plugins = tmp_path / "3rdparty-v10"
    plugins.mkdir()
    monkeypatch.delenv("KICAD9_3RD_PARTY", raising=False)
    monkeypatch.setenv("KICAD10_3RD_PARTY", str(plugins))
    assert find_plugins_dir() == plugins


def test_find_plugins_dir_prefers_kicad10_env_over_kicad9_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When both env vars resolve, ``KICAD10_3RD_PARTY`` wins (newest-first)."""
    plugins10 = tmp_path / "3rdparty-v10"
    plugins10.mkdir()
    plugins9 = tmp_path / "3rdparty-v9"
    plugins9.mkdir()
    monkeypatch.setenv("KICAD10_3RD_PARTY", str(plugins10))
    monkeypatch.setenv("KICAD9_3RD_PARTY", str(plugins9))
    assert find_plugins_dir() == plugins10


def test_find_plugins_dir_falls_through_kicad10_env_when_missing_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A set-but-non-existent ``KICAD10_3RD_PARTY`` raises before trying KICAD9."""
    monkeypatch.setenv("KICAD10_3RD_PARTY", str(tmp_path / "no-such-v10"))
    monkeypatch.delenv("KICAD9_3RD_PARTY", raising=False)
    with pytest.raises(KicadNotFoundError, match="KICAD10_3RD_PARTY"):
        find_plugins_dir()


def test_find_plugins_dir_falls_back_to_platform_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Platform defaults are tried in declared order (v10 before v9)."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    monkeypatch.delenv("KICAD10_3RD_PARTY", raising=False)
    monkeypatch.delenv("KICAD9_3RD_PARTY", raising=False)
    monkeypatch.setattr(
        kicad_install, "_PLATFORM_PLUGINS_DIR_CANDIDATES", (tmp_path / "nope", plugins)
    )
    assert find_plugins_dir() == plugins


def test_find_plugins_dir_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env, no platform default → ``KicadNotFoundError``."""
    monkeypatch.delenv("KICAD10_3RD_PARTY", raising=False)
    monkeypatch.delenv("KICAD9_3RD_PARTY", raising=False)
    monkeypatch.setattr(kicad_install, "_PLATFORM_PLUGINS_DIR_CANDIDATES", ())
    with pytest.raises(KicadNotFoundError):
        find_plugins_dir()


# ----------------------------------------------------------------------
# find_ibom_script
# ----------------------------------------------------------------------


def _fake_plugins_dir(tmp_path: Path) -> Path:
    """Build an iBOM-shaped fake plugin tree."""
    plugins = tmp_path / "3rdparty"
    target = (
        plugins
        / "plugins"
        / "org_openscopeproject_InteractiveHtmlBom"
        / "generate_interactive_bom.py"
    )
    target.parent.mkdir(parents=True)
    target.write_text("# fake iBOM script")
    return plugins


def test_find_ibom_script_resolves_under_plugins_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The locator returns the expected nested path under the plugins root."""
    plugins = _fake_plugins_dir(tmp_path)
    monkeypatch.setattr(kicad_install, "find_plugins_dir", lambda: plugins)
    script = find_ibom_script()
    assert script.exists()
    assert script.name == "generate_interactive_bom.py"


def test_find_ibom_script_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty plugins dir → :class:`KicadNotFoundError` with a clear hint."""
    plugins = tmp_path / "empty"
    plugins.mkdir()
    monkeypatch.setattr(kicad_install, "find_plugins_dir", lambda: plugins)
    with pytest.raises(KicadNotFoundError, match="org_openscopeproject_InteractiveHtmlBom"):
        find_ibom_script()


# ----------------------------------------------------------------------
# kicad_version
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ("9.0.4\n", (9, 0, 4)),
        ("KiCad 9.1.0\n", (9, 1, 0)),
        ("9.0.0-rc1\n", (9, 0, 0)),
        ("kicad-cli version 8.0.2\n", (8, 0, 2)),
    ],
)
def test_kicad_version_parses_canonical_outputs(
    stdout: str,
    expected: tuple[int, int, int],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """``kicad_version`` extracts ``(major, minor, patch)`` from stdout."""

    class _Result:
        def __init__(self, out: str) -> None:
            self.stdout = out
            self.returncode = 0

    def _fake_run(cmd: Iterable[str], **kwargs: object) -> _Result:
        return _Result(stdout)

    monkeypatch.setattr(kicad_install.subprocess, "run", _fake_run)
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    assert kicad_version(fake_cli) == expected


def test_kicad_version_raises_when_no_version_string(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unparsable stdout raises :class:`KicadNotFoundError`."""

    class _Result:
        stdout = "unexpected output\n"
        returncode = 0

    monkeypatch.setattr(kicad_install.subprocess, "run", lambda *_a, **_kw: _Result())
    fake_cli = tmp_path / "kicad-cli"
    fake_cli.write_text("")
    with pytest.raises(KicadNotFoundError, match="could not parse kicad-cli version"):
        kicad_version(fake_cli)


# ----------------------------------------------------------------------
# Platform default tables
# ----------------------------------------------------------------------


def test_platform_default_tables_are_non_empty_for_current_platform() -> None:
    """At least one default is registered for the host platform.

    Keeps the locator from regressing into a noop on a fresh checkout.
    """
    assert sys.platform in {"darwin", "linux", "win32"}
    assert len(kicad_install._PLATFORM_KICAD_CLI_CANDIDATES) >= 1
    assert len(kicad_install._PLATFORM_PLUGINS_DIR_CANDIDATES) >= 1


def test_plugins_dir_defaults_probe_kicad10_before_kicad9_on_macos_and_linux() -> None:
    """On macOS / Linux the default probe order must list a v10 path first.

    The fix that landed this test exists specifically because KiCad 10 plugin
    installs were being missed by the v9-only probe.  Reordering or removing
    the v10 path would silently regress us; pin the order here.
    """
    if sys.platform not in {"darwin", "linux"}:
        pytest.skip("order pin only applies to macOS / Linux defaults")
    paths = [str(p) for p in kicad_install._PLATFORM_PLUGINS_DIR_CANDIDATES]
    assert any("10.0" in p for p in paths)
    assert any("9.0" in p for p in paths)
    first_v10 = next(i for i, p in enumerate(paths) if "10.0" in p)
    first_v9 = next(i for i, p in enumerate(paths) if "9.0" in p)
    assert first_v10 < first_v9


def test_supported_kicad_majors_covers_9_and_10() -> None:
    """v1 supports KiCad 9.x and 10.x; the set is the canonical authority."""
    assert frozenset({9, 10}) == SUPPORTED_KICAD_MAJORS
