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
    """

    site_repo: Path
    no_push: bool
    kicad_cli: Path | None


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
    )
