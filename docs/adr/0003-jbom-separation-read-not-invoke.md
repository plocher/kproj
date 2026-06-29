# ADR 0003: jBOM Separation — Read, Don't Invoke
Date: 2026-06-29
Status: Accepted
Related: ADR 0001 (inherit jBOM patterns), jBOM ADR 0006 (production folder)

## Context

jBOM provides `FabricationWorkflow` — a Python-callable workflow that runs the user's chosen fabricator profile (jlc/pcbway/seeed/generic) and produces gerbers, BOM, POS, and a fab-house-ready zip into a `production/` folder.

kproj needs those artifacts to assemble its `<P>-<R>.fab.zip` for the site. The naive approach is to `import jbom.application.fabrication_orchestration.FabricationWorkflow` and call `.run(FabricationRequest(...))` inside kproj's `fab` pipeline step.

The naive approach has problems:
- **Cadence coupling**: kproj publishes many times per fab cycle (status changes, metadata fixes, audit-warning iteration). Re-running jBOM on every kproj invocation is wasteful and slow.
- **Fabricator choice coupling**: kproj would need to thread `--fabricator <name>` through its CLI, even though that's a jBOM concern.
- **Configuration coupling**: jBOM's `.jbom.yaml` config schema (ADR 0008) would leak into kproj's surface.
- **Composability**: users with non-Makefile workflows (just running jbom and kproj manually) would have to learn that kproj re-runs jBOM internally — surprising.

## Decision

kproj does NOT invoke jBOM's `FabricationWorkflow`. The fab step is **read + package**, not generate.

### Composition contract

1. **User invokes jBOM separately** — via Makefile (`make fab` → `jbom fab --fabricator <name>`), manual command, or any other workflow.
2. **jBOM writes outputs** to `<project_dir>/production/` per jBOM ADR 0006's production folder convention.
3. **kproj reads those existing files** when its fab step runs:
   - `<project_dir>/production/bom.csv` (jBOM's `bom` artifact)
   - `<project_dir>/production/pos.csv` (jBOM's `pos` artifact)
   - `<project_dir>/production/<title>_<rev>.zip` (jBOM's `gerber` artifact — the gerber-pack)
4. **kproj assembles `<P>-<R>.fab.zip`** containing exactly three files: `bom.csv` + `pos.csv` + `gerbers.zip`.
5. **kproj copies** the assembled zip to `<site_repo>/versions/<Project>/<board_rev>/`.

### What kproj still uses from jBOM

kproj retains jBOM library imports for **parsing only**, not for fabrication generation:
- `jbom.application.pcb_project_loader.resolve_pcb_input` — project resolution (ADR 0011).
- `jbom.services.pcb_reader.DefaultKiCadReaderService` — title-block read from `.kicad_pcb`.
- `jbom.services.schematic_reader.SchematicReader` — title-block read from `.kicad_sch`.
- `jbom.common.sexp_parser.load_kicad_file` — raw S-expression walking (used to extract `(comment N "...")` until jBOM upstream PR lands).
- `jbom.common.types.TitleBlockMetadata`, `jbom.common.types.Diagnostic` — domain dataclasses.

These are jBOM-as-library; `FabricationWorkflow` is jBOM-as-tool. The split is jBOM's natural layering.

### Audit findings about `production/`

kproj's audit module checks the state of `<project_dir>/production/` and surfaces:
- **warning**: `production/` missing or empty — fab artifacts not generated. kproj publishes the rest of the snapshot; `fab.zip` is omitted from the version page's `artifacts[]` list.
- **warning**: `production/` outputs stale — any of the production files have an mtime older than `<project_dir>/<basename>.kicad_pcb`. User probably forgot to re-run `jbom fab` after bumping the board.

Per ADR 0004 (show what is provided), these are never blocking.

## Consequences

### Positive

- kproj and jBOM evolve independently. Releasing a new kproj version does not require coordinating with jBOM, and vice versa.
- Publish cadence (~5–10 per fab cycle) decouples from fab cadence (~1 per design iteration).
- kproj's CLI surface is smaller (no `--fabricator` flag; no fabricator selection logic).
- User's `make fab` recipe records the fabricator choice explicitly; reproducibility is in the user's hands, not hidden inside kproj.

### Tradeoffs

- User responsibility: kproj cannot run jBOM for the user. If the user forgets to run `make fab` before `make publish`, kproj publishes without fab.zip and surfaces a warning. Acceptable.
- Staleness window: if the user bumps the board but doesn't re-run jBOM, the next `kproj` publishes the old fab.zip with the new board. The mtime audit catches this; warning is surfaced. Still a possible footgun.
- Cannot run jBOM as part of a hypothetical kproj-CI invocation (Phase 6+) without making jBOM available in the CI environment. Acceptable — same prereq as the user's local env.

### Reversibility

Adding jBOM back as an in-process invocation later (e.g. `kproj --auto-fab` flag) is mechanical — just import `FabricationWorkflow` and call `.run()`. The decision here is the separation discipline for v1; the door isn't closed.
