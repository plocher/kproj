"""Unit tests for :mod:`kproj.config`.

Validates the four-tier precedence per ``docs/DESIGN.md`` §
*Configuration layer*: CLI override > env > ``~/.kproj.yaml`` > default.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from kproj.config import (
    DEFAULT_NO_PUSH,
    DEFAULT_SITE_REPO,
    GENERIC_SITE_PROFILE,
    HUGO_SITE_PROFILE,
    ConfigOverrides,
    KprojConfig,
    SiteProfile,
    load_config,
)


def test_config_overrides_is_frozen() -> None:
    """``ConfigOverrides`` is a frozen dataclass."""
    overrides = ConfigOverrides()
    with pytest.raises(dataclasses.FrozenInstanceError):
        overrides.no_push = True  # type: ignore[misc]


def test_kproj_config_is_frozen() -> None:
    """``KprojConfig`` is a frozen dataclass."""
    config = load_config(ConfigOverrides(), env={}, yaml_path=Path("/dev/null"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.no_push = True  # type: ignore[misc]


def test_load_config_falls_back_to_defaults(tmp_path: Path) -> None:
    """With no CLI / env / yaml inputs, defaults apply."""
    config = load_config(ConfigOverrides(), env={}, yaml_path=tmp_path / "missing.yaml")
    assert config.site_repo == DEFAULT_SITE_REPO
    assert config.no_push == DEFAULT_NO_PUSH
    assert config.kicad_cli is None


def test_load_config_reads_yaml_when_present(tmp_path: Path) -> None:
    """A populated ``~/.kproj.yaml`` overrides defaults."""
    yaml_path = tmp_path / "kproj.yaml"
    yaml_path.write_text("site_repo: /opt/site\nno_push: true\nkicad_cli: /opt/kicad-cli\n")
    config = load_config(ConfigOverrides(), env={}, yaml_path=yaml_path)
    assert config.site_repo == Path("/opt/site")
    assert config.no_push is True
    assert config.kicad_cli == Path("/opt/kicad-cli")


def test_load_config_env_beats_yaml(tmp_path: Path) -> None:
    """Environment variables take precedence over ``~/.kproj.yaml``."""
    yaml_path = tmp_path / "kproj.yaml"
    yaml_path.write_text("site_repo: /from/yaml\nno_push: false\n")
    config = load_config(
        ConfigOverrides(),
        env={
            "KPROJ_SITE_REPO": "/from/env",
            "KPROJ_NO_PUSH": "1",
            "KPROJ_KICAD_CLI": "/env/kicad-cli",
        },
        yaml_path=yaml_path,
    )
    assert config.site_repo == Path("/from/env")
    assert config.no_push is True
    assert config.kicad_cli == Path("/env/kicad-cli")


def test_load_config_cli_override_beats_env_and_yaml(tmp_path: Path) -> None:
    """CLI ``ConfigOverrides`` win over both env and yaml."""
    yaml_path = tmp_path / "kproj.yaml"
    yaml_path.write_text("site_repo: /from/yaml\nno_push: false\n")
    overrides = ConfigOverrides(
        site_repo=Path("/from/cli"),
        no_push=False,
        kicad_cli=Path("/cli/kicad-cli"),
    )
    config = load_config(
        overrides,
        env={"KPROJ_SITE_REPO": "/from/env", "KPROJ_NO_PUSH": "1"},
        yaml_path=yaml_path,
    )
    assert config.site_repo == Path("/from/cli")
    assert config.no_push is False
    assert config.kicad_cli == Path("/cli/kicad-cli")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("true", True),
        ("yes", True),
        ("0", False),
        ("false", False),
        ("no", False),
        ("", False),
    ],
)
def test_load_config_parses_env_no_push_booleans(raw: str, expected: bool, tmp_path: Path) -> None:
    """``KPROJ_NO_PUSH`` parses common boolean shapes case-insensitively."""
    config = load_config(
        ConfigOverrides(),
        env={"KPROJ_NO_PUSH": raw},
        yaml_path=tmp_path / "missing.yaml",
    )
    assert config.no_push is expected


def test_load_config_yaml_with_unknown_keys_does_not_raise(tmp_path: Path) -> None:
    """Unknown YAML keys are ignored (forward-compatible)."""
    yaml_path = tmp_path / "kproj.yaml"
    yaml_path.write_text("site_repo: /ok\nfuture_key: experimental\n")
    config = load_config(ConfigOverrides(), env={}, yaml_path=yaml_path)
    assert config.site_repo == Path("/ok")


def test_load_config_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    """A YAML document that is not a mapping at the top level is rejected."""
    yaml_path = tmp_path / "kproj.yaml"
    yaml_path.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError, match="must be a YAML mapping"):
        load_config(ConfigOverrides(), env={}, yaml_path=yaml_path)


def test_kproj_config_dataclass_exposes_paths_as_path_objects() -> None:
    """The resolved config exposes ``Path`` objects, not raw strings."""
    config = KprojConfig(
        site_repo=Path("/x"),
        no_push=False,
        kicad_cli=Path("/y"),
        site_profile=GENERIC_SITE_PROFILE,
    )
    assert isinstance(config.site_repo, Path)
    assert isinstance(config.kicad_cli, Path)


# ─────────────────────── SiteProfile contract ───────────────────────


class TestSiteProfileContract:
    """The two built-in profiles carry the expected structural values.

    GENERIC is the abstract test anchor — backend-neutral values; a
    live deployment against GENERIC would land files at paths that
    match neither Hugo (``content/...``) nor Jekyll (``_versions``).
    HUGO is the concrete Hugo backend used by production runs.
    """

    def test_generic_is_backend_neutral(self) -> None:
        """GENERIC values carry no backend-specific prefixes."""
        assert GENERIC_SITE_PROFILE.name == "generic"
        assert GENERIC_SITE_PROFILE.versions_dir == "versions"
        assert GENERIC_SITE_PROFILE.pages_dir == "pages"
        assert GENERIC_SITE_PROFILE.layout_field is None

    def test_hugo_carries_hugo_content_prefix(self) -> None:
        """HUGO puts per-version + per-page files under Hugo's ``content/`` root."""
        assert HUGO_SITE_PROFILE.name == "hugo"
        assert HUGO_SITE_PROFILE.versions_dir == "content/versions"
        assert HUGO_SITE_PROFILE.pages_dir == "content/pages"
        assert HUGO_SITE_PROFILE.layout_field is None  # Hugo picks by section

    def test_generic_and_hugo_are_distinct(self) -> None:
        """The two profiles are not accidentally aliased."""
        assert GENERIC_SITE_PROFILE != HUGO_SITE_PROFILE
        assert GENERIC_SITE_PROFILE.versions_dir != HUGO_SITE_PROFILE.versions_dir
        assert GENERIC_SITE_PROFILE.pages_dir != HUGO_SITE_PROFILE.pages_dir

    def test_site_profile_is_frozen(self) -> None:
        """``SiteProfile`` is a frozen dataclass."""
        profile = SiteProfile(name="x", versions_dir="v", pages_dir="p")
        with pytest.raises(dataclasses.FrozenInstanceError):
            profile.name = "y"  # type: ignore[misc]


