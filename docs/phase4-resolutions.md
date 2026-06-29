# Phase 4 Resolution Tracking
Maps each Phase 4 review finding (`review/phase-4` branch, commit `61f31ef`, `docs/phase4-review.md`) to its resolution status.

## Summary
- 6 BLOCKER findings — all resolved.
- 10 MAJOR findings — all resolved.
- 4 QUESTION findings — all resolved (user input + architect decisions).
- 2 MINOR findings — all resolved.

## BLOCKERs (commit `42f86d6`)
| # | Finding | Resolution |
|---|---|---|
| B1 | Direct iBOM script execution contradicts the locked jobset decision | **Plan was stale.** User confirmed `kicad-cli jobset run` requires a live KiCad instance, incompatible with ADR 0007's non-interactive use case. ADR 0008 (iBOM via direct script invocation) supersedes the plan's locked decision. iBOM script path discovered by `common.kicad_install.find_ibom_script()` (ADR 0009). DESIGN's pipeline + IbomGenerator contract updated. Plan annotated. |
| B2 | Site emission contract is aspirational, not consumable by the current Jekyll site | DESIGN front-matter shape rewritten to match real `_layouts/eagle.html` contract: `layout: eagle` (not `kicad`), absolute `/versions/<P>/<R>/...` paths, `publish: true` gate, `iskicad: true|'obsolete'` discriminator. Site-setup PR coupling spelled out: `_data/tags.yml` extension, eagle.html status-branch extension for new taxonomy values, electronics.html repurpose. |
| B3 | Asset generation escapes ChangeJournal rollback | Pipeline restructured: ChangeJournal opens before step 7 (artifact generation), covers every site-repo write including exporter output. Per ADR 0005, mid-step exceptions in step 7 trigger full rollback. |
| B4 | Config layer leaks argparse outside `cli.py` | `ConfigOverrides` dataclass added; `cli.py` translates `argparse.Namespace` → `ConfigOverrides` before calling `load_config()`. `config.py` no longer imports argparse, per ADR 0006. |
| B5 | Project resolution contract misstates the jBOM API and returned artifact | `KicadProjectReader.resolve` now returns kproj-owned `ResolvedProject` dataclass wrapping jBOM's `ResolvedPcbProject`. All downstream services accept `ResolvedProject`, never bare `Path`. |
| B6 | FabPackager looks for the wrong production zip | FabPackager discovers jBOM's `<title>_<rev>.zip` by naming convention (or single-zip rule with ambiguity warning), normalizes the entry name to `gerbers.zip` inside `<P>-<R>.fab.zip`. Source filename not required to be `gerbers.zip`. |

## MAJORs (commit `b9b52ea`)
| # | Finding | Resolution |
|---|---|---|
| M1 | COMMENT9/status source side conflicts with the locked metadata precedence | DESIGN gains a new "Metadata precedence" section with per-field canonical/fallback table. PCB canonical for `title`/`company`/`rev`/`date`; SCH canonical for `comment2`/`comment3`/`comment9`; `comment1` either-side. PRD Story 6 updated to direct edits to the SCH title-block. |
| M2 | Private-skip semantics conflict with exit codes and preflight ordering | Pipeline restructured: status detection (step 4) now precedes iBOM script discovery + site cleanliness check (step 5). Private projects never fail preflight on those conditions. Exit code uniformly applies global rule: 0 clean, 1 with findings (user direction). PRD Story 7 updated; clarified prospective-only semantics + out-of-scope retroactive unpublish. |
| M3 | Schematic SVG export treats an output directory as a file and omits root-sheet selection | SchematicExporter rewritten to use temp output directory + `--pages` selector + post-process discover-and-move into final asset filename. Contract test layer (M9) verifies the kicad-cli surface. |
| M4 | New-release detection ignores body content, README content, asset presence, and asset freshness | New-release detection section rewritten. Comparison target now includes front-matter + body markdown + project page body + asset manifest (presence + mtime vs source). noop only when all four match. |
| M5 | Side-effect service result shapes drop diagnostics despite the Producer Pattern | `ExportResult` dataclass added. PcbExporter, SchematicExporter, IbomGenerator, FabPackager, SourcePackager, ZipArchiver all return ExportResult uniformly (path + diagnostics + command + elapsed_seconds + skipped). |
| M6 | kicad-cli locator/version preflight is incomplete | ADR 0009 introduced `common/kicad_install.py` utility with `find_kicad_cli`, `find_plugins_dir`, `find_ibom_script`, `kicad_version`. PcbExporter, SchematicExporter, DesignAnalyzer constructors take `kicad_cli: Path`. Preflight reports binary + version. |
| M7 | Source archive cannot promise self-contained KiCad opening while excluding external libraries | PRD Story 17 weakened: source.zip contains project sources + `SOURCE_README.md` listing external-library prerequisites. SourcePackager scans fp-lib-table / sym-lib-table / pcb / sch for external refs, emits reproducible manifest. User flagged the open experimental finding about KiCad's actual behavior — tracked as discussable sub-project in plan. |
| M8 | Subprocess timeout, hang, and signal behavior is unspecified | New `common/subprocess_runner.py` utility section added. Per-step timeouts (120s kicad-cli + iBOM, 30s git). Handles `TimeoutExpired`, `KeyboardInterrupt`, `SIGTERM`. SubprocessTimeoutError + SubprocessFailedError + SubprocessResult dataclass. |
| M9 | Test strategy can validate mocks instead of external contracts | New contract test layer (`tests/contract/`) between unit and Behave. 8 contract test files validate kicad-cli + iBOM external surfaces against the locally-discovered binary. `@pytest.mark.skipif` gated. |
| M10 | Audit exception rules are not implementable enough to avoid false positives and false negatives | `rev_relation` audit rule rewritten as executable regex `^<escaped sch_rev>[A-Z]+$`. Date interval gets a concrete 90-day threshold. Examples added (3.0B accepted; 3.0.1, 3.0-beta, 3.1 rejected). |

