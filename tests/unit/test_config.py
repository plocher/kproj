"""Unit tests for :mod:`kproj.config`.

Validates the four-tier precedence per ``docs/DESIGN.md`` §
*Configuration layer*: CLI override > env > ``~/.kproj.yaml`` > default.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from kproj.config import (
    DEFAULT_DATASHEET_LIBRARY,
    DEFAULT_DATASHEET_REPO,
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
    assert config.inventory is None
    assert config.datasheet_library == DEFAULT_DATASHEET_LIBRARY
    assert config.datasheet_repo == DEFAULT_DATASHEET_REPO


def test_load_config_reads_yaml_when_present(tmp_path: Path) -> None:
    """A populated ``~/.kproj.yaml`` overrides defaults."""
    yaml_path = tmp_path / "kproj.yaml"
    yaml_path.write_text(
        "site_repo: /opt/site\nno_push: true\nkicad_cli: /opt/kicad-cli\n"
        "inventory: /opt/inventory.csv\n"
        "datasheet_library: /opt/datasheets\n"
        "datasheet_repo: example/datasheets\n"
    )
    config = load_config(ConfigOverrides(), env={}, yaml_path=yaml_path)
    assert config.site_repo == Path("/opt/site")
    assert config.no_push is True
    assert config.kicad_cli == Path("/opt/kicad-cli")
    assert config.inventory == Path("/opt/inventory.csv")
    assert config.datasheet_library == Path("/opt/datasheets")
    assert config.datasheet_repo == "example/datasheets"


def test_load_config_env_beats_yaml(tmp_path: Path) -> None:
    """Environment variables take precedence over ``~/.kproj.yaml``."""
    yaml_path = tmp_path / "kproj.yaml"
    yaml_path.write_text(
        "site_repo: /from/yaml\n"
        "no_push: false\n"
        "inventory: /from/yaml.csv\n"
        "datasheet_library: /from/yaml-lib\n"
        "datasheet_repo: yaml/repo\n"
    )
    config = load_config(
        ConfigOverrides(),
        env={
            "KPROJ_SITE_REPO": "/from/env",
            "KPROJ_NO_PUSH": "1",
            "KPROJ_KICAD_CLI": "/env/kicad-cli",
            "KPROJ_INVENTORY": "/from/env.csv",
            "KPROJ_DATASHEET_LIBRARY": "/from/env-lib",
            "KPROJ_DATASHEET_REPO": "env/repo",
        },
        yaml_path=yaml_path,
    )
    assert config.site_repo == Path("/from/env")
    assert config.no_push is True
    assert config.kicad_cli == Path("/env/kicad-cli")
    assert config.inventory == Path("/from/env.csv")
    assert config.datasheet_library == Path("/from/env-lib")
    assert config.datasheet_repo == "env/repo"


def test_load_config_cli_override_beats_env_and_yaml(tmp_path: Path) -> None:
    """CLI ``ConfigOverrides`` win over both env and yaml."""
    yaml_path = tmp_path / "kproj.yaml"
    yaml_path.write_text("site_repo: /from/yaml\nno_push: false\ninventory: /from/yaml.csv\n")
    overrides = ConfigOverrides(
        site_repo=Path("/from/cli"),
        no_push=False,
        kicad_cli=Path("/cli/kicad-cli"),
        inventory=Path("/from/cli.csv"),
        datasheet_library=Path("/from/cli-lib"),
        datasheet_repo="cli/repo",
    )
    config = load_config(
        overrides,
        env={
            "KPROJ_SITE_REPO": "/from/env",
            "KPROJ_NO_PUSH": "1",
            "KPROJ_INVENTORY": "/from/env.csv",
        },
        yaml_path=yaml_path,
    )
    assert config.site_repo == Path("/from/cli")
    assert config.no_push is False
    assert config.kicad_cli == Path("/cli/kicad-cli")
    assert config.inventory == Path("/from/cli.csv")
    assert config.datasheet_library == Path("/from/cli-lib")
    assert config.datasheet_repo == "cli/repo"


class TestDatasheetLibraryPrecedence:
    """Per-tier tests for the local datasheet-library clone path."""

    def test_defaults_to_spcoast_convention(self, tmp_path: Path) -> None:
        config = load_config(ConfigOverrides(), env={}, yaml_path=tmp_path / "missing.yaml")
        assert config.datasheet_library == DEFAULT_DATASHEET_LIBRARY

    def test_yaml_overrides_default(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "kproj.yaml"
        yaml_path.write_text("datasheet_library: /from/yaml-lib\n")
        config = load_config(ConfigOverrides(), env={}, yaml_path=yaml_path)
        assert config.datasheet_library == Path("/from/yaml-lib")

    def test_env_beats_yaml(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "kproj.yaml"
        yaml_path.write_text("datasheet_library: /from/yaml-lib\n")
        config = load_config(
            ConfigOverrides(),
            env={"KPROJ_DATASHEET_LIBRARY": "/from/env-lib"},
            yaml_path=yaml_path,
        )
        assert config.datasheet_library == Path("/from/env-lib")

    def test_cli_override_beats_env_and_yaml(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "kproj.yaml"
        yaml_path.write_text("datasheet_library: /from/yaml-lib\n")
        config = load_config(
            ConfigOverrides(datasheet_library=Path("/from/cli-lib")),
            env={"KPROJ_DATASHEET_LIBRARY": "/from/env-lib"},
            yaml_path=yaml_path,
        )
        assert config.datasheet_library == Path("/from/cli-lib")


class TestDatasheetRepoPrecedence:
    """Per-tier tests for the public datasheet owner/repo slug."""

    def test_defaults_to_spcoast_convention(self, tmp_path: Path) -> None:
        config = load_config(ConfigOverrides(), env={}, yaml_path=tmp_path / "missing.yaml")
        assert config.datasheet_repo == DEFAULT_DATASHEET_REPO

    def test_yaml_overrides_default(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "kproj.yaml"
        yaml_path.write_text("datasheet_repo: yaml/repo\n")
        config = load_config(ConfigOverrides(), env={}, yaml_path=yaml_path)
        assert config.datasheet_repo == "yaml/repo"

    def test_env_beats_yaml(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "kproj.yaml"
        yaml_path.write_text("datasheet_repo: yaml/repo\n")
        config = load_config(
            ConfigOverrides(),
            env={"KPROJ_DATASHEET_REPO": "env/repo"},
            yaml_path=yaml_path,
        )
        assert config.datasheet_repo == "env/repo"

    def test_cli_override_beats_env_and_yaml(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "kproj.yaml"
        yaml_path.write_text("datasheet_repo: yaml/repo\n")
        config = load_config(
            ConfigOverrides(datasheet_repo="cli/repo"),
            env={"KPROJ_DATASHEET_REPO": "env/repo"},
            yaml_path=yaml_path,
        )
        assert config.datasheet_repo == "cli/repo"


class TestInventoryPrecedence:
    """Per-tier tests for ``KprojConfig.inventory`` (kproj#29 / ADR 0010).

    Mirrors the established per-tier pattern for ``site_repo`` /
    ``no_push`` / ``kicad_cli`` above. Unlike those, ``inventory`` has
    **no hardcoded fallback** - the ticket owner explicitly rejected a
    convention path (see ``config.py``'s module docstring); the
    bottom tier is always ``None``.
    """

    def test_defaults_to_none_with_no_inputs(self, tmp_path: Path) -> None:
        config = load_config(ConfigOverrides(), env={}, yaml_path=tmp_path / "missing.yaml")
        assert config.inventory is None

    def test_yaml_overrides_the_none_default(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "kproj.yaml"
        yaml_path.write_text("inventory: /from/yaml.csv\n")
        config = load_config(ConfigOverrides(), env={}, yaml_path=yaml_path)
        assert config.inventory == Path("/from/yaml.csv")

    def test_env_beats_yaml(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "kproj.yaml"
        yaml_path.write_text("inventory: /from/yaml.csv\n")
        config = load_config(
            ConfigOverrides(),
            env={"KPROJ_INVENTORY": "/from/env.csv"},
            yaml_path=yaml_path,
        )
        assert config.inventory == Path("/from/env.csv")

    def test_cli_override_beats_env_and_yaml(self, tmp_path: Path) -> None:
        yaml_path = tmp_path / "kproj.yaml"
        yaml_path.write_text("inventory: /from/yaml.csv\n")
        config = load_config(
            ConfigOverrides(inventory=Path("/from/cli.csv")),
            env={"KPROJ_INVENTORY": "/from/env.csv"},
            yaml_path=yaml_path,
        )
        assert config.inventory == Path("/from/cli.csv")


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
        assert GENERIC_SITE_PROFILE.assets_dir == "versions"
        assert GENERIC_SITE_PROFILE.layout_field is None

    def test_hugo_carries_hugo_content_prefix(self) -> None:
        """HUGO puts per-version + per-page files under Hugo's ``content/`` root."""
        assert HUGO_SITE_PROFILE.name == "hugo"
        assert HUGO_SITE_PROFILE.versions_dir == "content/versions"
        # Assets live under static/ so Hugo serves them at the /versions/ URL.
        assert HUGO_SITE_PROFILE.assets_dir == "static/versions"
        assert HUGO_SITE_PROFILE.layout_field is None  # Hugo picks by section

    def test_generic_and_hugo_are_distinct(self) -> None:
        """The two profiles are not accidentally aliased."""
        assert GENERIC_SITE_PROFILE != HUGO_SITE_PROFILE
        assert GENERIC_SITE_PROFILE.versions_dir != HUGO_SITE_PROFILE.versions_dir
        assert GENERIC_SITE_PROFILE.assets_dir != HUGO_SITE_PROFILE.assets_dir

    def test_site_profile_is_frozen(self) -> None:
        """``SiteProfile`` is a frozen dataclass."""
        profile = SiteProfile(name="x", versions_dir="v", assets_dir="a")
        with pytest.raises(dataclasses.FrozenInstanceError):
            profile.name = "y"  # type: ignore[misc]

    def test_site_profile_requires_assets_dir(self) -> None:
        """``assets_dir`` is a required field (no default).

        An implicit fallback is exactly what let Hugo assets land outside
        ``static/`` and 404 (kproj#10); every backend must state where its
        served assets physically live.
        """
        with pytest.raises(TypeError, match="assets_dir"):
            SiteProfile(name="x", versions_dir="v")  # type: ignore[call-arg]

    def test_version_and_project_index_paths(self) -> None:
        """Version pages and the project section index derive from versions_dir."""
        site = Path("/site")
        assert HUGO_SITE_PROFILE.version_page_path(site, "Demo", "1.0B") == (
            site / "content/versions" / "Demo" / "1.0B.md"
        )
        assert HUGO_SITE_PROFILE.project_index_path(site, "Demo") == (
            site / "content/versions" / "Demo" / "_index.md"
        )
        assert GENERIC_SITE_PROFILE.project_index_path(site, "Demo") == (
            site / "versions" / "Demo" / "_index.md"
        )


class TestAssetDiskPath:
    """``SiteProfile.asset_disk_path`` maps a public asset URL to disk.

    Public asset URLs are always ``/versions/<P>/<R>/<file>``; the physical
    location swaps the leading served-mount segment for ``assets_dir`` so
    the file resolves at that URL on the built site.
    """

    def test_generic_maps_versions_url_to_versions_dir(self) -> None:
        site = Path("/site")
        got = GENERIC_SITE_PROFILE.asset_disk_path(site, "/versions/Demo/1.0B/Demo-1.0B.top.png")
        assert got == site / "versions" / "Demo" / "1.0B" / "Demo-1.0B.top.png"

    def test_hugo_maps_versions_url_under_static(self) -> None:
        """Hugo serves ``static/`` at ``/``, so /versions/... lives in static/versions/."""
        site = Path("/site")
        got = HUGO_SITE_PROFILE.asset_disk_path(site, "/versions/Demo/1.0B/Demo-1.0B.ibom.html")
        assert got == site / "static" / "versions" / "Demo" / "1.0B" / "Demo-1.0B.ibom.html"

    def test_leading_slash_optional(self) -> None:
        """A path without the leading slash maps the same way."""
        site = Path("/site")
        with_slash = HUGO_SITE_PROFILE.asset_disk_path(site, "/versions/P/R/f.step")
        without_slash = HUGO_SITE_PROFILE.asset_disk_path(site, "versions/P/R/f.step")
        assert with_slash == without_slash == site / "static" / "versions" / "P" / "R" / "f.step"


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
