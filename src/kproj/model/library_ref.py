"""The :class:`LibraryRef` value object.

A single library the project references, tagged with where the
consumer would find it relative to the source.zip archive:

- ``internal`` - the library ships inside the source.zip via the
  ``Include`` rules (project-local ``*.pretty`` / ``*.kicad_sym``
  matched by ``fp-lib-table`` / ``sym-lib-table`` with a
  ``${KIPRJMOD}`` URI that does not escape the project root).
- ``external`` - the library lives outside the project; the
  consumer would need to clone / install it separately (lib-table
  URIs that are absolute, ``${KISYSMOD}``-prefixed, or
  ``${KIPRJMOD}/../...`` ones that escape the project root).
- ``ambiguous`` - the library is referenced by a ``(lib_id ...)``
  or ``(footprint ...)`` somewhere inside the design but has no
  matching ``fp-lib-table`` / ``sym-lib-table`` entry, so we can't
  authoritatively classify it.  Treat as install-required by
  default; matches the conservative safer-to-warn pattern kproj
  uses elsewhere (production-stale, comment9-missing).

The site-emission layer (kproj#4) groups + styles the three flavors
on the version page; the data layer just preserves the distinction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LibrarySource = Literal["internal", "external", "ambiguous"]
"""The three classifications a :class:`LibraryRef.source` may take."""


@dataclass(frozen=True, order=True)
class LibraryRef:
    """A single library the project references.

    Attributes:
        name: The library name as it appears in ``(lib_id "<lib>:...")``
            references and in ``fp-lib-table`` / ``sym-lib-table``
            ``(lib (name ...))`` entries.
        source: One of ``"internal"``, ``"external"``, ``"ambiguous"``
            per :data:`LibrarySource`.  See module docstring for the
            classification rules.
    """

    name: str
    source: LibrarySource
