"""kproj configuration layer.

Implements the four-tier precedence from ``docs/DESIGN.md`` §
*Configuration layer* (CLI flag > ``KPROJ_*`` env var > ``~/.kproj.yaml``
> hardcoded default), exposed via ``kproj --help``'s epilog (kproj#37):
1.  :class:`ConfigOverrides` field (set by a CLI flag)
2. Environment variable (``KPROJ_SITE_REPO`` / ``KPROJ_NO_PUSH`` /
   ``KPROJ_KICAD_CLI`` / ``KPROJ_INVENTORY`` / ``KPROJ_DATASHEET_LIBRARY`` /
   ``KPROJ_DATASHEET_REPO`` / ``KPROJ_IBOM_EXTRA_FIELDS`` /
   ``KPROJ_FABRICATOR``)
3. ``~/.kproj.yaml`` key (``site_repo`` / ``no_push`` / ``kicad_cli`` /
   ``inventory`` / ``datasheet_library`` / ``datasheet_repo`` /
   ``ibom_extra_fields`` / ``fabricator``)
4. Hardcoded fallback (:data:`DEFAULT_SITE_REPO`, ``False``, ``None``,
   ``None``, :data:`DEFAULT_DATASHEET_LIBRARY`, :data:`DEFAULT_DATASHEET_REPO`,
   :data:`DEFAULT_IBOM_EXTRA_FIELDS`, :data:`DEFAULT_FABRICATOR`)

``inventory`` (kproj#29) intentionally has **no** hardcoded-path
fallback, unlike ``site_repo``: per the datasheet document library's
publish-mechanics resolution (``plocher/jBOM#350``), hardcoded
user-machine paths are the antipattern that effort roots out. ``None``
means kproj never invokes ``jbom bom`` at all (kproj#36 owner ruling;
see :mod:`kproj.common.datasheet_library`) - an acceptable,
advisory-free degraded state, never a publish blocker. When neither
``~/.kproj.yaml`` nor ``--inventory``/``KPROJ_INVENTORY`` is set, the
CLI emits a one-time INFO-level discoverability hint (kproj#37).

Per ADR 0006, this module never imports ``argparse``. The CLI builds a
:class:`ConfigOverrides` from its parsed namespace and calls
:func:`load_config`.

The module also owns the :class:`SiteProfile` abstraction — the seam that
keeps kproj's site-repo layout (where per-version markdown files land,
what front-matter shape gets emitted) decoupled from a specific site
backend.  Two built-in profiles ship in v1:

* :data:`GENERIC_SITE_PROFILE` — the abstract test-anchor.  Values are
  intentionally backend-neutral (``versions/``, no explicit layout
  field) so Behave scenarios and unit-test fixtures can validate
  contract behaviour without pinning to any real backend.  It is
  **not** intended for deployment against a live site; real backends
  ship their own concrete profile.
* :data:`HUGO_SITE_PROFILE` — the concrete Hugo backend.  Fills in the
  structural bones a Hugo GitHub Pages deployment expects
  (``content/versions/``, ``layout:`` field omitted so Hugo picks by
  section).  This is what :func:`load_config` selects for production
  callers today.

Future named profiles (Jekyll, Astro, custom) plug into the same
abstraction via a future ``--profile`` / ``--type`` / ``--theme`` CLI
flag; the ``--site-repo`` flag remains reserved for the on-disk repo
path.  Analogue to jBOM's ADR 0008 pattern: ``generic`` is the
no-flag test fallback; named profiles fill in backend-specific values.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_SITE_REPO: Path = Path.home() / "Dropbox" / "workspace" / "SPCoast.github.io"
"""Canonical filesystem default for the SPCoast site-repo checkout.

