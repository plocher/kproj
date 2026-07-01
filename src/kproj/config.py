"""kproj configuration layer.

Implements the four-tier precedence from ``docs/DESIGN.md`` §
*Configuration layer*:

1. :class:`ConfigOverrides` field (set by a CLI flag)
2. Environment variable (``KPROJ_SITE_REPO`` / ``KPROJ_NO_PUSH`` /
   ``KPROJ_KICAD_CLI``)
3. ``~/.kproj.yaml`` key (``site_repo`` / ``no_push`` / ``kicad_cli``)
4. Hardcoded fallback (:data:`DEFAULT_SITE_REPO`, ``False``,
   ``None``)

Per ADR 0006, this module never imports ``argparse``. The CLI builds a
:class:`ConfigOverrides` from its parsed namespace and calls
:func:`load_config`.

The module also owns the :class:`SiteProfile` abstraction — the seam that
keeps kproj's site-repo layout (where per-version markdown files land,
what front-matter shape gets emitted) decoupled from a specific site
backend.  Two built-in profiles ship in v1:

* :data:`GENERIC_SITE_PROFILE` — the abstract test-anchor.  Values are
  intentionally backend-neutral (``versions/``, ``pages/``, no explicit
  layout field) so Behave scenarios and unit-test fixtures can validate
  contract behaviour without pinning to any real backend.  It is
  **not** intended for deployment against a live site; real backends
  ship their own concrete profile.
* :data:`HUGO_SITE_PROFILE` — the concrete Hugo backend.  Fills in the
  structural bones a Hugo GitHub Pages deployment expects
  (``content/versions/``, ``content/pages/``, ``layout:`` field
  omitted so Hugo picks by section).  This is what
  :func:`load_config` selects for production callers today.

Future named profiles (Jekyll, Astro, custom) plug into the same
abstraction via a future ``--profile`` / ``--type`` / ``--theme`` CLI
flag; the ``--site-repo`` flag remains reserved for the on-disk repo
path.  Analogue to jBOM's ADR 0008 pattern: ``generic`` is the
no-flag test fallback; named profiles fill in backend-specific values.
"""

from __future__ import annotations

from collections.abc import Mapping
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


# ---- SiteProfile abstraction (mirrors jBOM's ADR 0008 GENERIC pattern) ----


@dataclass(frozen=True)
class SiteProfile:
    """Site-repo layout profile — the seam between kproj and the site backend.

    Concrete backends (Hugo, Jekyll, Astro, ...) differ in:

    * Where per-version markdown files land (``content/versions/`` for
      Hugo, ``_versions/`` for Jekyll, etc.).
    * Where the per-project overview page lands (``content/pages/`` for
      Hugo, ``pages/`` for Jekyll).
    * Whether an explicit ``layout:`` front-matter field is required
      (Jekyll's ``layout: eagle`` selector; Hugo picks layout by
      section and typically omits the field).

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
            per-version markdown files (``<Revision>.md``) are written
            — one directory per project below this dir.
        pages_dir: Subpath where the per-project overview markdown file
            (``<Project>.md``) is written.
        layout_field: Optional value for the ``layout:`` front-matter
            field. ``None`` means the field is omitted from the emitted
            YAML entirely. Non-``None`` means emit ``layout: <value>``
            (Jekyll-compatible).
    """

    name: str
    versions_dir: str
    pages_dir: str
    layout_field: str | None = None


GENERIC_SITE_PROFILE: SiteProfile = SiteProfile(
    name="generic",
    versions_dir="versions",
    pages_dir="pages",
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
    pages_dir="content/pages",
    layout_field=None,
)
"""The concrete Hugo backend site profile.

Fills in the structural bones a Hugo GitHub Pages deployment expects:

* ``content/versions/<Project>/<Revision>.md`` — per-version markdown
  lives under Hugo's ``content/`` root, one directory per project.
* ``content/pages/<Project>.md`` — per-project overview lives under
  Hugo's ``content/`` root.
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
    """

    site_repo: Path | None = None
    no_push: bool | None = None
    kicad_cli: Path | None = None


@dataclass(frozen=True)
class KprojConfig:
    """The fully resolved runtime configuration.

    Attributes:
        site_repo: Local site-repo checkout where kproj will write.
        no_push: When ``True``, ``git push`` is skipped after commits.
        kicad_cli: Optional explicit ``kicad-cli`` executable; ``None``
            triggers :func:`kproj.common.kicad_install.find_kicad_cli`
            discovery in pre-flight.
        site_profile: :class:`SiteProfile` selecting the site-repo
            layout and front-matter shape.
    """

    site_repo: Path
    no_push: bool
    kicad_cli: Path | None
    site_profile: SiteProfile


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
