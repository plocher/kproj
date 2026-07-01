# kproj — Glossary
The canonical vocabulary used across the kproj codebase, ADRs, PRD, DESIGN doc, and source code.

This document is **terminology-only**. It captures terms and their definitions. Implementation mechanics, contracts, and step-by-step specifications live elsewhere:

- Architectural decisions → `docs/adr/`
- v1 user-facing requirements → `docs/PRD.md`
- v1 implementation specs → `docs/DESIGN.md`

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

## Domain model types

### ProjectInfo
The dataclass holding what we know about a project at a point in time: name, design_rev, board_rev, designer, tagline, dates, company, tags, status. Pure facts. No I/O. No Jekyll knowledge. Produced by `KicadProjectReader`.

### AnalysisInfo
The dataclass holding findings from analyzing a project: a list of `Finding`s plus counts per severity. Pure data. Produced by `MetadataAnalyzer` and `DesignAnalyzer`; may be merged into a single `AnalysisInfo` by the consuming Workflow.

### Publication
The bundle ready for site emission: a `ProjectInfo`, an `AnalysisInfo`, asset references (paths + metadata for the `images[]` and `artifacts[]` front-matter fields), and the body markdown. Pure data — no I/O, no Jekyll-specific YAML rendering (that happens in `SitePublisher`). When Phase 6+ adds a two-phase architecture (extract → render), `Publication` is the JSON-serializable intermediate that flows between phases.

### Finding
A single quality-lint finding. Frozen dataclass with: `severity`, `project`, `field`, `value`, `reason`, `location_hint`. Carries enough info for stderr / Markdown table / front-matter / JSON formatters to render appropriately. Per jBOM ADR 0006's Diagnostic Collection Principle.

### Severity
Enum with values `error` and `warning`. DRC/ERC findings additionally use `exclusion` to preserve KiCad's GUI-marked exclusions; the metadata audit itself uses only `error` and `warning`.

## Domain services

The eleven services that compose kproj v1's domain layer. Each is a noun naming a *kind of thing*, not a verb naming an action. See *Naming conventions* and *Producer Pattern* below for the shared shape.

### KicadProjectReader
Reads project files on disk → `ProjectInfo`. Wraps jBOM's parsing library (`pcb_reader`, `schematic_reader`, `sexp_parser`); houses the interim `(comment N "...")` walker until jBOM's upstream PR adding COMMENT/text_variables parsing lands.

### MetadataAnalyzer
Analyzes a `ProjectInfo` (and adjacent project files) for metadata-quality findings. In-process heuristics: placeholder values, missing `${COMMENT9}`, SCH/PCB title-block disagreements, date-format violations, designer-format violations, etc. Produces metadata `Finding`s.

### DesignAnalyzer
Analyzes a KiCad project for design-quality findings. Delegates to `kicad-cli pcb drc` and `kicad-cli sch erc`; parses JSON output into `Finding`s. KiCad's GUI-marked exclusions are preserved via `Severity.exclusion`.

### PcbExporter
Exports PCB content to target file formats. v1 targets: PNG (via 3D render, top + bottom sides) and STEP. Future targets (SVG, GLB, etc.) extend per-method without changing the service.

### SchematicExporter
Exports schematic content to target file formats. v1 targets: SVG (root sheet only) and PDF (all sheets, multi-page).

### IbomGenerator
Generates the interactive HTML BOM artifact. The output adds presentation structure (interactivity, embedded JavaScript) beyond pure format conversion — hence `Generator` rather than `Exporter`. Includes a pre-flight check that the iBOM plugin script is installed at the expected KiCad PCM path.

### FabPackager
Packages an existing `<project_dir>/production/` directory's contents (jBOM's outputs) into `<P>-<R>.fab.zip`. Uses `ZipArchiver`.

### SourcePackager
Packages non-derived KiCad files from the project tree into `<P>-<R>.source.zip`. Uses `ZipArchiver`.

### ZipArchiver
Low-level zip primitive. Takes source paths + output path; produces a zip. Domain-agnostic. Used by both `FabPackager` and `SourcePackager`. Matches jBOM ADR 0006's `ZipArchiver`.

### SitePublisher
Writes a `Publication` into the local SPCoast Jekyll site repo: per-version markdown, per-version assets, per-project aggregator. Houses the Jekyll-specific YAML rendering. Coordinates with `ChangeJournal` for transactional writes; commits + pushes the site repo at end.

### ChangeJournal
Transactional write log. Context manager that records every file kproj creates or modifies in the site repo; rollback restores the pre-run state on exception (ADR 0005). Domain-agnostic (any tool writing to a git repo could use it) — candidate for future extraction per ADR 0006.

## Naming conventions

Service classes are named by a `-Suffix` that encodes the *functional concept*, not the implementation. Subprocess-vs-in-process, ray-trace-vs-SVG, etc. do not change the suffix.

| Suffix | Functional meaning |
|---|---|
| `-Reader` | reads existing artifact → domain dataclasses (internalization) |
| `-Analyzer` | inspects existing content → `Finding`s (regardless of in-process heuristics vs delegation to external tools) |
| `-Exporter` | converts content to another file format (externalization with content equivalence) |
| `-Generator` | produces new artifact with structure or presentation beyond pure format conversion |
| `-Packager` | bundles existing artifacts into an archive |
| `-Archiver` | low-level archive primitive |
| `-Publisher` | writes content to a target system (with side effects on that system) |
| `-Journal` / `-Tracker` | records state changes for replay/rollback |

Application-layer orchestrators (Workflows) follow jBOM ADR 0014's convention: `<Verb>Workflow` class with `.run(<Verb>Request) -> <Verb>Result` method. The Verb is the canonical action name (`Publish`, `Audit`, etc.).

## Producer Pattern

Most kproj services follow a common shape — the **Producer Pattern** — regardless of suffix:

- **Constructor** takes configuration options (immutable; behavior fixed at construction time).
- **Single primary method** named for the domain operation (`.read()`, `.analyze()`, `.export_*()`, `.generate()`, `.package()`, `.archive()`, `.publish()`).
- **Typed inputs** — paths or dataclasses, never `**kwargs`.
- **Typed result** that includes `diagnostics: tuple[Finding, ...]` per jBOM's Diagnostic Collection Principle.
- **No side effects** beyond the documented output (file at a known path, or returned dataclass).

`ChangeJournal` is the lone non-Producer service: it is a Tracker (context manager that records writes), not a Producer of a domain artifact.

## Audience framing

The SPCoast site is a **developer-time tool** as well as a customer-facing production catalogue. Releases with audit or DRC/ERC findings are intentionally visible — a developer reading the site sees current state, not a polished-final-only view. Strict quality gating belongs in the (B) release-lifecycle layer (out of v1 scope; see ADR 0002 and ADR 0004).