This is the **single source of truth** for the default ``site_repo`` path
(the hardcoded fallback per ADR 0007). Other code MUST NOT re-declare the
literal path; import this constant instead. Docs, templates, ADRs, and
plan-level references use the generic ``$SITE_REPO`` placeholder and cite
this constant when the actual filesystem location is needed."""

DEFAULT_NO_PUSH: bool = False
"""Hardcoded fallback for ``--no-push`` (off by default)."""

DEFAULT_DATASHEET_LIBRARY: Path = Path.home() / "Dropbox" / "KiCad" / "SPCoast-inventory"
"""SPCoast convention for the local datasheet-library clone used by the
advisory publish guard (:func:`kproj.common.datasheet_library.check_datasheet_links`).
Unlike ``inventory``, this keeps a hardcoded fallback (ADR 0007 unchanged
conventions; kproj#37 only adds override tiers + discoverability)."""

DEFAULT_DATASHEET_REPO: str = "plocher/SPCoast-inventory"
"""The public datasheet-library repo's ``<owner>/<repo>`` slug that
published deep-links point at (:func:`kproj.common.datasheet_library.build_datasheet_link`).
Hardcoded fallback (ADR 0007 unchanged conventions)."""

DEFAULT_IBOM_EXTRA_FIELDS: tuple[str, ...] = (
    "MPN",
    "Manufacturer",
    "Fabricator Part Number",
    "Datasheet",
    "Datasheet Name",
    "Description",
)
"""Default iBOM extra fields surfaced by kproj (kproj#48).

Ordered for assembly use: supply-chain identifiers first, then
datasheet/documentation and descriptive context.
"""

DEFAULT_FABRICATOR: str = "jlc"
"""Default jBOM fabricator mode for inventory lookup normalization."""

_SUPPORTED_FABRICATORS: frozenset[str] = frozenset({"generic", "jlc", "pcbway", "seeed"})
"""Fabricator values accepted by jBOM's ``--fabricator`` option."""


# ---- SiteProfile abstraction (mirrors jBOM's ADR 0008 GENERIC pattern) ----


@dataclass(frozen=True)
class SiteProfile:
    """Site-repo layout profile — the seam between kproj and the site backend.

    Concrete backends (Hugo, Jekyll, Astro, ...) differ in:

    * Where per-version markdown files land (``content/versions/`` for
      Hugo, ``_versions/`` for Jekyll, etc.).
    * Where per-version asset files land (``assets_dir``).
    * Whether an explicit ``layout:`` front-matter field is required
      (Jekyll's ``layout: eagle`` selector; Hugo picks layout by
      section and typically omits the field).

    The per-project overview is emitted as the project section's index
    page — ``<versions_dir>/<Project>/_index.md`` — so a project is a
    Hugo section and each version a page in it (see
    :meth:`project_index_path`). There is one index per project,
    rewritten on each publish to reflect the most-recent-publish
    project-global state; kproj no longer writes a separate
    ``pages/<Project>.md``.

    A :class:`SiteProfile` captures these knobs so :class:`SitePublisher`,
    :class:`FrontMatterSummaryFormatter`, and every other backend-facing
    consumer reads from a profile field instead of a hard-coded string.
    Behave scenarios and unit-test fixtures reference
    :data:`GENERIC_SITE_PROFILE` (the abstract test anchor); real
    deployments select a named backend profile such as
    :data:`HUGO_SITE_PROFILE`.

    Attributes:
        name: Short identifier (used for logging and future
            ``--profile <name>`` CLI selection).
        versions_dir: Subpath, relative to the site-repo root, where the
            per-version markdown files (``<Revision>.md``) and the
            per-project section index (``<Project>/_index.md``) are
            written — one directory per project below this dir.
        assets_dir: Subpath, relative to the site-repo root, where the
            per-version **asset files** (renders, STEP, SVG/PDF, iBOM,
            fab/source zips) are physically written. This is distinct
            from the public asset URL, which is always
            ``/versions/<Project>/<Revision>/<file>``: a backend whose
            web root differs from its repo root (Hugo serves ``static/``
            at ``/``) sets ``assets_dir`` so the physical file resolves
            at that fixed URL. Kept a **required** field (no default) so
            every backend must state where its served assets live —
            an implicit fallback is exactly what let Hugo assets land
            outside ``static/`` and 404 (kproj#10 Phase G finding).
        layout_field: Optional value for the ``layout:`` front-matter
            field. ``None`` means the field is omitted from the emitted
            YAML entirely. Non-``None`` means emit ``layout: <value>``
            (Jekyll-compatible).
    """

    name: str
    versions_dir: str
    assets_dir: str
    layout_field: str | None = None

    def version_page_path(self, site_repo: Path, project: str, board_rev: str) -> Path:
        """Return the on-disk path of a version page (``<P>/<R>.md``)."""
        return site_repo / self.versions_dir / project / f"{board_rev}.md"

    def project_index_path(self, site_repo: Path, project: str) -> Path:
        """Return the on-disk path of the project section index.

        The per-project overview lives at
        ``<versions_dir>/<Project>/_index.md`` so that a project is a
        Hugo section (identity = index page) with its versions as pages.
        One index per project, rewritten each publish.
        """
        return site_repo / self.versions_dir / project / "_index.md"

    def asset_disk_path(self, site_repo: Path, public_asset_path: str) -> Path:
        """Map a public asset URL to its on-disk location under this profile.

        Release assets are referenced in front-matter by their public
        site URL (always ``/versions/<Project>/<Revision>/<file>``), but
        the physical file may live elsewhere so the backend's web server
        serves it at that URL. Hugo, for example, serves ``static/`` at
        the site root, so its assets live under ``static/versions/`` yet
        must resolve at ``/versions/``. This swaps the leading public
        URL segment (the served mount point) for this profile's
        :attr:`assets_dir`.

        Args:
            site_repo: Local site-repo checkout root.
            public_asset_path: The public asset URL (e.g.
                ``/versions/<P>/<R>/<file>``) as stored in
                :attr:`~kproj.model.publication.AssetRef.path`.

        Returns:
            The absolute on-disk path where that asset is written / read.
        """
        rel = public_asset_path.lstrip("/")
        # Drop the leading public mount segment (e.g. ``versions``) and
        # re-root the remainder under this profile's physical assets_dir.
        _, _, tail = rel.partition("/")
        return site_repo / self.assets_dir / tail


GENERIC_SITE_PROFILE: SiteProfile = SiteProfile(
    name="generic",
    versions_dir="versions",
    assets_dir="versions",
    layout_field=None,
)
"""The abstract, backend-neutral **test-anchor** site profile.

All values are intentionally generic — no ``content/`` prefix (Hugo),
no ``_`` prefix (Jekyll), no ``layout:`` field.  Behave scenarios and
unit-test fixtures reference this constant; not intended for
deployment against a live site (see ``docs/DESIGN.md`` § *SiteProfile
abstraction*).
"""


HUGO_SITE_PROFILE: SiteProfile = SiteProfile(
    name="hugo",
    versions_dir="content/versions",
    assets_dir="static/versions",
    layout_field=None,
)
"""The concrete Hugo backend site profile.

Fills in the structural bones a Hugo GitHub Pages deployment expects:

* ``content/versions/<Project>/<Revision>.md`` — per-version markdown
  lives under Hugo's ``content/`` root, one directory per project.
* ``content/versions/<Project>/_index.md`` — the project section index
  (project-global overview); one per project, rewritten each publish.
* No ``layout:`` field — Hugo picks the layout by section (files under
  ``content/versions/`` render via ``layouts/versions/single.html`` if
  present, else ``layouts/_default/single.html``).

Selected by :func:`load_config` as kproj v1's production default; the
SPCoast site at :data:`DEFAULT_SITE_REPO` is a Hugo site.
"""

_TRUE_TOKENS: frozenset[str] = frozenset({"1", "true", "yes", "on", "y", "t"})


def _parse_bool(value: str) -> bool:
    """Parse a YAML/env boolean-shaped string.

    Args:
        value: Raw string. Stripped + lower-cased before comparison.

    Returns:
        ``True`` iff ``value`` is one of the canonical truthy tokens
        (``1``, ``true``, ``yes``, ``on``, ``y``, ``t``). Empty / any
        other value → ``False``.
    """
    return value.strip().lower() in _TRUE_TOKENS


def _normalize_ibom_extra_fields(value: str | Sequence[str]) -> tuple[str, ...]:
    """Normalize iBOM extra-field configuration input to an ordered tuple.

    Args:
        value: Either a comma-separated string (CLI/env style) or a
            sequence of field labels (yaml list style).

    Returns:
        A de-duplicated tuple preserving first-seen order.

    Raises:
        ValueError: If *value* is not a supported shape.
    """
    raw_fields: list[str]
    if isinstance(value, str):
        raw_fields = value.split(",")
    elif isinstance(value, Sequence):
        raw_fields = [str(item) for item in value]
    else:
        raise ValueError(
            "ibom_extra_fields must be a comma-separated string or a sequence of strings"
        )

    ordered: list[str] = []
    seen: set[str] = set()
    for raw_field in raw_fields:
        field = raw_field.strip()
        if not field:
            continue
        folded = field.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        ordered.append(field)
    return tuple(ordered)


def _normalize_fabricator(value: str) -> str:
    """Normalize and validate a configured jBOM fabricator mode."""
    normalized = value.strip().lower()
    if normalized not in _SUPPORTED_FABRICATORS:
        allowed = ", ".join(sorted(_SUPPORTED_FABRICATORS))
        raise ValueError(f"fabricator must be one of: {allowed}")
    return normalized


@dataclass(frozen=True)
class ConfigOverrides:
    """CLI-derived overrides built inside :mod:`kproj.cli`.

    ``None`` on any field means the flag was not provided by the user;
    precedence falls through to env / yaml / default. Setting a field
    to a non-``None`` value pins it as the highest-precedence source.

    Attributes:
        site_repo: ``--site-repo`` override.
        no_push: ``--no-push`` override.
        kicad_cli: Reserved for future ``--kicad-cli`` CLI flag; not
            exposed in v1 (env + yaml + locator probe suffice).
        inventory: ``--inventory`` override (kproj#37). ``None`` means
            the flag was not provided by the user; when unset at every
            tier, kproj skips the ``jbom bom`` invocation entirely
            (kproj#36) rather than omitting just the ``--inventory``
            flag.
        datasheet_library: ``--datasheet-library`` override (kproj#37):
            the local datasheet-library clone path used by the
            advisory publish guard.
        datasheet_repo: ``--datasheet-repo`` override (kproj#37): the
            public ``<owner>/<repo>`` slug published deep-links point at.
        ibom_extra_fields: ``--ibom-extra-fields`` override (kproj#48).
            Accepts either a comma-separated string or a sequence of
            field labels.
        fabricator: ``--fabricator`` override selecting which jBOM
            fabricator profile to use for lookup output.
    """

    site_repo: Path | None = None
    no_push: bool | None = None
    kicad_cli: Path | None = None
    inventory: Path | None = None
    datasheet_library: Path | None = None
    datasheet_repo: str | None = None
    ibom_extra_fields: str | Sequence[str] | None = None
    fabricator: str | None = None


@dataclass(frozen=True)
class KprojConfig:
    """The fully resolved runtime configuration.

    Attributes:
        site_repo: Local site-repo checkout where kproj will write.
        no_push: When ``True``, ``git push`` is skipped after commits.
        kicad_cli: Optional explicit ``kicad_cli`` executable; ``None``
            triggers :func:`kproj.common.kicad_install.find_kicad_cli`
            discovery in pre-flight.
        site_profile: :class:`SiteProfile` selecting the site-repo
            layout and front-matter shape.
        inventory: Optional inventory CSV path forwarded to ``jbom
            bom --inventory`` for datasheet-name lookup (kproj#29).
            ``None`` skips the ``jbom bom`` invocation entirely
            (kproj#36); no hardcoded fallback (see :class:`ConfigOverrides`).
        datasheet_library: Local datasheet-library clone path for the
            advisory publish guard (kproj#37). Defaults to
            :data:`DEFAULT_DATASHEET_LIBRARY` (SPCoast convention,
            unchanged) when unset at every tier.
        datasheet_repo: Public ``<owner>/<repo>`` slug published
            deep-links point at (kproj#37). Defaults to
            :data:`DEFAULT_DATASHEET_REPO` (SPCoast convention,
            unchanged) when unset at every tier.
        ibom_extra_fields: Ordered iBOM extra fields surfaced during
            publish (kproj#48). Resolved from CLI/env/yaml precedence,
            defaults to :data:`DEFAULT_IBOM_EXTRA_FIELDS`.
        fabricator: Resolved jBOM fabricator mode forwarded to lookup
            invocations as ``--fabricator``. Defaults to
            :data:`DEFAULT_FABRICATOR`.
    """

    site_repo: Path
    no_push: bool
    kicad_cli: Path | None
    site_profile: SiteProfile
    inventory: Path | None = None
    datasheet_library: Path = DEFAULT_DATASHEET_LIBRARY
    datasheet_repo: str = DEFAULT_DATASHEET_REPO
    ibom_extra_fields: tuple[str, ...] = DEFAULT_IBOM_EXTRA_FIELDS
    fabricator: str = DEFAULT_FABRICATOR


def _load_yaml_mapping(yaml_path: Path) -> Mapping[str, Any]:
    """Read ``yaml_path`` and return the top-level mapping.

    Args:
        yaml_path: Path to a YAML config file. Missing file → empty mapping.

    Returns:
        The parsed YAML document as a ``dict``. Empty document → ``{}``.

    Raises:
        ValueError: When the document parses to something other than a
            mapping at the top level.
    """
    if not yaml_path.exists():
        return {}
    raw = yaml.safe_load(yaml_path.read_text()) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"{yaml_path} must be a YAML mapping, got {type(raw).__name__}")
    return raw


