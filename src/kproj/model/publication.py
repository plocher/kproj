"""The :class:`Publication` value object + its supporting :class:`AssetRef`.

Per ``docs/GLOSSARY.md`` § *Publication*, this is the bundle ready for
site emission. It carries the project metadata, audit findings, asset
references, and pre-rendered Markdown body that ``SitePublisher`` consumes.

The dataclass is pure data - no I/O, no Jekyll-specific YAML rendering
(that lives inside ``SitePublisher``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .analysis_info import AnalysisInfo
from .library_ref import LibraryRef
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
        readme_md: The project's ``README.md`` content.  Written as the
            body of the project section index
            ``<versions_dir>/<P>/_index.md`` (one per project, rewritten
            each publish).  Also used in new-release detection: if the
            on-disk section-index body differs, a ``"refresh"`` outcome
            is triggered.  Defaults to an empty string when the project
            has no README.
        published_at: The kproj execution / publish time, emitted as the
            version page's Hugo-reserved ``date`` front-matter field
            (Hugo requires ``date`` to be a parseable date; the
            title-block ``YYYY.MM`` value is emitted separately as
            ``issue_date``). Empty string omits ``date`` (used by unit
            fixtures that don't care about the publish time). Treated as
            a **volatile** key in new-release detection so a plain
            re-run stays a no-op.
        datasheets: Project-global datasheet PDF filenames discovered in
            the project directory (per
            :func:`kproj.common.project_docs.discover_datasheets`). Listed
            by name on the project section index. Empty when none.
        description: Optional project-global ``DESCRIPTION`` prose (per
            :func:`kproj.common.project_docs.read_description`), rendered
            on the project section index alongside the README. Empty
            when the project has no DESCRIPTION file.
        images: Asset references emitted into the front-matter
            ``images:`` list (renders, schematic SVG).
        artifacts: Asset references emitted into the front-matter
            ``artifacts:`` list (schematic PDF, iBOM HTML, STEP,
            fab.zip, source.zip).
        libraries: Stable-sorted tuple of :class:`LibraryRef` entries
            naming every library the project references, each tagged
            with its ``source`` classification (``internal`` /
            ``external`` / ``ambiguous``) per
            :func:`kproj.common.kicad_libraries.enumerate_libraries`.
            The site-emission layer renders these on the version page;
            see ``docs/DESIGN.md`` § *Library enumeration*. Rendering
            itself is tracked by kproj#4.
    """

    project_info: ProjectInfo
    analysis_info: AnalysisInfo
    body_md: str
    readme_md: str = ""
    published_at: str = ""
    datasheets: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    images: tuple[AssetRef, ...] = field(default_factory=tuple)
    artifacts: tuple[AssetRef, ...] = field(default_factory=tuple)
    libraries: tuple[LibraryRef, ...] = field(default_factory=tuple)
