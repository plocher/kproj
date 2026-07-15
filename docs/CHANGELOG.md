# Changelog
## Unreleased
- Extended iBOM enrichment to consume inventory-derived jBOM data (datasheet link/name, manufacturer, MPN mapping, fabricator part number, description, and DNP semantics) via iBOM extra-data XML without forking iBOM.
- Added grouped-reference expansion (`"R1, R2"` -> per-reference rows) so enriched inventory fields align with iBOM component refs.
- Added configurable `ibom_extra_fields` with full precedence support (CLI `--ibom-extra-fields`, env `KPROJ_IBOM_EXTRA_FIELDS`, yaml `ibom_extra_fields`, default value).
- Added configurable jBOM fabricator selection with full precedence support (CLI `--fabricator`, env `KPROJ_FABRICATOR`, yaml `fabricator`, default `jlc`).
- Added CSV header alias normalization for generic/JLC lookup output (`Reference`/`Designator`, `Description`/`Comment`, `Lcsc`/`LCSC Part #`) so enrichment remains reference-correct under JLC defaults.
- Preserved fallback behavior when inventory is not configured (legacy PCB-backed iBOM extra-data path remains valid).
## 0.4.0
- Humanized console output with `Info:`, `Note:`, `Warning:`, and `Error:` prefixes; GitHub-link environment diagnostics are now INFO and no longer change a successful exit code.
- Dry-run reports the public destination from the site checkout's `hugo.toml`, with a site-relative fallback.
- Plain unchanged publishes now flush pending site commits created by earlier `--no-push` runs; batch and dry-run modes report pending debt without pushing.
