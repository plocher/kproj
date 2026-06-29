# ADR 0001: Inherit jBOM's Architectural Patterns
Date: 2026-06-29
Status: Accepted
Related: jBOM ADR 0006, jBOM ADR 0011, jBOM ADR 0013, jBOM ADR 0014

## Context

kproj is a sibling tool to jBOM (`~/Dropbox/KiCad/jBOM/`) in the KiCad release-publishing ecosystem. jBOM has accumulated substantial architectural ADRs — patterns proven across its CLI + plugin adapter surfaces — that kproj would otherwise have to reinvent from scratch. Same author, same problem domain (KiCad project metadata, fab artifact generation, project resolution), same Python-package shape.

Reinventing equivalent patterns is wasted work and risks divergence where the underlying domain has not actually changed.

## Decision

kproj adopts the following jBOM ADRs **by reference**. The source-of-truth lives in `~/Dropbox/KiCad/jBOM/docs/architecture/adr/`; kproj inherits the decisions without copy-pasting them into its own tree.

### Wholesale adoption

- **jBOM ADR 0011 — Project-Centric Design.** kproj's positional CLI argument resolves projects via `jbom.application.pcb_project_loader.resolve_pcb_input()`. Same semantics: `kproj` (no arg) → CWD; `kproj <dir>/` → that dir; `kproj <basename>` → resolve to project dir; `kproj <path>/<file>.kicad_{pro,sch,pcb}` → find adjacent `.kicad_pro`.
- **jBOM ADR 0013 — Domain-Centric Design.** Layer responsibilities (Domain Model → Domain Services → Application → Interface), naming conventions (`<Verb>Workflow`, `.run(request)` — no `Orchestration` in names), design patterns (Constructor Configuration, Single Responsibility, Service Composition, Adapter, Strategy, Friend Serializer), and the architectural mindset (DDD bounded contexts, ubiquitous language) all carry over directly. kproj's bounded contexts are smaller (Project Snapshot, Audit, Site Repo) but the pattern is the same.
- **jBOM ADR 0006 — Production Folder + ProjectMetadata + Diagnostic Collection.** kproj READS jBOM's `production/` folder convention (its `fab` step is "read + package", not "generate"). kproj's `ProjectMetadata` extends jBOM's shape with `board_rev` / `design_rev` / `status` (per kproj's Phase 2 locked vocabulary). kproj's audit `Finding` is the structurally-equivalent successor to jBOM's `Diagnostic`; the **Diagnostic Collection Principle** applies verbatim ("services always collect and return all diagnostics in the result contract; adapters decide what to display and when").

### Partial adoption

- **jBOM ADR 0014 — Job Contracts.** kproj v1 adopts the `<Verb>Request` / `<Verb>Result` dataclass shape with diagnostics on the result. kproj v1 does NOT adopt the `JobContext` / `JobRunner` / cancellation / capability-flags machinery — those are over-engineered for kproj's single-CLI surface. The event-stream model (`progress` + `diagnostic` events with deterministic ordering) is reserved for the Phase 6+ two-phase architecture (extract → render) deepening.

### Explicitly NOT adopted

- **jBOM ADR 0008 — Unified Config Schema.** kproj's v1 config is intentionally simpler — a single `~/.kproj.yaml` with two keys (`site_repo`, `no_push`). No `extends:`, no `common.kproj.yaml`, no `policy.kproj.yaml`, no per-stanza id resolution. The complexity of jBOM's unified schema is unjustified for kproj's smaller config surface. If kproj's config surface ever grows past ~5 keys with composition needs, revisit.
- **jBOM ADR 0007 — PCM Packaging.** kproj is not a KiCad plugin; it's a CLI tool. The PCM-archive build machinery does not apply. (A future PCM-distributed `kproj-interactive.kicad_jobset` is noted in DESIGN.md as a Phase 6+ deepening, but that's a single resource, not a plugin.)

## Consequences

### Positive

- kproj's architectural surface area is reduced — we inherit decisions instead of relitigating them.
- Codebases stay structurally similar; contributors who know jBOM will recognize kproj's patterns.
- Cross-cutting future improvements (e.g. typed `Diagnostic(severity, message)`) can be coordinated between the two projects.

### Tradeoffs

- Cross-repo dependency: kproj's ADRs reference jBOM's ADRs by path. If jBOM relocates or significantly revises an ADR, kproj's ADR 0001 may need to update.
- Mitigation: jBOM is maintained by the same author; coordination is internal. Should jBOM ever go elsewhere, kproj snapshots the referenced ADRs at that point.

### Deviations are documented per-ADR

When kproj diverges from a jBOM pattern, the divergence gets a kproj-specific ADR explaining why. ADR 0006 (library-shape boundary discipline) is one such — jBOM has a similar mindset but no dedicated ADR for it, so kproj formalizes it here.
