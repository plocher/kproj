# kproj

KiCad project publisher for the SPCoast Hugo site.

`kproj` takes a point-in-time snapshot of a KiCad project (renders, schematic SVG/PDF, interactive HTML BOM, fabrication artifacts, KiCad source archive) and publishes it as a version entry on the SPCoast site.

## Installation

```sh
pip install kproj
```

Requires Python ≥3.10. `kproj` needs a local `kicad-cli` install (KiCad 9.x or 10.x) to render/export artifacts, and the iBOM plugin installed into KiCad for the interactive BOM step.

## Usage

```sh
kproj [<project-or-dir-or-file>] [options]
```

Run from inside a KiCad project directory, or pass a path to a `.kicad_pro` / `.kicad_sch` / `.kicad_pcb` file, a project directory, or a basename resolved under the KiCad projects root. Defaults to `.` (the current directory).

Pipeline: **render → ibom → fab → publish**. Each release generates board renders, schematic SVG/PDF, the interactive HTML BOM, packages fabrication artifacts, and commits (+ pushes) a version page and its assets into the configured site repo.

### CLI flags

Run `kproj --help` for the authoritative, up-to-date flag list. As of this writing:

- `--site-repo PATH` — override the local site-repo checkout (highest precedence).
- `--inventory PATH` — inventory CSV to enrich the BOM with curated datasheet names. Unset means kproj never invokes `jbom` and publishes without datasheet deep-links.
- `--fabricator FAB` — jBOM fabricator profile (`generic`, `jlc`, `pcbway`, `seeed`) used for lookup item/header normalization. Default: `jlc`.
- `--ibom-extra-fields FIELDS` — comma-separated iBOM table fields to surface from inventory-enriched data (for example `Details,Description`).
- `--datasheet-library PATH` — local datasheet-library clone used by the advisory publish guard.
- `--datasheet-repo OWNER/REPO` — public repo slug that published datasheet deep-links point at.
- `--dry-run` — read-only mode: surface findings without writing to the site repo.
- `--republish` / `--force` — force artifact regeneration and publish even when unchanged checks would otherwise skip producers.
- `--no-push` — skip `git push` after the site-repo commit (batch-friendly). Run N batch publishes with this flag, then run a final plain `kproj` to flush all queued site commits.
- `-v` / `--verbose`, `-d` / `--debug` — increase logging verbosity. Toolchain discovery lines (`Using kicad-cli...`, `Using jbom...`) are shown under verbose mode.

## Configuration

Every setting (except the project argument) follows a four-tier precedence, highest first:

1. CLI flag
2. `KPROJ_*` environment variable
3. `~/.kproj.yaml`
4. Hardcoded default

`kproj --help` documents the full precedence chain, every `KPROJ_*` environment variable, and a complete `~/.kproj.yaml` example inline.

### First-time setup

If `~/.kproj.yaml` is absent and no inventory is configured, kproj emits a one-time informational hint pointing here — it still publishes successfully, just without datasheet deep-links.

Create `~/.kproj.yaml` to configure kproj for your machine:

```yaml
site_repo: /path/to/your/SPCoast.github.io
no_push: false
kicad_cli: /usr/local/bin/kicad-cli
inventory: /path/to/your/SPCoast-inventory/SPCoast-INVENTORY.csv
datasheet_library: /path/to/your/SPCoast-inventory
datasheet_repo: plocher/SPCoast-inventory
ibom_extra_fields: Details,Description
fabricator: jlc
```

Every key is optional; omit what you don't need to override. `site_repo` and `no_push` control where and how kproj publishes; `kicad_cli` pins a specific executable instead of relying on auto-discovery; `inventory` / `datasheet_library` / `datasheet_repo` configure the datasheet deep-link feature below.
`ibom_extra_fields` controls which inventory-derived columns are surfaced in the generated iBOM table.
`fabricator` controls which jBOM fabricator profile is used for BOM lookup normalization (default `jlc`).

### Datasheet deep-links

When `inventory` is configured, kproj queries `jbom bom --inventory <path> --fabricator <fabricator> -f "reference,datasheet,datasheet_name" -o -` live at publish time and deep-links each curated `Datasheet Name` into the shared datasheet-library repo (view + download URLs) — no PDFs are copied into the site. Lookup parsing accepts both generic and JLC-oriented header names (`Reference`/`Designator`, `Description`/`Comment`, `Lcsc`/`LCSC Part #`). Without an inventory, kproj never invokes `jbom` and publishes without datasheet links (an intentional, advisory-free degraded state, not an error).

## Exit codes

- `0` — clean: published (or refreshed/noop/private-skip) with no error/warning findings.
- `1` — findings present: the same outcomes above, but with at least one error or warning finding (audit, DRC/ERC, etc.), surfaced on stderr and in the version page's Markdown body.
- `2` — mechanical failure: kicad-cli not found, project resolution failed, or another pipeline step raised.

## Composition with other tools

kproj is one tool in a small ecosystem. The release-lifecycle workflow composes via Makefile (see [`templates/Makefile.kicad`](templates/Makefile.kicad)):

- `jbom fab` — generates fabrication artifacts (`bom.csv`, `pos.csv`, `gerbers.zip`) into `./production/`. Invoked separately by the user before `kproj`.
- `kproj` — reads `./production/` + KiCad project files, publishes a snapshot to the SPCoast site.
- `git tag` + `gh release create` (manual or Makefile-driven) — the release-lifecycle layer, external to kproj.

## Development

- Python ≥3.10; [`uv`](https://docs.astral.sh/uv/) for environment + dependency management (`uv sync`, `uv run`).
- `uv.lock` is committed and authoritative for the development environment. Keep it fresh with `uv lock` whenever dependency inputs change (including local `../jBOM` version shifts). CI validates lock freshness on PRs, and release automation refreshes `uv.lock` after semantic version bumps.
- `pytest` + `behave` for testing; `ruff` + `mypy` for lint/type-checking; `pre-commit` hooks configured.
- `docs/DESIGN.md` has the implementation specs; `docs/adr/` has the Architecture Decision Records; `CONTEXT.md` has the canonical project vocabulary.
- `docs/history.md` has the retired v1-development phase tracker, for archival reference.

## License

MIT — see [`LICENSE`](LICENSE).
