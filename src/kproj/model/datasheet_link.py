"""The :class:`DatasheetLink` value object (kproj#29).

Per the datasheet document library map (``plocher/jBOM#342``) and its
publish-mechanics resolution (``plocher/jBOM#350``), kproj never copies
datasheet PDFs into the site. Instead it deep-links a curated
``Datasheet Name`` (looked up live via ``jbom bom`` at publish time,
per ADR 0010 - not read from ``production/jbom.csv``, a stale
fab-oriented snapshot) to the public ``plocher/SPCoast-inventory``
library repo. See :mod:`kproj.common.datasheet_library` for the URL
constructors.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasheetLink:
    """A deep-link pair for one curated ``Datasheet Name``.

    Attributes:
        name: The curated, stable ``Datasheet Name`` (per
            SPCoast-inventory's Never-Rename invariant). Bare name,
            no ``.pdf`` suffix and no path.
        view_url: The GitHub blob URL for inline viewing
            (``.../blob/main/datasheets/<name>.pdf``).
        download_url: The raw-content URL for direct download
            (``raw.githubusercontent.com/.../main/datasheets/<name>.pdf``).
    """

    name: str
    view_url: str
    download_url: str
