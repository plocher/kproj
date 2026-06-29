"""KiCad install discovery (per ``docs/adr/0009-kicad-install-locator.md``).

Plain-function utility module \u2014 not a Producer-Pattern service. Each
function either returns a :class:`pathlib.Path` to an existing
artifact or raises :class:`KicadNotFoundError`.

Per ADR 0009 the probe order is:

1. Explicit env var override (``KPROJ_KICAD_CLI`` /
   ``KICAD9_3RD_PARTY``); existence-checked before returning.
2. Platform-specific defaults (macOS / Linux / Windows) declared in
   :data:`_PLATFORM_KICAD_CLI_CANDIDATES` /
   :data:`_PLATFORM_PLUGINS_DIR_CANDIDATES`.
3. PATH lookup via :func:`shutil.which` (for ``kicad-cli`` only).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

_KICAD_CLI_ENV_VAR = "KPROJ_KICAD_CLI"
_PLUGINS_DIR_ENV_VAR = "KICAD9_3RD_PARTY"
_IBOM_PLUGIN_DIR = "org_openscopeproject_InteractiveHtmlBom"
_IBOM_SCRIPT_NAME = "generate_interactive_bom.py"
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)")


class KicadNotFoundError(RuntimeError):
    """Raised when a required KiCad-install artifact cannot be located.

    Carries a human-readable message intended for direct stderr
    surfacing (the workflow re-raises after converting to an
    ``outcome="failed"``, ``exit_code=2`` :class:`PublishResult`).
    """


def _candidates_for_kicad_cli() -> tuple[Path, ...]:
    """Return the per-platform default ``kicad-cli`` locations."""
    if sys.platform == "darwin":
        return (Path("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"),)
    if sys.platform == "linux":
        return (Path("/usr/bin/kicad-cli"), Path("/usr/local/bin/kicad-cli"))
    if sys.platform == "win32":
        return (
            Path(r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe"),
            Path(r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe"),
        )
    return ()


def _candidates_for_plugins_dir() -> tuple[Path, ...]:
    """Return the per-platform default ``KICAD9_3RD_PARTY`` locations."""
    home = Path.home()
    if sys.platform == "darwin":
        return (home / "Documents/KiCad/9.0/3rdparty",)
    if sys.platform == "linux":
        return (home / ".local/share/kicad/9.0/3rdparty",)
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return (Path(appdata) / "kicad" / "9.0" / "3rdparty",)
        return ()
    return ()


# Module-level tuples so tests can monkeypatch isolated probes.
_PLATFORM_KICAD_CLI_CANDIDATES: tuple[Path, ...] = _candidates_for_kicad_cli()
"""Per-platform default ``kicad-cli`` paths; tried in declared order."""

_PLATFORM_PLUGINS_DIR_CANDIDATES: tuple[Path, ...] = _candidates_for_plugins_dir()
"""Per-platform default plugins-root paths; tried in declared order."""


def find_kicad_cli() -> Path:
    """Locate the ``kicad-cli`` executable.

    Returns:
        Absolute :class:`pathlib.Path` to an existing executable.

    Raises:
        KicadNotFoundError: When no probe resolves to an existing path.
    """
    explicit = os.environ.get(_KICAD_CLI_ENV_VAR)
    if explicit:
        candidate = Path(explicit)
        if candidate.exists():
            return candidate
        raise KicadNotFoundError(f"{_KICAD_CLI_ENV_VAR}={explicit!r} but that path does not exist.")

    for candidate in _PLATFORM_KICAD_CLI_CANDIDATES:
        if candidate.exists():
            return candidate

    located = shutil.which("kicad-cli")
    if located:
        return Path(located)

    raise KicadNotFoundError(
        "kicad-cli executable not found. Set "
        f"{_KICAD_CLI_ENV_VAR} or install KiCad 9.x at the platform default location."
    )


def find_plugins_dir() -> Path:
    """Locate the KiCad 9 plugins (``KICAD9_3RD_PARTY``) root.

    Returns:
        Absolute :class:`pathlib.Path` to an existing directory.

    Raises:
        KicadNotFoundError: When no probe resolves to an existing directory.
    """
    explicit = os.environ.get(_PLUGINS_DIR_ENV_VAR)
    if explicit:
        candidate = Path(explicit)
        if candidate.is_dir():
            return candidate
        raise KicadNotFoundError(
            f"{_PLUGINS_DIR_ENV_VAR}={explicit!r} but that directory does not exist."
        )

    for candidate in _PLATFORM_PLUGINS_DIR_CANDIDATES:
        if candidate.is_dir():
            return candidate

    raise KicadNotFoundError(
        "KiCad 9 plugins root not found. Set "
        f"{_PLUGINS_DIR_ENV_VAR} or install KiCad 9.x at the platform default location."
    )


def find_ibom_script() -> Path:
    """Locate the InteractiveHtmlBom generator script.

    Returns:
        Absolute :class:`pathlib.Path` to ``generate_interactive_bom.py``.

    Raises:
        KicadNotFoundError: When the plugins root cannot be located, or
            when the iBOM script does not exist inside it.
    """
    plugins = find_plugins_dir()
    script = plugins / "plugins" / _IBOM_PLUGIN_DIR / _IBOM_SCRIPT_NAME
    if not script.exists():
        raise KicadNotFoundError(
            "kproj: iBOM plugin not installed at "
            f"{script}. Install via KiCad's Plugin and Content Manager: "
            f"{_IBOM_PLUGIN_DIR}."
        )
    return script


def kicad_version(kicad_cli: Path) -> tuple[int, int, int]:
    """Return ``(major, minor, patch)`` from ``<kicad_cli> --version``.

    Args:
        kicad_cli: The discovered ``kicad-cli`` executable.

    Returns:
        Tuple ``(major, minor, patch)`` of integers parsed from the
        first ``N.N.N`` token in the executable's ``--version`` stdout.

    Raises:
        KicadNotFoundError: When the executable produces no parseable
            version string. The full stdout is included in the message
            for diagnostics.
    """
    completed = subprocess.run(
        [str(kicad_cli), "--version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    match = _VERSION_RE.search(completed.stdout or "")
    if not match:
        raise KicadNotFoundError(
            f"could not parse kicad-cli version from output: {(completed.stdout or '').strip()!r}"
        )
    major, minor, patch = (int(g) for g in match.groups())
    return major, minor, patch
