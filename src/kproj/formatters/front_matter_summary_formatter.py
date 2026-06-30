"""The :class:`FrontMatterSummaryFormatter`.

Produces the authoritative YAML front-matter for
``_versions/<P>/<R>.md`` per ``docs/DESIGN.md`` § *Front-matter shape*.

The :meth:`render` method takes a fully assembled :class:`Publication`
and returns a YAML string (without the ``---`` delimiters) ready for
embedding in a Jekyll markdown file.

The ``libraries:`` section groups libraries into three buckets
(``internal`` / ``external`` / ``ambiguous``) per the
:data:`LibrarySource` taxonomy from
``docs/DESIGN.md`` § *Library enumeration*.

Design note: key order in the emitted YAML follows the DESIGN
§ *Front-matter shape* example; ``sort_keys=False`` is used in
:func:`yaml.dump` to preserve it.  Jekyll reads front-matter as an
ordered map anyway, so order is cosmetic but keeps diffs reviewable.
"""

from __future__ import annotations

from collections import defaultdict

import yaml

from ..model.analysis_info import AnalysisInfo
from ..model.project_info import Status
from ..model.publication import Publication
from ..model.severity import Severity

# Statuses whose on-site pages are "obsolete" (hidden / archived).
_OBSOLETE_STATUSES: frozenset[Status] = frozenset(
    {Status.RETIRED, Status.REPLACED_BY}
)


class FrontMatterSummaryFormatter:
    """Renders the authoritative YAML front-matter for a version page.

    The :meth:`render` method consumes a fully assembled
    :class:`~kproj.model.publication.Publication` and returns a YAML
    string containing every field described in
    ``docs/DESIGN.md`` § *Front-matter shape*, including the
    ``libraries:`` section introduced by kproj#4.
    """

    def __init__(self) -> None:
        """Construct a front-matter summary formatter."""

    def render(self, publication: Publication) -> str:
        """Render the full YAML front-matter for *publication*.

        Args:
            publication: The site-emission-ready publication bundle.

        Returns:
            A YAML string (no ``---`` fences) ready to embed between
            the opening and closing ``---`` delimiters of a Jekyll
            markdown file.
        """
        pi = publication.project_info
        ai = publication.analysis_info
        P = pi.project
        R = pi.board_rev
        PR = f"{P}-{R}"

        iskicad: object = "obsolete" if pi.status in _OBSOLETE_STATUSES else True

        data: dict[str, object] = {
            "iskicad": iskicad,
            "layout": "eagle",
            "sidebar": "spcoast_sidebar",
            "project": P,
            "title": R,
            "date": pi.date,
            "design_rev": pi.design_rev,
            "board_rev": R,
            "designer": pi.designer,
            "tagline": pi.tagline,
            "overview": pi.overview,
            "company": pi.company,
            "tags": list(pi.tags),
            "status": pi.status.value,
            "publish": True,
            "image_path": f"/versions/{P}/{R}/{PR}.thumbnail.png",
        }

        # Fabrication fields — only when set.
        if pi.fabricated:
            data["fabricated"] = pi.fab_date or pi.date
        if pi.fab_date:
            data["fab_date"] = pi.fab_date

        # Images list.
        data["images"] = [
            {"image_path": ref.path, "title": ref.title}
            for ref in publication.images
        ]

        # Artifacts list (all with type=download).
        data["artifacts"] = [
            {
                "path": ref.path,
                "tag": ref.tag,
                "type": "download",
                "post": ref.post,
            }
            for ref in publication.artifacts
        ]

        # Audit / DRC / ERC count summaries.
        data["audit"] = self.render_audit(ai)
        data["drc"] = _count_design_findings(ai, kind="drc")
        data["erc"] = _count_design_findings(ai, kind="erc")

        # Libraries — three-bucket YAML shape (kproj#4 wave-3).
        libs_yaml = _render_libraries(publication)
        if libs_yaml is not None:
            data["libraries"] = libs_yaml

        return yaml.dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)

    def render_audit(self, analysis_info: AnalysisInfo) -> dict[str, int]:
        """Render the ``audit:`` count summary as a plain dict.

        Args:
            analysis_info: The merged findings collection.

        Returns:
            A dict with ``"errors"`` and ``"warnings"`` integer keys
            counting the metadata-audit findings.
        """
        return {
            "errors": analysis_info.count(Severity.ERROR),
            "warnings": analysis_info.count(Severity.WARNING),
        }


# ----- module-level helpers -----


def _count_design_findings(ai: AnalysisInfo, *, kind: str) -> dict[str, int]:
    """Return error / warning / exclusion counts for DRC or ERC findings.

    v1 keeps a single merged :class:`AnalysisInfo`; all design findings
    (errors + warnings + exclusions) from both DRC and ERC are merged.
    The ``kind`` parameter is retained for forward-compatibility once
    wave-3 splits them, but in v1 we report the merged counts for both.

    Args:
        ai: The merged analysis findings.
        kind: ``"drc"`` or ``"erc"`` (currently both see the same data).

    Returns:
        A dict with ``"errors"``, ``"warnings"``, and ``"exclusions"``
        integer keys.
    """
    del kind  # reserved; used for forward-compatibility in v1.1+
    return {
        "errors": ai.count(Severity.ERROR),
        "warnings": ai.count(Severity.WARNING),
        "exclusions": ai.count(Severity.EXCLUSION),
    }


def _render_libraries(
    publication: Publication,
) -> dict[str, list[str]] | None:
    """Render the ``libraries:`` YAML shape from publication.libraries.

    Returns ``None`` when the publication has no libraries (the
    ``libraries:`` key is omitted from the front-matter rather than
    emitting an empty block).

    The three-bucket shape chosen per kproj#4 wave-3::

        libraries:
          internal:
            - LibA
          external:
            - LibB
          ambiguous:
            - LibC

    Within each bucket, names are sorted alphabetically for stable diffs.

    Args:
        publication: The assembled :class:`Publication`.

    Returns:
        A dict mapping ``"internal"`` / ``"external"`` / ``"ambiguous"``
        each to a sorted list of library names, or ``None`` when empty.
    """
    if not publication.libraries:
        return None

    buckets: dict[str, list[str]] = defaultdict(list)
    for lib in publication.libraries:
        buckets[lib.source].append(lib.name)

    return {
        "internal": sorted(buckets.get("internal", [])),
        "external": sorted(buckets.get("external", [])),
        "ambiguous": sorted(buckets.get("ambiguous", [])),
    }