class TestSiteProfileResolution:
    """``KprojConfig.site_profile`` has no default; ``load_config`` selects HUGO."""

    def test_construction_requires_explicit_profile(self) -> None:
        """Constructing ``KprojConfig`` without ``site_profile`` raises TypeError.

        The abstraction has intentionally **no dataclass default** so
        the profile is resolved exactly once (at argparse/``load_config``
        time for production, or explicitly in test fixtures via
        :data:`GENERIC_SITE_PROFILE`) and cannot silently fall back to
        a stale in-code default.
        """
        with pytest.raises(TypeError, match="site_profile"):
            KprojConfig(  # type: ignore[call-arg]
                site_repo=Path("/x"),
                no_push=False,
                kicad_cli=None,
            )

    def test_construction_with_explicit_profile_succeeds(self) -> None:
        """Passing ``site_profile=GENERIC`` explicitly constructs cleanly."""
        config = KprojConfig(
            site_repo=Path("/x"),
            no_push=False,
            kicad_cli=None,
            site_profile=GENERIC_SITE_PROFILE,
        )
        assert config.site_profile == GENERIC_SITE_PROFILE

    def test_load_config_selects_hugo_for_production(self, tmp_path: Path) -> None:
        """``load_config`` (the production entry point) selects HUGO in v1."""
        config = load_config(
            ConfigOverrides(),
            env={},
            yaml_path=tmp_path / "missing.yaml",
        )
        assert config.site_profile == HUGO_SITE_PROFILE

    def test_load_config_selects_hugo_even_when_other_fields_come_from_overrides(
        self,
        tmp_path: Path,
    ) -> None:
        """``site_profile`` selection is independent of other override sources."""
        config = load_config(
            ConfigOverrides(site_repo=Path("/from/cli"), no_push=True),
            env={"KPROJ_KICAD_CLI": "/env/kicad-cli"},
            yaml_path=tmp_path / "missing.yaml",
        )
        assert config.site_profile == HUGO_SITE_PROFILE
        assert config.site_repo == Path("/from/cli")  # sanity
        assert config.no_push is True
