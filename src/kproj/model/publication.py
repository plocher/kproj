"""The :class:`Publication` value object + its supporting :class:`AssetRef`.

Per ``docs/GLOSSARY.md`` § *Publication*, this is the bundle ready for
site emission. It carries the project metadata, audit findings, asset
references, and pre-rendered Markdown body that ``SitePublisher`` consumes.

The dataclass is pure data — no I/O, no Jekyll-specific YAML rendering
(that lives inside ``SitePublisher``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .analysis_info import AnalysisInfo
from .project_info import ProjectInfo


@dataclass(frozen=True)
class AssetRef:
    """A reference to a per-version asset emitted into the site repo.

    Mirrors the entries kproj writes into the Jekyll front-matter
    ``images:`` and ``artifacts:`` lists.

    Attributes:
        path: Site-absolute path (e.g. ``/versions/<P>/<R>/<file>``).
        tag: Role identifier consumed by ``eagle.html`` /
            ``electronics.html`` (e.g. ``"render-top"``,
            ``"schematic-pdf"``).
        title: Optional human-readable title (used in ``images[].title``).
        post: Optional download-link caption (used in
            ``artifacts[].post``).
    """

    path: str
    tag: str
    title: str = ""
    post: str = ""


@dataclass(frozen=True)
class Publication:
    """A site-emission-ready bundle for one ``(project, board_rev)`` pair.

    Attributes:
        project_info: The point-in-time facts for the project.
        analysis_info: Audit + DRC/ERC findings.
        body_md: The pre-rendered Markdown body (audit + DRC/ERC
            tables) written below the YAML front-matter terminator.
        images: Asset references emitted into the front-matter
            ``images:`` list (renders, schematic SVG).
        artifacts: Asset references emitted into the front-matter
            ``artifacts:`` list (schematic PDF, iBOM HTML, STEP,
            fab.zip, source.zip).
    """

    project_info: ProjectInfo
    analysis_info: AnalysisInfo
    body_md: str
    images: tuple[AssetRef, ...] = field(default_factory=tuple)
    artifacts: tuple[AssetRef, ...] = field(default_factory=tuple)