def _resolve_site_repo(
    overrides: ConfigOverrides, env: Mapping[str, str], yaml_data: Mapping[str, Any]
) -> Path:
    """Resolve the effective ``site_repo`` from the precedence chain."""
    if overrides.site_repo is not None:
        return overrides.site_repo
    if "KPROJ_SITE_REPO" in env:
        return Path(env["KPROJ_SITE_REPO"])
    if "site_repo" in yaml_data:
        return Path(str(yaml_data["site_repo"]))
    return DEFAULT_SITE_REPO


def _resolve_no_push(
    overrides: ConfigOverrides, env: Mapping[str, str], yaml_data: Mapping[str, Any]
) -> bool:
    """Resolve the effective ``no_push`` from the precedence chain."""
    if overrides.no_push is not None:
        return overrides.no_push
    if "KPROJ_NO_PUSH" in env:
        return _parse_bool(env["KPROJ_NO_PUSH"])
    if "no_push" in yaml_data:
        return bool(yaml_data["no_push"])
    return DEFAULT_NO_PUSH


def _resolve_kicad_cli(
    overrides: ConfigOverrides, env: Mapping[str, str], yaml_data: Mapping[str, Any]
) -> Path | None:
    """Resolve the optional explicit ``kicad_cli`` path.

    ``None`` indicates the locator (``find_kicad_cli``) should probe.
    """
    if overrides.kicad_cli is not None:
        return overrides.kicad_cli
    if "KPROJ_KICAD_CLI" in env:
        return Path(env["KPROJ_KICAD_CLI"])
    if "kicad_cli" in yaml_data:
        return Path(str(yaml_data["kicad_cli"]))
    return None


