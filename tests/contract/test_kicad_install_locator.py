"""Contract test for :mod:`kproj.common.kicad_install`.

Validates that the locator returns real, existing paths against the
local KiCad install. Skipped automatically on machines where KiCad is
not installed (CI / non-developer machines), per
``docs/DESIGN.md`` \u00a7 *Contract tests*.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kproj.common.kicad_install import (
    KicadNotFoundError,
    find_ibom_script,
    find_kicad_cli,
    find_plugins_dir,
    kicad_version,
)


def _kicad_cli_available() -> bool:
    """Return ``True`` iff :func:`find_kicad_cli` finds a real executable."""
    try:
        find_kicad_cli()
    except KicadNotFoundError:
        return False
    return True


def _plugins_dir_available() -> bool:
    """Return ``True`` iff :func:`find_plugins_dir` resolves locally."""
    try:
        find_plugins_dir()
    except KicadNotFoundError:
        return False
    return True


def _ibom_available() -> bool:
    """Return ``True`` iff :func:`find_ibom_script` resolves locally."""
    try:
        find_ibom_script()
    except KicadNotFoundError:
        return False
    return True


pytestmark = pytest.mark.contract


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_find_kicad_cli_returns_existing_executable() -> None:
    """The discovered ``kicad-cli`` is an existing file on disk."""
    binary = find_kicad_cli()
    assert isinstance(binary, Path)
    assert binary.exists()


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_kicad_version_returns_sane_major() -> None:
    """``kicad_version`` returns a plausible ``(major, minor, patch)`` tuple.

    v1 supports the 9.x line per ADR 0009; this test asserts only that
    the parser produces a sane tuple, not which major version is
    installed (developer machines may carry 8.x or 9.x during
    transitions).
    """
    binary = find_kicad_cli()
    major, minor, patch = kicad_version(binary)
    assert major >= 7  # KiCad ≥ 7 is the floor for kicad-cli existence
    assert minor >= 0
    assert patch >= 0


@pytest.mark.skipif(not _plugins_dir_available(), reason="KiCad 9 plugins dir not present locally")
def test_find_plugins_dir_returns_existing_directory() -> None:
    """The discovered plugins root exists and is a directory."""
    plugins = find_plugins_dir()
    assert plugins.is_dir()


@pytest.mark.skipif(not _ibom_available(), reason="iBOM plugin not installed locally")
def test_find_ibom_script_returns_existing_file() -> None:
    """The discovered iBOM script exists on disk."""
    script = find_ibom_script()
    assert script.is_file()
    assert script.name == "generate_interactive_bom.py"
