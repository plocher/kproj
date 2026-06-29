# kproj — Domain Glossary
Source of truth for the language used in the plan, code, and docs.
Populated incrementally during Phase 2 grilling. Implementation details and decisions live elsewhere (the plan, the ADRs); this file is glossary-only.
## Terms
### release
The (project, PCB-revision) pair. EAGLE-era meaning: "the design was released from development and sent to a fab house". Each KiCad project produces many releases over its lifetime as the board layout iterates. **In kproj v1, a `kproj` invocation does not assert a release event** — it publishes a *point-in-time snapshot* of the project to the site. The release event itself (tag + gh-release in the project repo) is (B) release-lifecycle work, out of v1 scope. The conceptual identity `(project, board_rev)` still anchors what kproj publishes.
### version
The Jekyll artifact at `_versions/<Project>/<Revision>.md` representing a snapshot of one release on the SPCoast site. Tied 1:1 to KiCad PCB `${REVISION}` (the `<DESIGN><LETTER>` form, e.g. `3.0B`). Each kproj invocation writes exactly one version entry. The SCH `${REVISION}` (the `<DESIGN>` form, e.g. `3.0`) is recorded in the version's front-matter as `design_rev` but does not key the version — multiple PCB layout iterations of the same SCH design are distinct versions.
### publish
Verb: "make the current snapshot of a release visible on the SPCoast site". Also the name of the v1 pipeline step that writes the version entry + assets into the Jekyll site repo and pushes the result. (Renamed from the plan's earlier `site` step.)
### tag
Git tag in the project's own repo identifying a release. **Out of kproj v1 scope** — handled by the user's existing Makefile / manual `git tag` workflow. Defined here for vocabulary clarity; (B) release‑lifecycle work may reintroduce a `kproj release` sibling subcommand or Makefile recipe later. **Tag format** (locked for when (B) lands): `release/<board_rev>` (slash‑namespaced). Examples: `release/1.0B`, `release/3.0A`. The `release/` prefix gives a clean `git tag -l "release/*"` query for "all kproj‑era release tags".
### gh-release
`gh release create` artifact in the project's own repo, keyed on the `release/<board_rev>` tag from above. **Out of kproj v1 scope** — handled by the user's existing Makefile / manual `gh release create` workflow. Defined here for vocabulary clarity.
### status
A release's lifecycle attribute, sourced from `${COMMENT9}` in the title block per extended SPCoast convention. Closed taxonomy (Phase 2 locked):
* `experimental` — first small-quantity fab; design under validation. Same design files as `active`; confidence differs, not content.
* `active` — design validated; in regular production use. Default for established projects (bulk-populate target).
* `retired` — no longer in active use; archived for reference.
* `broken` — known defects; do not fabricate. Site renders with warning callout.
* `replaced-by:<project-dir>` — superseded by another project. `<project-dir>` is the directory name (unique even when `.kicad_pro` basenames collide — e.g. `Brakeman-BLUE`, not `Brakeman`).
* `private` — release exists; `publish` step skipped. cpOD pattern.

Experimental→active is a confidence transition, **not a new release**: design files are identical between the first small-qty fab and subsequent quantity fabs; only the status value changes. User updates `${COMMENT9}` manually when validation completes; CI re-running kproj propagates the new status to the site via the existing version entry (idempotent metadata update).

Audit rules:
* Missing `${COMMENT9}` is an audit error once the corpus is bulk-populated.
* Value outside the closed taxonomy is an audit error.
* `replaced-by:<X>` where `<X>` does not match an existing project directory under `~/Dropbox/KiCad/projects/` is an audit warning.
### design_rev / board_rev
`design_rev` is the SCH `${REVISION}` (the `<DESIGN>` form, e.g. `3.0`). `board_rev` is the PCB `${REVISION}` (the `<DESIGN><LETTER>` form, e.g. `3.0B`). The audit enforces `board_rev startswith design_rev + zero-or-more letters` — any other relationship is a logical error in the title-block content. Both are emitted into front-matter so the future hierarchical layout can group versions by `design_rev`.
### v1 runtime model
kproj v1 is a **local CLI tool**, invoked manually by the user against a KiCad project on disk. Writes to a local checkout of the SPCoast site repo (path configurable; default `~/Dropbox/eagle/SPCoast.github.io`).

**kproj DOES do the site-repo git workflow** — stage, commit, push. This is necessary because the whole point of `publish` is getting the content to the public site, and that requires pushing the site repo to its remote. Per-project repos are read-only to kproj v1; the site repo is read-write + pushed.

**Pre‑flight site‑repo cleanliness check**: before any writes, kproj runs `git -C <site_repo> status --porcelain`. Non‑empty → hard‑fail with `kproj: site repo at <path> has uncommitted changes; commit/stash/clean before running kproj` (exit code 2). Prevents kproj's writes from mixing with user‑pending edits. `--dry-run` is exempt (no writes happen anyway).

**Corpus batching via `--no-push`**: default `kproj` commits AND pushes the site repo. The `--no-push` CLI flag (or `KPROJ_NO_PUSH=1` env var) commits but skips the push. Batch usage:
```bash path=null start=null
for project in ~/Dropbox/KiCad/projects/*/; do KPROJ_NO_PUSH=1 kproj --project "$project" || echo "FAILED: $project"; done
git -C ~/Dropbox/eagle/SPCoast.github.io push
```
N commits, 1 push. GitHub Pages rebuilds once, not N times.

CI / GitHub-Actions integration is a Phase 6+ deepening — out of v1 scope. The cross-repo push problem (project repo's CI runner pushing to the SPCoast site repo with cross-repo PAT credentials, concurrency handling, etc.) is non-trivial and not worth solving until kproj v1 is in use.

**Out of v1**: project-repo git tag creation, `gh release create`, project-repo working-tree-clean preconditions, `--force` flag, CI integration. These belong to (B) the release-lifecycle layer (which may be a Makefile, manual workflow, or a future `kproj release` sibling subcommand — to be scoped post-v1).
### config — global defaults
kproj reads optional defaults from `~/.kproj.yaml` (single dotfile, YAML format). Keys:
* `site_repo` — path to the local SPCoast site repo checkout. Default fallback: `~/Dropbox/eagle/SPCoast.github.io`.
* `no_push` (boolean) — if `true`, suppress the `git push` in the publish step. Default `false`. Useful for batch usage; same effect as `--no-push` CLI flag or `KPROJ_NO_PUSH=1` env var.

Precedence: CLI flag > env var (`KPROJ_*`) > `~/.kproj.yaml` > hardcoded fallback. KiCad env vars (e.g. `KICAD9_3RD_PARTY` for iBOM script discovery) come from the user's KiCad install, not from `.kproj.yaml`.

No `fabricator` key (jBOM owns fabricator selection — see *fab step* below). No `staging_dir` key (no user‑visible staging dir; jBOM's intermediate uses Python's `tempfile.TemporaryDirectory()`, kicad-cli/iBOM write directly to the site repo path).

No per-project config in v1. Project-local `.kproj/config.yaml` auto-discovery deferred until per-project defaults become a real need.
### v1 CLI surface
Final v1 CLI grammar (kept deliberately small — the Phase 2 grilling reduced this from an originally larger surface):

```text path=null start=null
kproj [<project-or-dir-or-file>] [--dry-run] [--no-push] [-v|--verbose] [-d|--debug]
```

* **Positional `<project-or-dir-or-file>`** — mirrors jBOM ADR 0011's project‑centric resolution:
  * `kproj` (no arg) — use CWD as the project directory.
  * `kproj <dir>/` — use the given directory.
  * `kproj <basename>` — resolve to `<basename>/<basename>.kicad_pro` (base‑name → project dir).
  * `kproj <path>/<file>.kicad_{pro,sch,pcb}` — find the `.kicad_pro` in the file's directory.
  Resolution delegates to `jbom.application.pcb_project_loader.resolve_pcb_input()`. No `--project` flag (positional is enough).
* **`--dry-run`** — side‑effect‑free preview (see *dry‑run* section).
* **`--no-push`** — commit but skip `git push` (or `KPROJ_NO_PUSH=1` env var, or `no_push: true` in `~/.kproj.yaml`). Default: push. Used for batch invocation.
* **`-v` / `--verbose`** — adds subcommand executions (`kicad-cli ...`, `git ...`) + their stderr/stdout to kproj's stderr stream. For "why did this fail?" debugging.
* **`-d` / `--debug`** — implementation‑private dev diagnostics. **NOT a committed interface** — output content and format change freely between kproj versions to suit whatever the implementer is currently debugging. No tests assert on its content. No documentation enumerates its lines.

**Default** (no `-v`, no `-d`) — silent unless findings emerge (audit warnings/errors, DRC/ERC findings) or a mechanical failure occurs. A clean publish run prints nothing.

**Explicitly dropped from v1**:
* `--project <path>` flag — positional arg is enough.
* `--step <name>` — total runtime is fast (10–30s for a real board); pipeline modules are already modular without CLI plumbing.
* `--json` — no compelling v1 use case. **Phase 6+ deepening**: reintroduce as part of a *two‑phase architecture* that decouples data gathering from format rendering (e.g. `kproj <project> --json out.json` for extract; `kproj --publish-from-json out.json --format=...` for render). Enables multi‑format output (eagle‑jekyll, future kicad.html rich, hypothetical Hugo/Astro). Not v1.
* `--force` — nothing blocks in v1, nothing to override. Resurfaces in (B) release‑lifecycle if/when implemented.
* `-q` / `--quiet` — `2>/dev/null` handles the silent case.
* `--fabricator <name>` — jBOM owns fabricator selection at jBOM‑invocation time, before kproj runs.
* `--debug=<N>` numeric levels — single flat debug mode. If discrimination becomes useful later, named categories (e.g. `--debug-areas=audit,writes`), not numeric levels.

**CLI parsing library**: stdlib `argparse` (matches jBOM's choice).

**Secrets**: none in v1. kproj does not call the GitHub API; the site‑repo `git push` uses the user's locally‑configured git credentials. If/when (B) lifecycle tool gets built and uses `gh release create` from CI, that tool will own its own PAT story — not kproj.
### new-release detection (internal)
kproj decides what work to do by comparing the project's current PCB `${REVISION}` against the SPCoast site repo's `_versions/<Project>/<board_rev>.md`:
* **Site entry missing** — new release. Full pipeline: `render`, `ibom`, `fab`, `publish`. (Tag and gh-release are out of v1 — see *v1 runtime model* above.)
* **Site entry present, front-matter matches what kproj would emit** — exit 0, no work done.
* **Site entry present, front-matter would differ (e.g. STATUS changed)** — metadata refresh only. Re-emit the version's front-matter into the site repo; do not regenerate assets. Idempotent.

The "experimental → active" confidence transition is the canonical example of the metadata-refresh path.
### release asset set (per `_versions/<Project>/<board_rev>/`)
Files kproj emits for one release, written under the site repo at `/versions/<Project>/<board_rev>/`. Filename token `<P>-<R>` = `<project-basename>-<board_rev>` (e.g. `cpNode-Xiao-68x90-1.0B`).
* `<P>-<R>.top.png` — 3D top render via `kicad-cli pcb render --side top` (default ray tracing, default size). Title in `images[]`: `Top`.
* `<P>-<R>.bottom.png` — 3D bottom render via `kicad-cli pcb render --side bottom`. Title in `images[]`: `Bottom`.
* `<P>-<R>.step` — 3D STEP model via `kicad-cli pcb export step` as part of the `render` step. Listed in `artifacts[]` as a download.
* `<P>-<R>.sch.svg` — **root sheet only** in v1, via `kicad-cli sch export svg`. For single‑sheet projects this is the schematic; for hierarchical projects this is the entry‑point view. Title in `images[]`: `Schematic`.
* `<P>-<R>.sch.pdf` — **full multi‑page PDF** in v1, via `kicad-cli sch export pdf`. All sheets, in KiCad‑rendered order. Listed in `artifacts[]` as a download, NOT in `images[]`. No layout changes needed; eagle.html already iterates `artifacts[]` for download links.
* `<P>-<R>.ibom.html` — Interactive HTML BOM via a direct `subprocess.run` call against the bundled `generate_interactive_bom.py` plugin script (see *iBOM invocation* below). Replaces the static board‑layout SVG (iBOM's interactive board view subsumes it). Listed in `artifacts[]`, not `images[]`; the layout embeds or links to it.
* `<P>-<R>.fab.zip` — fab‑house bundle from jBOM's `FabricationWorkflow`. Unzips to exactly three files: `bom.csv`, `pos.csv`, `gerbers.zip` (gerbers + drill files). No designators file (a KiCad‑era holdover not used by fabricators). Listed in `artifacts[]`.
* `<P>-<R>.source.zip` — KiCad source archive for replication. Non‑derived KiCad files only per the locked source‑snapshot scope: `*.kicad_pro/sch/pcb/sym/pretty/dru/wks`, `fp-lib-table`, `sym-lib-table`, `README.md`, `LICENSE`, `CHANGELOG.md`. Unzips to a directory another KiCad user can open and iterate on. Listed in `artifacts[]`.
* `<P>-<R>.thumbnail.png` (or `.svg`) — small project‑list image, **versioned** (lives in `versions/<Project>/<board_rev>/`, not at the project level). Each version has its own thumbnail; reflects that the rendered image inherently changes between layout iterations (unlike the EAGLE-era hand-drawn abstracts that were revision-stable). Front‑matter on each version page carries `image_path: <P>-<R>.thumbnail.png`. The project-list (`electronics.html`) renders the *latest* version's thumbnail by looking up the latest `_versions/<Project>/...` entry and reading its `image_path`. Recipe deferred to Phase 6: PNG crop of `<P>-<R>.top.png` (~400×400) vs. PCB outline SVG. Tuned against `cpNode-Xiao-68x90` at the project‑list 80×scale during Phase 6.

Not emitted in v1: a static `<P>-<R>.brd.svg` (iBOM's interactive board view replaces it); per‑subsheet SVGs (root‑only in v1; full PDF carries the rest); structured `schematic_sheets[]` front‑matter (no layout consumer in v1); standalone `<P>-<R>.bom.csv` / `<P>-<R>.pos.csv` (both live inside `<P>-<R>.fab.zip`; iBOM provides the interactive BOM surface for site browsing); jBOM's `designators` artifact (holdover); jBOM's `backup` artifact (superseded by `<P>-<R>.source.zip`); standalone DRC/ERC report files (see *fab step + DRC/ERC* below).

The filename convention is independent of the existing EAGLE archive's `<P>-<R>.<type>.<ext>` pattern; the two never appear together (separate sidebar entries, separate landing pages).

**Phase 6 deepening for hierarchical schematics**: when the corpus has projects with non‑trivial hierarchy that justify the work, emit per‑sheet SVGs with hierarchical decimal naming (root=`100`; root's children=`110`/`120`/`130`; `120`'s children=`121`/`122`; etc. — each sheet *instance* gets its own ID even when the sheet *design* is reused, because refdes labels differ per instance), populate a `schematic_sheets[]` structured front‑matter (path / name / parent / hierarchical‑id), and design the display UX (tree‑of‑thumbnails vs. dropdown vs. modal navigator) against a concrete project. Avoid tabs‑under‑tabs against the existing revision tabs in the layout.
### KiCad‑side artifact generation — direct subprocess per step
Each pipeline step that talks to KiCad uses the most natural kicad-cli surface, invoked as a direct `subprocess.run` call. No `.kicad_jobset` is generated, persisted, or consulted in v1 — jobsets are intrinsically GUI‑coupled and don't compose with batch invocation (`for project in ...; do kproj $project; done`), which is a primary use case.
* `render` — `kicad-cli pcb render --side top` + `kicad-cli pcb render --side bottom` (default ray tracing, default size).
* `sch export` — `kicad-cli sch export svg` (root sheet) + `kicad-cli sch export pdf` (all sheets).
* `ibom` — direct `python <ibom-script> --no-browser --no-compression --dest-dir <staging> --name-format "<P>-<R>.ibom" --extra-data-file <pcb> --dnp-field kicad_dnp --extra-fields MPN,Manufacturer --include-tracks <pcb>` (see *iBOM invocation* below).
* `fab` — **read + package** existing jBOM outputs from `<project_dir>/production/` (jBOM is invoked separately by the user via Makefile / `jbom fab`; kproj does NOT call `FabricationWorkflow`). kproj keeps jBOM library imports for **parsing only** (`jbom.application.pcb_project_loader`, `jbom.services.pcb_reader`, `jbom.services.schematic_reader`, `jbom.common.sexp_parser`, `jbom.common.types`).
### iBOM invocation
The `ibom` step is a direct `subprocess.run` against the bundled `generate_interactive_bom.py` plugin script. No jobset wrapper.
* **Pre‑flight check**: kproj verifies `${KICAD9_3RD_PARTY}/plugins/org_openscopeproject_InteractiveHtmlBom/generate_interactive_bom.py` exists. Missing → **hard‑fail** with `kproj: iBOM plugin not installed at <expected-path>. Install via KiCad's Plugin and Content Manager: org_openscopeproject_InteractiveHtmlBom.` Missing iBOM is a deployment bug, not a degradation kproj papers over. No placeholder image.
* **Args**: `--no-browser --no-compression --dest-dir <staging> --name-format "<P>-<R>.ibom" --extra-data-file <pcb> --dnp-field kicad_dnp --extra-fields MPN,Manufacturer --include-tracks <pcb>`. Rationale per flag captured in the grilling history.
* **Output**: `<P>-<R>.ibom.html` lands in the staging directory; kproj moves it to the site repo's `_versions/<P>/<R>/` during the `publish` step.
* **Batch‑safe**: no `${KIPRJMOD}` resolution, no KiCad GUI dependency. Works inside `for project in $(find ...); do kproj $project; done`.
### fab step + DRC/ERC
The `fab` pipeline step is **read + package** — kproj reads jBOM's existing outputs from `<project_dir>/production/`, assembles `<P>-<R>.fab.zip`, copies it to the site repo. kproj does NOT invoke jBOM's `FabricationWorkflow`; the user runs jBOM separately (Makefile `make fab` recipe, or direct `jbom fab` invocation).
* **Inputs**: `<project_dir>/production/bom.csv`, `<project_dir>/production/pos.csv`, `<project_dir>/production/gerbers.zip` (or whatever jBOM's `production_root` defaults produce; we read what's there).
* **fab.zip assembly**: kproj zips `bom.csv` + `pos.csv` + `gerbers.zip` into `<P>-<R>.fab.zip`, writes to `<site_repo>/versions/<P>/<R>/`.
* **No `--fabricator` in kproj's CLI** — fabricator selection happens at jBOM invocation time, not at kproj time. jBOM's output reflects whatever profile the user chose.
* **Audit findings about `<project_dir>/production/`**:
  * **warning**: `production/` missing or empty — fab artifacts not generated. kproj proceeds with the rest of the pipeline; `<P>-<R>.fab.zip` is omitted from `artifacts[]` and the version page (audit table surfaces the omission). User runs `jbom fab` and re‑runs kproj.
  * **warning**: `production/` outputs stale — `production/*.zip` mtime older than `*.kicad_pcb` mtime. User likely forgot to re‑run jBOM after bumping the board.
* **DRC/ERC** run as direct `kicad-cli pcb drc --format json --severity-all` + `kicad-cli sch erc --format json --severity-all` invocations alongside the fab step (kproj reads JSON in‑memory; no JSON files written to disk in v1). KiCad's GUI‑marked exclusions are respected (they appear in the report as severity `exclusion`).
* **v1 severity policy — surfaced, never blocking**: every DRC/ERC violation (error, warning, exclusion) is surfaced via **stderr** (human‑readable, one violation per line, with location + description) AND as a **Markdown table** embedded in the version page's content body (below front‑matter). The publish proceeds regardless of severity. The audit records counts per severity.
* **No `--force` flag in v1**: nothing blocks, nothing to override. `--force` semantics resurface in (B) where the strict‑quality‑bar policy gates tag creation.
* **No standalone artifacts**: kproj emits NO `<P>-<R>.drc.json`, `<P>-<R>.erc.json`, `*.drc.csv`, or `*.drc.html` files in `artifacts[]`. The Markdown table in the version page content body is the v1 surface.
* **Phase 6 deepening**: DRC violation visualisation as an iBOM extension — spatial overlay of violations on the interactive board view, leveraging iBOM's existing component‑location/board‑rendering infrastructure. Pairs naturally with the iBOM IPC‑API migration when KiCad 11 lands.
* **Audience framing**: the SPCoast site is a **developer‑time tool** as well as a customer‑facing production catalogue. Releases with warnings or errors are intentionally visible — a developer reading the site sees the current state, not a polished‑final‑only view. (B) is where the polish gating happens.
### publish step — site-repo writes
The `publish` pipeline step writes the snapshot into the local SPCoast site repo checkout, stages the changes, commits, and pushes.
* **Per-version markdown**: `<site_repo>/_versions/<Project>/<board_rev>.md` — front-matter (per the release-asset-set contract) + content body (DRC/ERC table + free-form passthrough).
* **Per-version assets**: `<site_repo>/versions/<Project>/<board_rev>/<P>-<R>.<asset>` — every file in the release asset set, including the versioned thumbnail (`<P>-<R>.thumbnail.{png,svg}`).
* **Per-project aggregator** at `<site_repo>/pages/<Project>.md` — **always rewritten** on every kproj run. Front-matter regenerated from current project metadata; body content = current `README.md` from the project repo (or empty if absent). No "create-once" pattern; no user-editable region inside this file. User customisations live in the project's `README.md` (source of truth); kproj re-imports each run. This way kproj evolutions of the aggregator format propagate automatically.
* **Layout for KiCad-era version files**: front-matter says `layout: kicad`. The site setup PR ships `_layouts/kicad.html` as a thin v1 wrapper that re-uses `eagle.html`:
```yaml path=null start=null
---
layout: eagle
---
{{ content }}
```
  Phase 6 grows `kicad.html` into a KiCad-specific layout (interactive iBOM embed, hierarchical schematic UX, DRC overlay) without touching any per-version `_versions/<P>/<R>.md` file.
* **Atomic file writes**: each emitted file written via `tempfile` + `os.replace()` so partial writes never appear in `git status` or `git diff`. KiCad-cli/iBOM/STEP outputs are pointed directly at `<site_repo>/versions/<P>/<R>/` via their `--output` / `--dest-dir` flags — no separate staging dir. jBOM's intermediate (the per-run `production_root`) is jBOM's concern; kproj just reads `<project_dir>/production/` for its assembly.
* **WriteTracker rollback** (v1 critical): kproj uses a `WriteTracker` Python context manager during the publish step. The tracker records every file created or modified in the site repo. On any exception:
  * Created files are deleted (`Path.unlink(missing_ok=True)`).
  * Modified files are restored via `git -C <site_repo> checkout -- <files>`.
  * If `git commit` succeeded but `git push` failed: `git reset --hard HEAD^` to undo the commit.
  * If the rollback itself errors: log to stderr with manual‑recovery instructions and exit code 2.
Net guarantee: a kproj run either completes cleanly (commit + push, or commit‑only with `--no-push`) or leaves the site repo working tree exactly as it was at run start. No "stray files in git status" residue from partial runs — critical for batch usage where one mid‑pipeline failure must not poison subsequent projects.
* **Git workflow** (site repo only): kproj runs `git add` on the changed files, `git commit -m "<message>"`, and `git push` (pushes whatever branch is checked out to its upstream; user keeps the site repo on the deployment branch). The push is suppressed by `--no-push` / `KPROJ_NO_PUSH=1` for batch usage. No `git checkout` logic; no PR flow; no branch flag in v1.
* **Commit messages** (plain-prefix style; not full conventional commits):
  * New release: `publish: <Project>-<board_rev>`
  * Metadata-only refresh: `refresh: <Project>-<board_rev> (<reason>)` — e.g. `refresh: cpNode-Xiao-68x90-1.0B (status: experimental → active)`
  * First release for a new project: `add: <Project> <board_rev>`
* **One-time site setup** (not per-release; a separate manual PR the user does once before kproj v1 starts running): rewrite `electronics.html` to filter on `iskicad` + use-latest-version thumbnail Liquid; create `eagle-archive.html` for the legacy EAGLE list; replace the sidebar TOC's single `Electronics` entry with two adjacent entries `KiCad Projects → /electronics.html` and `Eagle Projects → /eagle-archive.html`; create `_layouts/kicad.html` v1 thin wrapper. After this setup PR, kproj per-release runs only write `_versions/<P>/<R>.md`, `versions/<P>/<R>/...`, and `pages/<P>.md`.
### dry‑run — side‑effect‑free preview
`kproj --dry-run` is a **fully side‑effect‑free** preview. Runs in milliseconds (audit + pre‑flight + string composition). No file writes anywhere.
* **Runs**: pre‑flight checks (project files exist, iBOM plugin path resolves, site repo accessible, site repo clean), audit (read‑only on project files), DRC/ERC (read‑only, JSON captured in‑memory only).
* **Skips**: all `kicad-cli` artifact generation (no PNG/SVG/STEP/PDF files), iBOM subprocess invocation, jBOM (kproj never invoked jBOM anyway in this model), staging-dir creation, any writes to the site repo, any git operations.
* **Reports** to stderr: pre‑flight pass/fail, audit findings, DRC/ERC findings, **action summary only** for the would‑be writes — file paths, commit message, push target. **No content dumping** (no rendered front‑matter, no rendered body); content rendering would be its own artifact, defeating the purpose.
* **Exempts itself** from the pre‑flight site‑repo cleanliness check (since dry‑run never writes).
### exit codes
Structured exit codes communicate run outcome to toolchains:
* **0** — clean: no audit findings of any severity, no DRC/ERC findings. Pipeline ran successfully (or `--dry-run` would have).
* **1** — findings present: audit warnings/errors and/or DRC/ERC violations were surfaced. Pipeline still completed successfully (publish happened in non‑dry‑run; results visible on site). Toolchain decides whether to treat as informational or gate downstream work.
* **2** — mechanical failure: project files missing, iBOM plugin not installed, site repo dirty pre‑flight, file system error, jBOM `production/` missing in a context that needs it, git push rejected, WriteTracker rollback ran, etc. Pipeline did NOT complete. Site repo state is either unchanged (rollback succeeded) or in a documented manual‑recovery state.

Makefile patterns:
* `kproj && next-step` — gate downstream on clean run.
* `kproj; [ $$? -eq 2 ] && exit 1; next-step` — treat mechanical failures as fatal, ignore findings.
* `kproj || true; next-step` — naive "just publish, ignore outcome".
### audit — surface-independent finding model
The audit is the metadata-quality lint pass (distinct from DRC/ERC which is design‑quality). Findings are captured as a structured `List[Finding]` independent of how they're displayed. v1 surfaces:
* **stderr formatter** — human prose, one line per finding.
* **Markdown table formatter** — embedded in the version page's content body (sibling to DRC/ERC table).
* **Front‑matter summary formatter** — `audit: {errors: N, warnings: M}` for layout badges.
* **JSON formatter** — emitted by `--json` mode to stdout.

Audit severities are `error` and `warning` only — no `exclusion` level (audit has no equivalent of KiCad's per-violation exclusion UI; `exclusion` belongs to DRC/ERC only). Heuristic vocabulary (locked Phase 2):
* error: `.kicad_sch` or `.kicad_pcb` missing; placeholder/template values (`${...}` literals, `DATE`, `Fab Date`, `Designer Name`, `Sheet Title Line N`, locale defaults); missing `${COMMENT9}`; `${COMMENT9}` outside the closed taxonomy.
* warning: empty title_block on either side; SCH/PCB disagreement on a field (excluding legitimate `rev` and `date` patterns); date not `YYYY.MM`; designer not `FirstName LastName`; `board_rev` doesn't extend `design_rev`; `replaced-by:<X>` references nonexistent project; `production/` missing or stale.

`--step audit` is NOT in v1 — the full pipeline is fast enough that a separate fast-audit step isn't justified. Fast audit feedback comes from `kproj --dry-run` (which runs audit + DRC/ERC + pre‑flight in milliseconds).
### v1 deliverables outside the CLI
* **`templates/Makefile.kicad`** shipped in the kproj repo. Sample composition file users symlink into a KiCad project (matching the existing `Makefile.board` symlink pattern). Provides `make audit` (= `kproj --dry-run`), `make fab` (= `jbom fab`), `make publish` (= `kproj`), and a sample `make release` (= `git tag -a release/<rev>` + `gh release create` — the (B) layer the user composes from kproj + jBOM + git/gh).
### Phase 6 deepening — user‑facing interactive jobset
A *single global* `kproj-interactive.kicad_jobset`, distributed via the user's `com_spcoast_jplocher_kicad-parts-library` PCM package, would let the user run kproj‑equivalent KiCad‑side artifact generation interactively from KiCad's `File → Open Job Set...` UI without invoking kproj's CLI. Path‑agnostic via `${KIPRJMOD}`. Pairs with the PCM‑package‑refresh sub‑project. Not v1.