def _resolve_inventory(
    overrides: ConfigOverrides, env: Mapping[str, str], yaml_data: Mapping[str, Any]
) -> Path | None:
    """Resolve the optional ``inventory`` CSV path (kproj#29).

    ``None`` when unset at every tier - deliberately **no** hardcoded
    fallback path (see the module docstring's ``inventory`` note).
    """
    if overrides.inventory is not None:
        return overrides.inventory
    if "KPROJ_INVENTORY" in env:
        return Path(env["KPROJ_INVENTORY"])
    if "inventory" in yaml_data:
        return Path(str(yaml_data["inventory"]))
    return None


def _resolve_datasheet_library(
    overrides: ConfigOverrides, env: Mapping[str, str], yaml_data: Mapping[str, Any]
) -> Path:
    """Resolve the effective local datasheet-library clone path (kproj#37)."""
    if overrides.datasheet_library is not None:
        return overrides.datasheet_library
    if "KPROJ_DATASHEET_LIBRARY" in env:
        return Path(env["KPROJ_DATASHEET_LIBRARY"])
    if "datasheet_library" in yaml_data:
        return Path(str(yaml_data["datasheet_library"]))
    return DEFAULT_DATASHEET_LIBRARY


def _resolve_datasheet_repo(
    overrides: ConfigOverrides, env: Mapping[str, str], yaml_data: Mapping[str, Any]
) -> str:
    """Resolve the effective public datasheet-repo ``<owner>/<repo>`` slug (kproj#37)."""
    if overrides.datasheet_repo is not None:
        return overrides.datasheet_repo
    if "KPROJ_DATASHEET_REPO" in env:
        return env["KPROJ_DATASHEET_REPO"]
    if "datasheet_repo" in yaml_data:
        return str(yaml_data["datasheet_repo"])
    return DEFAULT_DATASHEET_REPO


