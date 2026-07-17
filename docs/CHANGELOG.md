# Changelog
## Unreleased
- Refactored CLI parsing to first-class verbs (`kproj publish`, `kproj list`, `kproj delete`) and removed legacy token-dispatch command routing.
- Added global `kproj --version` support and aligned list/delete with publish-style optional project resolution (defaults to `.` / CWD).
- Added `kproj list --all` for full site overview and switched list output to one-line summaries (`project [natural-ordered versions]`).
- Added site-management commands: `kproj list [project]` for published project/version introspection and `kproj delete [project] ...` for explicit retroactive cleanup.
- Added delete semantics for single-version removal and full-project removal with force/preview behavior (`kproj delete [project] --version <rev>`, bare `kproj delete [project]` preview-and-fail, and `kproj delete [project] --force`).
- Added delete-specific site commit messages (`delete version <VER>` and `delete project <list of VERs deleted>`) and reused `--dry-run`/`--no-push` behavior for delete flows.
- Ensured `/versions/` remains routable after deleting the final published project by creating a root section index (`content/versions/_index.md`) when the published set becomes empty.
- Added publish-context drift detection to regeneration decisions, so legacy version pages missing context metadata are regenerated once and no-op checks account for output-affecting publish changes.
- Added `--republish` (alias `--force`) to bypass unchanged optimization and force artifact regeneration.
- Gated toolchain discovery lines (`Info: Using kicad-cli ...`, `Info: Using jbom ...`) behind verbose mode (`-v`).
- Restored explicit compact-mode stderr notes for `github_link_missing` / `github_link_unpushed` so non-git or unpushed projects still surface missing GitHub-link advisories while keeping full finding rows debug-only.
- Extended iBOM enrichment to consume inventory-derived jBOM data (datasheet link/name, manufacturer, MPN mapping, fabricator part number, description, and DNP semantics) via iBOM extra-data XML without forking iBOM.
- Added grouped-reference expansion (`"R1, R2"` -> per-reference rows) so enriched inventory fields align with iBOM component refs.
- Added configurable `ibom_extra_fields` with full precedence support (CLI `--ibom-extra-fields`, env `KPROJ_IBOM_EXTRA_FIELDS`, yaml `ibom_extra_fields`, default value).
- Added configurable jBOM fabricator selection with full precedence support (CLI `--fabricator`, env `KPROJ_FABRICATOR`, yaml `fabricator`, default `jlc`).
- Added CSV header alias normalization for generic/JLC lookup output (`Reference`/`Designator`, `Description`/`Comment`, `Lcsc`/`LCSC Part #`) so enrichment remains reference-correct under JLC defaults.
- Switched iBOM `Datasheet` enrichment links to use curated `Datasheet Name` deep-links into `SPCoast-inventory` (GitHub blob URLs) instead of supplier-provided datasheet URLs.
- Updated default iBOM extra columns to `Details,Description`; `Details` now composes `Manufacturer`, `MPN`, and a compact `Datasheet` link (`<br>` separated), replacing separate `Manufacturer`, `MPN`, `Fabricator Part Number`, `Datasheet`, and `Datasheet Name` default columns.
- Updated generated iBOM UI defaults to start on the front side (`layer_view=F`) and hide `checkboxes` + `Footprint` columns by default while relabeling `References` to `Ref`.
- Added generated iBOM column-width heuristics to minimize row number/`Ref`/`Value`/`Details` columns and favor remaining width for `Description` under common layouts.
- Fixed the iBOM column-visibility dropdown (top-left cell) rendering only a single entry: SPCoast's iBOM UI defaults (column widths, default hidden columns, `References`->`Ref` relabeling) now ride iBOM's own supported `user.css`/`user.js` customization hooks instead of splicing text into iBOM's generated HTML/JS after the fact, and the `th.numCol` width constraint that hosted the dropdown (and was corrupting its rendering) is no longer applied.
- Preserved fallback behavior when inventory is not configured (legacy PCB-backed iBOM extra-data path remains valid).
## 0.4.0
- Humanized console output with `Info:`, `Note:`, `Warning:`, and `Error:` prefixes; GitHub-link environment diagnostics are now INFO and no longer change a successful exit code.
- Dry-run reports the public destination from the site checkout's `hugo.toml`, with a site-relative fallback.
- Plain unchanged publishes now flush pending site commits created by earlier `--no-push` runs; batch and dry-run modes report pending debt without pushing.
