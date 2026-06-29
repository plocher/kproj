# Architecture Decision Records

kproj's architectural decisions, recorded as ADRs (Architecture Decision Records). Format follows jBOM's convention: `NNNN-title.md`, with `Status: Accepted | Proposed | Superseded`.

## kproj-specific ADRs

| # | Title | Status |
|---|---|---|
| [0001](0001-inherit-jbom-architectural-patterns.md) | Inherit jBOM's Architectural Patterns | Accepted |
| [0002](0002-jekyll-publisher-scope-a-b-split.md) | Jekyll-Publisher Scope — (A)/(B) Split | Accepted |
| [0003](0003-jbom-separation-read-not-invoke.md) | jBOM Separation — Read, Don't Invoke | Accepted |
| [0004](0004-show-what-is-provided-audit-policy.md) | "Show What Is Provided" Audit Policy | Accepted |
| [0005](0005-writetracker-transactional-site-writes.md) | WriteTracker for Transactional Site-Repo Writes | Accepted |
| [0006](0006-library-shape-boundary-discipline.md) | Library-Shape Boundary Discipline | Accepted |
| [0007](0007-local-cli-v1-ci-deferred.md) | Local-CLI v1, CI Integration Deferred | Accepted |
| [0008](0008-ibom-direct-script-invocation.md) | iBOM via Direct Script Invocation | Accepted |
| [0009](0009-kicad-install-locator.md) | KicadInstallLocator Utility | Accepted |

## Inherited from jBOM (cited, not duplicated)

ADR 0001 documents the inheritance contract. The source-of-truth lives in `~/Dropbox/KiCad/jBOM/docs/architecture/adr/`.

| jBOM ADR | Title | Adoption |
|---|---|---|
| 0006 | Production Folder + ProjectMetadata + Diagnostic Collection | wholesale |
| 0011 | Project-Centric Design | wholesale |
| 0013 | Domain-Centric Design (layers + patterns + naming) | wholesale |
| 0014 | Job Contracts (`<Verb>Request` / `Result` shape) | partial |
| 0008 | Unified Config Schema | NOT adopted (intentionally simpler) |
| 0007 | PCM Packaging | N/A (kproj is not a KiCad plugin) |

## Cross-references

The kproj ADRs reference each other and jBOM ADRs in their `Related:` headers. Reading order for someone new to the codebase:

1. **ADR 0001** — for the overall inheritance contract.
2. **ADR 0002** — for the v1 scope (what kproj is and isn't).
3. **ADR 0003** — for the jBOM separation (how kproj relates to jBOM at runtime).
4. **ADR 0004** — for the "show what is provided" policy that shapes audit / DRC / ERC behaviour.
5. **ADR 0006** — for the code-structure discipline that shapes every module.
6. **ADR 0005**, **ADR 0007** — for the more focused decisions (transactional writes, local-CLI scope).
7. **ADR 0008**, **ADR 0009** — for the iBOM invocation and KiCad install discovery (both adopted during Phase 4 resolution; ADR 0008 supersedes a plan-level decision).

## Process

New ADRs are added as part of feature work, on the relevant feature branch, and committed alongside the code they justify. ADR-worthy decisions (per the `grill-with-docs` criteria) are:

1. **Hard to reverse** — the cost of changing your mind later is meaningful.
2. **Surprising without context** — a future reader will wonder "why did they do it this way?"
3. **The result of a real trade-off** — there were genuine alternatives and you picked one for specific reasons.

If any of the three is missing, the decision belongs in `docs/GLOSSARY.md` (if it's a term), `docs/PRD.md` (if it's user-facing scope), `docs/DESIGN.md` (if it's an implementation choice), or code comments — not as an ADR.
