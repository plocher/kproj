# kproj

KiCad project publisher for the SPCoast site: one `kproj` invocation publishes a point-in-time snapshot of a KiCad project as a version entry.

The canonical vocabulary used across the kproj codebase, ADRs, PRD, DESIGN doc, and source code. This document is **terminology-only**. It captures terms and their definitions. Implementation mechanics, contracts, and step-by-step specifications live elsewhere:

- Architectural decisions → `docs/adr/`
- v1 user-facing requirements → `docs/PRD.md`
- v1 implementation specs → `docs/DESIGN.md` (including the domain model types, domain services, naming conventions, and Producer Pattern)

When new terms emerge during PRD authoring, implementation, or grilling, only term-shaped entries land here. Mechanics go to the PRD or DESIGN.

## Domain vocabulary

### release
The (project, PCB-revision) pair. EAGLE-era meaning carried forward: "the design was released from development and sent to a fab house". Each KiCad project produces many releases over its lifetime as the board layout iterates. **In kproj v1, a `kproj` invocation does not assert a release event** — it publishes a *point-in-time snapshot* of the project to the site. The release event itself (tag + gh-release in the project repo) is (B) release-lifecycle work, out of v1 scope (ADR 0002). The conceptual identity `(project, board_rev)` still anchors what kproj publishes.

### version
The site artifact at `<versions_dir>/<Project>/<board_rev>.md` representing a snapshot of one release on the SPCoast site (default `content/versions/<Project>/<board_rev>.md` under the Hugo `GENERIC_SITE_PROFILE`; see `docs/DESIGN.md` § *SiteProfile abstraction*). Tied 1:1 to KiCad PCB `${REVISION}` (the `<DESIGN><LETTER>` form, e.g. `3.0B`). Each kproj invocation writes exactly one version entry. The SCH `${REVISION}` (the `<DESIGN>` form, e.g. `3.0`) is recorded as `design_rev` but does not key the version — multiple PCB layout iterations of the same SCH design are distinct versions.

### publish
Verb: "make the current snapshot of a release visible on the SPCoast site". Also the name of the v1 pipeline's terminal step (`SitePublisher`).

### tag
Git tag in the project's own repo identifying a release. **Out of kproj v1 scope** (ADR 0002) — handled by the user's existing Makefile / manual `git tag` workflow. Tag format when (B) lifecycle work lands: `release/<board_rev>` (slash-namespaced; e.g. `release/1.0B`).

### gh-release
`gh release create` artifact in the project's own repo, keyed on the `release/<board_rev>` tag. **Out of kproj v1 scope** (ADR 0002).

### status
A release's lifecycle attribute, sourced from `${COMMENT9}` in the title block per the extended SPCoast convention. Closed taxonomy:

- `experimental` — first small-quantity fab; design under validation. Same design files as `active`; confidence differs, not content.
- `active` — design validated; in regular production use. Default for established projects.
- `retired` — no longer in active use; archived for reference.
- `broken` — known defects; do not fabricate. Site renders with warning callout.
- `replaced-by:<project-dir>` — superseded by another project. `<project-dir>` is the directory name (unique even when `.kicad_pro` basenames collide — e.g. `Brakeman-BLUE`, not `Brakeman`).
- `private` — release exists; `publish` step skipped. cpOD pattern.

Experimental→active is a confidence transition, **not a new release**: design files are identical between the first small-qty fab and subsequent quantity fabs; only the status value changes.

### design_rev / board_rev
`design_rev` is the SCH `${REVISION}` (the `<DESIGN>` form, e.g. `3.0`). `board_rev` is the PCB `${REVISION}` (the `<DESIGN><LETTER>` form, e.g. `3.0B`). The relationship `board_rev startswith design_rev + zero-or-more letters` is a domain invariant — any other relationship is a logical error in title-block content and is surfaced by the metadata analyzer.

### audit
The metadata-quality lint pass performed by `MetadataAnalyzer`. Distinct from DRC/ERC analysis (performed by `DesignAnalyzer`). "Audit findings" refer to `MetadataAnalyzer`'s output; "DRC/ERC findings" refer to `DesignAnalyzer`'s output.

## Imported terms

Owned by [SPCoast-inventory's glossary](https://github.com/plocher/SPCoast-inventory/blob/main/CONTEXT.md) — use its definitions; do not redefine here:
**Library**, **Document**, **Datasheet Name**, **Never-Rename**.

Owned by [jBOM's glossary](https://github.com/plocher/jBOM/blob/main/CONTEXT.md):
**Item**, **Datasheet Name column** (the BOM column kproj reads live, via `jbom bom -f "Datasheet Name"` at publish time — not from `production/jbom.csv`, which is a stale fab-time snapshot; see ADR 0010).
