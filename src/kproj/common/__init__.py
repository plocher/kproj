"""kproj common utilities (KiCad install discovery, subprocess runner).

Per ``docs/DESIGN.md`` § *Architecture overview*, this package contains
pure-function modules consumed by services via dependency injection.
It is not a domain layer of its own.
"""

from __future__ import annotations

from .kicad_install import (
    KicadNotFoundError,
    find_ibom_script,
    find_kicad_cli,
    find_plugins_dir,
    kicad_version,
)

__all__ = [
    "KicadNotFoundError",
    "find_ibom_script",
    "find_kicad_cli",
    "find_plugins_dir",
    "kicad_version",
]
