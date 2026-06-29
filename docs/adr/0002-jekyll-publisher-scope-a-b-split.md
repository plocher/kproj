# ADR 0002: Jekyll-Publisher Scope — (A)/(B) Split
Date: 2026-06-29
Status: Accepted
Related: ADR 0007 (local-CLI v1)

## Context

A "KiCad release pipeline" tool could plausibly include all of:
1. Reading the project and generating snapshot artifacts (renders, schematic export, iBOM, fab.zip).
2. Writing those artifacts to a documentation site (Jekyll, in our case).
3. Creating a git tag in the project repo identifying the release.
4. Creating a GitHub release with assets via `gh release create`.
5. Optionally pushing to CI hooks, etc.

Conflating all of these creates a tool with multiple distinct concerns, distinct cadences (publication happens many times per fab cadence; tag/release happens once per fab), and distinct quality bars (publication is "show what's there"; tag/release implies "this is THE release").

## Decision

kproj v1 is exclusively a **Jekyll publisher** (the "A" layer). It takes a *point-in-time snapshot* of a KiCad project on disk and writes it to the SPCoast Jekyll site. Specifically excluded from v1 scope:

- Git tag creation in the project repo.
- `gh release create`.
- Working-tree-clean preconditions on the project repo.
- `--force` flag (nothing blocks, nothing to override).
- CI integration (see ADR 0007).

The release-lifecycle layer (the "B" layer) — tag, gh-release, strict quality gating — is composed externally by the user. Typical composition: a Makefile recipe (see `templates/Makefile.kicad`) that runs `kproj` then `git tag` then `gh release create`. A future `kproj release` sibling subcommand could absorb (B) work if the Makefile pattern proves too thin, but it is not v1 scope.

### Vocabulary

- **release** — the conceptual (project, board_rev) pair. EAGLE-era meaning carried forward.
- **publish** — verb. "Make the current snapshot of a release visible on the SPCoast site." Also the name of kproj v1's pipeline-ending step.
- **(A) layer** — kproj v1. Jekyll publication of a snapshot.
- **(B) layer** — release-lifecycle work composed externally (tag + gh-release). Out of v1.

A given kproj invocation **publishes** but does not necessarily mark a **release** — the release-event semantics (tag presence) live entirely in (B).

## Consequences

### Positive

- Smaller v1 surface area; faster delivery.
- Clearer mental model: one tool, one concern.
- The two cadences (publish-often vs. release-once) can move independently. Common case: 5–10 publishes per fab cycle as the user iterates on metadata; one release at the end.
- Quality-bar split: (A) is "show what's there"; (B) is "this is gated". Confusing them was the source of significant grilling-phase complexity.

### Tradeoffs

- Users must compose two tools (kproj + git/gh) for the full release. Mitigated by `templates/Makefile.kicad` shipping `make release` as a one-liner.
- The split could feel artificial to a user who expects "release tools" to do both.

### Reversibility

The conceptual split is hard to reverse once the codebase embeds it (every step module assumes publish-only). But adding (B) back later as a sibling subcommand (`kproj release`) is mechanical: import the same Workflow modules, add tag/gh-release steps, gate on DRC clean + working-tree clean. The decision here is "not in v1", not "never".