def _resolve_ibom_extra_fields(
    overrides: ConfigOverrides, env: Mapping[str, str], yaml_data: Mapping[str, Any]
) -> tuple[str, ...]:
    """Resolve iBOM extra fields from precedence tiers (kproj#48)."""
    if overrides.ibom_extra_fields is not None:
        return _normalize_ibom_extra_fields(overrides.ibom_extra_fields)
    if "KPROJ_IBOM_EXTRA_FIELDS" in env:
        return _normalize_ibom_extra_fields(env["KPROJ_IBOM_EXTRA_FIELDS"])
    if "ibom_extra_fields" in yaml_data:
        return _normalize_ibom_extra_fields(yaml_data["ibom_extra_fields"])
    return DEFAULT_IBOM_EXTRA_FIELDS


def _resolve_fabricator(
    overrides: ConfigOverrides, env: Mapping[str, str], yaml_data: Mapping[str, Any]
) -> str:
    """Resolve the effective jBOM ``--fabricator`` value."""
    if overrides.fabricator is not None:
        return _normalize_fabricator(overrides.fabricator)
    if "KPROJ_FABRICATOR" in env:
        return _normalize_fabricator(env["KPROJ_FABRICATOR"])
    if "fabricator" in yaml_data:
        return _normalize_fabricator(str(yaml_data["fabricator"]))
    return DEFAULT_FABRICATOR


