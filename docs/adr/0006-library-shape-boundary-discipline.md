# ADR 0006: Library-Shape Boundary Discipline
Date: 2026-06-29
Status: Accepted
Related: ADR 0001 (jBOM patterns), jBOM ADR 0013 (Domain-Centric Design)

## Context

kproj is primarily a CLI application: end users invoke `kproj` from the shell or a Makefile. But within the codebase, several components have **library-shape** concerns even though no library is being extracted:

- The `Finding` + audit-formatter pattern (per ADR 0001's inheritance of jBOM's Diagnostic Collection Principle).
- The `WriteTracker` rollback pattern (ADR 0005).
- The `kproj.kicad.metadata` reader (interim — will collapse when the jBOM upstream PR adding `(comment N "...")` parsing lands).
- The front-matter generator that emits SPCoast Jekyll version markdown.
- Per-step Workflow classes (`RenderWorkflow`, `IbomWorkflow`, `FabWorkflow`, `PublishWorkflow`) following jBOM ADR 0014's `<Verb>Workflow`/`.run(request)` shape.

Two ways to write these:

1. **Application-style**: tight coupling with `argparse`, `sys.argv`, `sys.exit`, global state, "just make the CLI work". Fast to write; hard to test in isolation; hard to extract later.
2. **Library-style**: pure functions where possible, dataclasses, no CLI/argparse coupling, no global state, callable from any Python entry point (CLI, future test harness, future second consumer). Slower to write upfront; testable in isolation; extractable later.

## Decision

kproj v1 adopts **library-shape boundary discipline** as a codebase-wide mindset, *without* committing to actually extracting any library product. The discipline shapes how modules are written; the library extraction may never happen.

### Concrete rules

- **`argparse` is confined to `src/kproj/cli.py`.** No step module, no audit module, no Workflow class imports argparse or references `sys.argv`. CLI parsing translates argv → typed Request dataclass; everything downstream operates on dataclasses.
- **`sys.exit` is confined to `cli.py`.** Step modules return result objects (with exit-code hints in the result); `cli.py` maps results → process exit codes.
- **No global state.** No module-level mutable variables. No "current project" globals. Each Workflow takes a Request, returns a Result, no implicit context.
- **Dataclasses over magic dicts.** All Request/Result/intermediate-data shapes are frozen dataclasses with explicit types. Per jBOM ADR 0013's Value Object pattern.
- **Pure functions where possible.** Pure parsing, pure transformation, pure formatter functions. Side effects (file writes, subprocess invocations) are isolated and explicit.
- **Domain language in module names.** Per jBOM ADR 0013's naming convention: `RenderWorkflow` not `RenderOrchestrator`; `.run(request)` not `.execute()` or `.orchestrate()`; module file `render_workflow.py` not `render_orchestration.py`.
- **No I/O in domain-model code.** `Finding` / `ProjectMetadata` / `VersionFrontMatter` dataclasses live in the domain-model layer and have zero file-system or subprocess dependencies. I/O happens in services/Workflows that consume the domain model.

### What this is NOT

- **NOT a commitment to extract a `kproj-lib` package.** No v1 publication of kproj-internals to PyPI. No documented stable public API.
- **NOT design-by-contract or interface-segregation purism.** No abstract base classes for theoretical "what if someone else implements this" cases. We're disciplined, not zealous.
- **NOT a freeze on internal refactoring.** Library-shape modules are still kproj-internal; we can refactor them freely without versioning concerns.

### Why this discipline NOW, before any extraction need

The mindset shapes every module written. Reversing it later means rewriting modules with looser coupling than they originally had — net negative work. Adopting the discipline upfront costs only a small amount of authorial care; reaping later (extraction, easier testing, easier future jBOM upstream contributions) is essentially free.

The discipline matches jBOM's evolution: jBOM's internals are library-quality not because there was a planned library extraction, but because the author wrote them that way. kproj follows the same path; jBOM ADR 0013 is the architectural sibling.

## Consequences

### Positive

- Step modules and audit module are unit-testable in isolation (no CLI context needed; just construct a Request, call `.run()`, assert on Result).
- Future opportunistic extractions are mechanical:
  - If `Finding` + formatter pattern proves useful to another tool: move into a shared `kproj-diag` package or contribute upstream to jBOM.
  - If `WriteTracker` proves useful: move into a shared `git-write-tracker` package.
  - If `kproj.kicad.metadata` becomes redundant after jBOM's upstream PR: delete it.
- Codebase reads like jBOM. Contributors familiar with one are productive in the other.
- Refactoring stays cheap because the boundaries are clean.

### Tradeoffs

- Upfront cost: every step module needs a Request dataclass, every result needs a Result dataclass. Slightly more code than the "just take CLI args and write files" style.
- Discipline overhead during PR review — reviewers need to enforce no-argparse-outside-cli.py, no-globals, etc.
- May feel over-engineered for kproj's small v1 surface. Mitigation: jBOM ADR 0013's patterns are well-documented; the upfront cost is bounded.

### Reversibility

Reversing this discipline mid-project means rewriting modules to tighten coupling — which nobody would deliberately do. The decision is sticky by nature; that's the point. If at some future date "library-shape was overkill" becomes obvious, we can relax specific rules in subsequent ADRs without rewriting the codebase.