## QUESTIONs (resolved per user input + commit `b9b52ea` plus the final MINORs+QUESTIONs commit on `feat/phase-3-prd`)
| # | Question | Resolution |
|---|---|---|
| Q1 | Is `--site-repo` accepted or rejected? | User direction: **keep `--site-repo`**. PRD + DESIGN updated; CLI surface in PRD Further Notes lists six flags. DESIGN CLI mechanics + config layer document the highest-precedence position. ADR 0007 already listed it; no edit needed. |
| Q2 | What should `private` do to an already published version? | User direction: **prospective only** (option 1). Don't publish future snapshots; leave existing site entry untouched. Retroactive unpublishing is out of v1 scope (deferred discussable sub-project added to plan). PRD Story 7 updated. |
| Q3 | What is the "standard asset set" when `production/` is missing? | Architect decision: fab.zip is conditional. PRD Story 1 gains a GIVEN clause for fresh production output; Story 16 gains a GIVEN clause requiring production was fresh at publish time. fab.zip omission is a warning Finding, not a publish failure. |
| Q4 | When does `comment9_missing` become an error, and does empty still default to `active`? | Architect decision: v1 = warning + emit `active` default per locked Phase 1 closeout. Promotion to `error` deferred until after corpus bulk-populate (future ADR). DESIGN audit heuristic table updated. |

## MINORs (final MINORs+QUESTIONs commit on `feat/phase-3-prd` — see `git log` for the hash)
| # | Finding | Resolution |
|---|---|---|
| Mn1 | `--dry-run` is not milliseconds if it runs DRC/ERC | DESIGN dry-run section: "milliseconds" claim dropped. Wall-clock dominated by DRC/ERC subprocess invocations (seconds per project). |
| Mn2 | Proposed `kicad` and company-derived tags are not in the current allowed tag set | DESIGN front-matter shape annotated: non-allowlisted tags emit to front-matter but don't render until site-setup PR extends `_data/tags.yml`. Tracked as part of site-setup PR scope (already in Phase 1 closeout) + discussable sub-project for ongoing allowlist maintenance. |

## Commit references
- `42f86d6` — BLOCKERs (+ ADR 0008, ADR 0009).
- `b9b52ea` — MAJORs.
- See `git log feat/phase-3-prd` for the final MINORs+QUESTIONs commit hash.

## Phase 4 outcome
Phase 4 review surfaced 22 substantive findings; all addressed before Phase 5 issue breakdown. Two ADRs added (0008, 0009). Plan got three updates: iBOM jobset superseded, jBOM PR #2 demoted, two new discussable sub-projects (unpublish-mistakenly-published, external-library bundling experiment). Architect-driven resolution for all DESIGN drift; user input resolved the four QUESTION-level decisions; one BLOCKER (iBOM) resolved against the original plan because the user's lived experience contradicted the locked decision.

The review branch `review/phase-4` is preserved unchanged as the source-of-truth for Phase 4 findings; this document tracks resolution on `feat/phase-3-prd`.