def load_config(
    overrides: ConfigOverrides,
    env: Mapping[str, str],
    yaml_path: Path,
) -> KprojConfig:
    """Resolve the effective :class:`KprojConfig`.

    Args:
        overrides: CLI-derived overrides (see :class:`ConfigOverrides`).
        env: Mapping of environment variables to consult (typically
            ``os.environ``). Pass an empty dict in tests for isolation.
        yaml_path: Path to ``~/.kproj.yaml`` (or any test fixture);
            missing file → defaults apply.

    Returns:
        A populated :class:`KprojConfig` with the precedence applied.

    Raises:
        ValueError: When *yaml_path* exists but does not parse to a
            top-level mapping.
    """
    yaml_data = _load_yaml_mapping(yaml_path)
    return KprojConfig(
        site_repo=_resolve_site_repo(overrides, env, yaml_data),
        no_push=_resolve_no_push(overrides, env, yaml_data),
        kicad_cli=_resolve_kicad_cli(overrides, env, yaml_data),
        site_profile=_resolve_site_profile(overrides, env, yaml_data),
        inventory=_resolve_inventory(overrides, env, yaml_data),
        datasheet_library=_resolve_datasheet_library(overrides, env, yaml_data),
        datasheet_repo=_resolve_datasheet_repo(overrides, env, yaml_data),
        ibom_extra_fields=_resolve_ibom_extra_fields(overrides, env, yaml_data),
        fabricator=_resolve_fabricator(overrides, env, yaml_data),
    )


def _resolve_site_profile(
    overrides: ConfigOverrides,
    env: Mapping[str, str],
    yaml_data: Mapping[str, Any],
) -> SiteProfile:
    """Resolve the effective :class:`SiteProfile` for a production run.

    v1 ships only ``generic`` and ``hugo``; ``load_config`` always
    picks :data:`HUGO_SITE_PROFILE` because the SPCoast production
    site is a Hugo deployment.  A future ``--profile`` / ``--type`` /
    ``--theme`` CLI flag + env var + yaml key will grow the precedence
    chain here (matching the existing ``site_repo`` / ``no_push`` /
    ``kicad_cli`` resolvers).  Test fixtures that build
    :class:`KprojConfig` directly bypass this function entirely and
    receive the dataclass default (:data:`GENERIC_SITE_PROFILE`).

    Args:
        overrides: Reserved for the future ``ConfigOverrides.site_profile``
            field; currently unused.
        env: Reserved for the future ``KPROJ_SITE_PROFILE`` env var;
            currently unused.
        yaml_data: Reserved for the future ``site_profile:`` yaml key;
            currently unused.

    Returns:
        Always :data:`HUGO_SITE_PROFILE` in v1.
    """
    del overrides, env, yaml_data  # reserved; v1 has no override paths
    return HUGO_SITE_PROFILE
