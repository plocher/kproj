# ADR 0010: Live `jbom bom` Invocation for Datasheet-Name Lookup

Date: 2026-07-13 (amended 2026-07-14, kproj#36; amended 2026-07-14, kproj#41)
Status: Accepted
Related: ADR 0003 (jBOM Separation — Read, Don't Invoke; amended by this ADR), jBOM#342 (datasheet document library map), jBOM#350 (kproj publish-mechanics resolution), kproj#36 (invocation bug fix + multi-field row shape), kproj#37 (CLI/config surface for `inventory` / `datasheet_library` / `datasheet_repo`), kproj#41 (global `-q` flag)

## Context

kproj#29 requires kproj to publish per-component datasheet deep-links, sourced from the BOM's curated `Datasheet Name` column, into the public `plocher/SPCoast-inventory` library repo (view + download URLs; no PDF copies — see jBOM#350).

ADR 0003 established "read, don't invoke": kproj reads jBOM's already-written `production/` outputs (`bom.csv` / `pos.csv` / the gerber zip) rather than invoking jBOM itself. The obvious extension — read `Datasheet Name` out of the existing `production/jbom.csv` fab snapshot — was the original design of this ticket (see `kproj/common/datasheet_library.py`'s first revision).

That design was rejected by the ticket owner during implementation, verified against a real project:

- `production/jbom.csv` is a **fab-oriented, point-in-time snapshot**, written by whatever `jbom fab` invocation last ran. It may be old (predating jBOM 7.4.0's `Datasheet Name` field entirely) or may never have requested the field via `-f`/`--fields`.
- Datasheet links are a **publish-time concern**, not a fab-time one: they should reflect the *current* state of the curated inventory, not a stale fab artifact. A maintainer who curates a new `Datasheet Name` in the inventory shouldn't have to re-run `jbom fab` just to get a fresh `kproj publish` to pick it up.

## Decision

kproj invokes jBOM's `bom` subcommand read-only, at publish time, for a small, extensible set of BOM fields:

```
jbom -q bom <project_dir> --inventory <path> -f "reference,datasheet,datasheet_name" -o -
```

**kproj#41 addition**: the global `-q` flag (jBOM 7.8.1+, `plocher/jBOM#376`) suppresses jBOM's info/warning guidance diagnostics (e.g. "Missing important generic fields: ...") on stderr, which otherwise leaked into kproj's terminal/captured stderr during a publish run. Errors still print. `-q` is a *global* jBOM flag and MUST precede the `bom` subcommand. No version detection or fallback - per the owner ruling, latest jBOM and latest kproj are always used together. (`-q` has been a global jBOM flag since before 7.8.1 — jBOM#376 only made `bom` diagnostics honor it — so against an older jBOM the flag still parses fine and is merely ineffective; there is no ordering hazard while PyPI propagates the new release.)

**kproj#36 correction**: the original implementation of this ADR passed the *display header* `"Datasheet Name"` (with a space) as the `-f` token — jBOM's `-f` expects comma-separated, normalized field names (a token containing a space is a syntax error against real jBOM 7.8.0), so every publish silently degraded to the `datasheet_field_missing` advisory. The field list is `reference,datasheet,datasheet_name` — normalized snake_case tokens — declared as a single constant (`kproj.common.datasheet_library.DATASHEET_BOM_FIELDS`) built from an extensible tuple, since this is general BOM-row plumbing whose eventual consumer is the iBOM interactive-BOM viewer (more fields will be needed there; out of scope for kproj#36 itself). jBOM still *renders* the output CSV header in title-cased display form (`"Reference","Datasheet","Datasheet Name"`) regardless of the `-f` token casing, so the parser side is unaffected by this fix. Output is CSV on stdout, parsed into structured **per-reference rows** (`kproj.model.datasheet_row.DatasheetRow`); the project-index Documentation list derives its distinct, case-insensitively-deduped names from those rows via `distinct_datasheet_names`.

**kproj#36 owner ruling — no inventory, no invocation**: `--inventory` is no longer optional-but-omittable. When `KprojConfig.inventory` is unconfigured (`None`), kproj never builds or runs the `jbom bom` command at all: the `datasheet_name` column only exists in the inventory, so there is no data to fetch and the invocation would be pointless. This is a silent, advisory-free degraded state (no `Finding` is emitted) — see kproj#37's first-run INFO hint for the discoverability companion. This supersedes the original "omit `--inventory` and accept blank columns" design below.

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

**kproj#36 owner ruling — invoke `jbom` from PATH**: the original invocation went via `[sys.executable, "-m", "jbom", ...]`, reasoned as "jBOM is a normal Python dependency of kproj". This rationale was overruled: kproj now resolves the `jbom` executable from `PATH` (`shutil.which("jbom")`), falling back to `[sys.executable, "-m", "jbom"]` only when no `jbom` is found on `PATH` (`kproj.common.datasheet_library._resolve_jbom_executable`). Both invocation shapes degrade to the same advisory finding on failure, so this is a pure preference change, not a new failure mode.

### Advisory-only, never a publish blocker

Every failure mode — jBOM missing or too old to recognise the field, a non-zero exit, a subprocess timeout, or a missing `Datasheet Name` column — degrades to a warning `Finding` (`datasheet_field_missing`) rather than raising. kproj publishes without datasheet links in that case. See `kproj.common.datasheet_library.read_datasheet_rows` (and its `read_datasheet_names` convenience wrapper). The no-inventory skip (above) is the one exception: it is not a failure mode, so it emits no `Finding` at all.

### Inventory path: `KprojConfig.inventory`, no hardcoded convention

`jbom bom --inventory <path>` has no profile/defaults-hierarchy fallback in jBOM today (verified against jBOM main, 7.5.0-era: `inventory_files` defaults to an empty tuple with no resolution beyond the CLI flag). kproj therefore owns `KprojConfig.inventory: Path | None`, resolved via the same CLI-override / `KPROJ_INVENTORY` env / `~/.kproj.yaml` `inventory:` key precedence as `site_repo` (and, per kproj#37, exposed as a first-class `--inventory` CLI flag rather than being reserved for a future one). Unlike `site_repo`, it has **no hardcoded fallback path** — per jBOM#350's rejection of hardcoded user-machine paths as an antipattern. `None` now skips the `jbom bom` invocation entirely (kproj#36 ruling above), rather than omitting just the `--inventory` flag.

### Local library clone + public repo slug are now configurable (kproj#37)

The advisory guard's local clone path (`KprojConfig.datasheet_library`) and the published deep-link `<owner>/<repo>` slug (`KprojConfig.datasheet_repo`) each gained the same CLI/env/yaml override tiers as `site_repo`, but - per ADR 0007 - keep their SPCoast-convention hardcoded fallback (`~/Dropbox/KiCad/SPCoast-inventory` / `plocher/SPCoast-inventory`) rather than defaulting to `None`. `kproj.common.datasheet_library.build_datasheet_link` takes `owner_repo` and `check_datasheet_links` takes `library_repo`, both as explicit parameters instead of reading a module-level constant, so a `kproj --datasheet-repo` / `--datasheet-library` override can retarget the published URLs and local guard clone for a forked or private library.

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
