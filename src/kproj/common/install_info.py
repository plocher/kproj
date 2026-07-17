"""Detection of kproj's own install provenance (release vs. editable).

kproj can be invoked from more than one installation on the same
machine at once: a released version resolved via ``pip``/``pipx``/
Homebrew from PyPI, or a dev/editable checkout (e.g. ``uv run kproj``
from a git clone). Both can write into the *same* shared external
state - the SPCoast site repo's git history, and the globally-installed
iBOM plugin's ``web/`` customization directory (see
``kproj.services.ibom_generator``) - with no visible indication of
which one produced a given publish. :func:`detect_install_info` and
:func:`format_provenance` exist so every provenance-surfacing site (the
``-v`` banner, the iBOM page, the site-repo commit message, and the
Hugo front-matter block) describes "which kproj, really" from one
shared detection pass and one shared string format, rather than four
independent - and potentially drifting - implementations.

Detection never raises: an inconclusive result falls back to
``"release"`` (the common case) rather than surfacing an exception
from what is purely a diagnostic nice-to-have.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import metadata
from typing import Literal

from .. import __version__ as KPROJ_VERSION

_DISTRIBUTION_NAME = "kproj"

InstallType = Literal["release", "editable"]
"""Closed taxonomy for :attr:`InstallInfo.install_type`."""


@dataclass(frozen=True)
class InstallInfo:
    """kproj's own version + install provenance for one running process.

    Attributes:
        install_type: ``"editable"`` for a PEP 660 editable/dev install
            (e.g. ``uv run kproj`` from a git checkout); ``"release"``
            for everything else, including the common case of a plain
            ``pip``/``pipx``/Homebrew install from PyPI.
        version: kproj's own ``__version__``.
        location: Best-effort filesystem path the running kproj was
            loaded from, for diagnostics. Empty string when
            undeterminable (e.g. a non-editable release install, where
            the distinction isn't diagnostically useful).
    """

    install_type: InstallType
    version: str
    location: str = ""


def detect_install_info() -> InstallInfo:
    """Return kproj's own version + install-type for this process.

    Inspects the installed ``kproj`` distribution's PEP 610
    ``direct_url.json`` metadata for an ``"editable": true`` marker -
    the standard signal PEP 660 editable installs write (including
    ``uv run`` / ``pip install -e`` / ``uv pip install -e``). Any
    lookup failure - the distribution metadata being absent, malformed,
    or unreadable - falls back to ``"release"`` rather than raising,
    since this is a best-effort diagnostic, not a control-flow-critical
    fact.

    Returns:
        A populated :class:`InstallInfo`.
    """
    try:
        dist = metadata.distribution(_DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return InstallInfo(install_type="release", version=KPROJ_VERSION)

    install_type: InstallType = "release"
    location = ""
    try:
        direct_url_text = dist.read_text("direct_url.json")
    except OSError:
        direct_url_text = None
    if direct_url_text:
        try:
            direct_url = json.loads(direct_url_text)
        except json.JSONDecodeError:
            direct_url = {}
        if isinstance(direct_url, dict):
            dir_info = direct_url.get("dir_info")
            if isinstance(dir_info, dict) and dir_info.get("editable") is True:
                install_type = "editable"
            url = direct_url.get("url")
            if isinstance(url, str) and url.startswith("file://"):
                location = url[len("file://") :]

    return InstallInfo(install_type=install_type, version=KPROJ_VERSION, location=location)


def format_provenance(info: InstallInfo, watermark: str = "") -> str:
    """Return a one-line human-readable provenance string.

    Used verbatim by every surfacing site (``-v`` banner, iBOM page
    comment/tooltip, site-repo commit trailer) so the wording never
    drifts between them.

    Args:
        info: The detected :class:`InstallInfo`.
        watermark: Optional free-text tag (``--watermark``), appended
            in brackets when non-empty.

    Returns:
        E.g. ``"kproj 0.10.5 (release)"`` or
        ``"kproj 0.dev0 (editable) [my-test-tag]"``.
    """
    text = f"kproj {info.version} ({info.install_type})"
    if watermark:
        text += f" [{watermark}]"
    return text
