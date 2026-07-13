# ADR 0010: Live `jbom bom` Invocation for Datasheet-Name Lookup

Date: 2026-07-13
Status: Accepted
Related: ADR 0003 (jBOM Separation — Read, Don't Invoke; amended by this ADR), jBOM#342 (datasheet document library map), jBOM#350 (kproj publish-mechanics resolution)

## Context

kproj#29 requires kproj to publish per-component datasheet deep-links, sourced from the BOM's curated `Datasheet Name` column, into the public `plocher/SPCoast-inventory` library repo (view + download URLs; no PDF copies — see jBOM#350).

ADR 0003 established "read, don't invoke": kproj reads jBOM's already-written `production/` outputs (`bom.csv` / `pos.csv` / the gerber zip) rather than invoking jBOM itself. The obvious extension — read `Datasheet Name` out of the existing `production/jbom.csv` fab snapshot — was the original design of this ticket (see `kproj/common/datasheet_library.py`'s first revision).

That design was rejected by the ticket owner during implementation, verified against a real project:

- `production/jbom.csv` is a **fab-oriented, point-in-time snapshot**, written by whatever `jbom fab` invocation last ran. It may be old (predating jBOM 7.4.0's `Datasheet Name` field entirely) or may never have requested the field via `-f`/`--fields`.
- Datasheet links are a **publish-time concern**, not a fab-time one: they should reflect the *current* state of the curated inventory, not a stale fab artifact. A maintainer who curates a new `Datasheet Name` in the inventory shouldn't have to re-run `jbom fab` just to get a fresh `kproj publish` to pick it up.

## Decision

kproj invokes jBOM's `bom` subcommand read-only, at publish time, specifically for the `Datasheet Name` column:

```
jbom bom <project_dir> -f "Datasheet Name" -o -
```

(plus `--inventory <path>` when `KprojConfig.inventory` is configured — see below). Output is CSV on stdout, parsed for distinct non-empty `Datasheet Name` values.

This **amends ADR 0003**, narrowly: kproj is no longer strictly "read jBOM's `production/` files, never invoke jBOM." The reversal is scoped precisely —

- kproj MAY invoke `jbom bom` read-only, for datasheet-name lookup, at publish time.
- kproj still does NOT invoke `jbom fab` / `FabricationWorkflow` (fab generation stays out-of-process, per ADR 0003's original rationale — cadence/fabricator/config decoupling).
- kproj still does NOT write to the inventory, and invokes no other jBOM subcommand.

Reframed as: **jBOM is a first-class read-only dependency of kproj.** kproj already used jBOM as a library for project-root resolution and KiCad-file attribute reading (ADR 0003's "what kproj still uses from jBOM" section); this ADR extends that read-only relationship to cover BOM/datasheet-name lookup via jBOM's own CLI surface, rather than kproj re-deriving BOM logic itself.

### Mechanism: subprocess CLI, not the services API

jBOM exposes both a CLI (`jbom bom ...`) and an internal services API (`jbom.application.bom_workflow.BOMWorkflow`). Both are legitimate per the ticket owner's ruling; kproj chose the CLI/subprocess route for this specific lookup because:

- The need here is minimal — one distinct-name list, nothing else from the BOM.
- `jbom bom -f ... -o -`'s CSV-to-stdout contract is jBOM's own behave-feature-tested public surface (`features/bom/datasheet_name_field.feature`), a stronger stability guarantee for this narrow need than coupling to `BOMWorkflow`'s internal `BOMRequest`/`BOMData`/`BOMEntry` shapes and its fabricator-projection pipeline, which carry more surface area than this lookup requires.
- Subprocess invocation mirrors kproj's existing external-tool integration pattern (`kicad-cli`), rather than introducing a second integration style alongside it.

Invocation goes via `[sys.executable, "-m", "jbom", ...]`, not a bare `jbom` on `PATH`: jBOM is a normal Python dependency of kproj (`tool.uv.sources`), so it's guaranteed importable in kproj's own venv — no separate executable-discovery locator is needed (unlike `kicad-cli`, which lives outside any Python environment).

### Advisory-only, never a publish blocker

Every failure mode — jBOM missing or too old to recognise the field, a non-zero exit, a subprocess timeout, or unparseable output — degrades to a warning `Finding` (`datasheet_field_missing`) rather than raising. kproj publishes without datasheet links in that case. See `kproj.common.datasheet_library.read_datasheet_names`.

### Inventory path: `KprojConfig.inventory`, no hardcoded convention

`jbom bom --inventory <path>` has no profile/defaults-hierarchy fallback in jBOM today (verified against jBOM main, 7.5.0-era: `inventory_files` defaults to an empty tuple with no resolution beyond the CLI flag). kproj therefore owns `KprojConfig.inventory: Path | None`, resolved via the same CLI-override / `KPROJ_INVENTORY` env / `~/.kproj.yaml` `inventory:` key precedence as `site_repo`. Unlike `site_repo`, it has **no hardcoded fallback path** — per jBOM#350's rejection of hardcoded user-machine paths as an antipattern. `None` omits `--inventory` entirely; jBOM then has no curated data to join against, so every row's `Datasheet Name` comes back blank — a valid, advisory-free degraded state, not every project need be inventory-curated.

## Consequences

### Positive

- Datasheet links always reflect the current inventory, not a stale fab snapshot.
- No re-run of `jbom fab` required to pick up new inventory curation.
- kproj's fab/generation boundary (ADR 0003's core concern) is untouched.

### Tradeoffs

- kproj's publish pipeline now shells out to jBOM (a second external-tool dependency alongside `kicad-cli`), with the attendant version-compatibility surface (mitigated by graceful degradation).
- A misconfigured or absent `jbom` degrades every publish to "no datasheet links" silently unless the maintainer reads the advisory finding.

### Reversibility

If jBOM later grows a profile-driven inventory-path default (mirroring `datasheet_staging.staging_dir`'s `~/.jbom/common.jbom.yaml` pattern), `KprojConfig.inventory` can be dropped in favour of omitting `--inventory` unconditionally — a follow-up jBOM ticket, not a kproj architecture change.
