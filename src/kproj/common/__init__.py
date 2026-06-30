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
from .kicad_libraries import enumerate_libraries
from .subprocess_runner import (
    DEFAULT_GIT_TIMEOUT,
    DEFAULT_KICAD_TIMEOUT,
    SubprocessFailedError,
    SubprocessResult,
    SubprocessTimeoutError,
    run,
)

__all__ = [
    "DEFAULT_GIT_TIMEOUT",
    "DEFAULT_KICAD_TIMEOUT",
    "KicadNotFoundError",
    "SubprocessFailedError",
    "SubprocessResult",
    "SubprocessTimeoutError",
    "enumerate_libraries",
    "find_ibom_script",
    "find_kicad_cli",
    "find_plugins_dir",
    "kicad_version",
    "run",
]
