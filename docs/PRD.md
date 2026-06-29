# kproj — Product Requirements Document (v1)
Phase 3 deliverable. Defines what kproj v1 does from the user's perspective: the problem it solves, the solution shape, the user stories with Gherkin acceptance criteria, and the explicit out-of-scope boundary.

This document is **user-facing requirements**. It does not specify implementation:
- Vocabulary → `docs/GLOSSARY.md`
- Architecture decisions → `docs/adr/`
- Implementation specs → `docs/DESIGN.md`

## Problem Statement

The SPCoast site at `https://www.spcoast.com/electronics.html` catalogs SPCoast (and MRCS) PCB designs. Today the site is populated by `convert2jekyll.py` — an EAGLE-only Python script that produces hand-curated thumbnails, sidecar metadata files, and requires the user to manually run a Makefile target before each upload.

KiCad has replaced EAGLE as the active CAD tool for new boards. The EAGLE pipeline does not understand KiCad files; the user has been hand-publishing recent KiCad projects to the site, which is repetitive and error-prone. Several knock-on problems compound the friction:

- KiCad's title-block metadata (`${TITLE}`, `${REVISION}`, `${COMPANY}`, `${ISSUE_DATE}`, `${COMMENT1..9}`) is the canonical source for project facts, but its population is sparse across the corpus (Phase 1 survey).
- Multiple sources of project data (`.kicad_pro` JSON, `.kicad_sch` / `.kicad_pcb` S-expressions, `README.md`) need to be reconciled into a single Jekyll front-matter shape.
- jBOM exists as a sibling tool for generating fab artifacts but is not yet wired into the site-publish workflow.
- The audit needed to ensure metadata quality (placeholder values, SCH/PCB title-block disagreements, date-format violations) has no automated surface.
- Mid-pipeline failure in a batch context (e.g. iBOM plugin not installed for one project) can leave the site repo in a dirty state, poisoning subsequent batch publish attempts.

## Solution

**kproj** is a local CLI tool that takes a *point-in-time snapshot* of a KiCad project on disk and publishes it as a `version` entry on the SPCoast Jekyll site. One `kproj` invocation: reads the project, runs the metadata audit + DRC + ERC, exports renders + schematics + iBOM, reads jBOM's `production/` outputs to assemble `fab.zip`, packages `source.zip`, writes the version markdown + per-version assets + per-project aggregator into the local site repo checkout, commits, and pushes.

The user runs `kproj` (or `make publish` via a sample Makefile shipped at `templates/Makefile.kicad`) whenever they want to refresh the site's view of a project — many times per fab cycle, on the user's machine, no CI integration required for v1. Release-lifecycle work (git tag + `gh release create`) is out of v1 scope and composed externally via Makefile (`make release`).

Audit and DRC/ERC findings are **surfaced, not blocking** (ADR 0004): the publish proceeds; readers of the site see findings honestly via Markdown tables on each version page; the developer iterates against the findings to clean up.

Mid-pipeline failure rolls back automatically via the `ChangeJournal` transactional write log (ADR 0005), so batch publishes (`for project in projects/*/; do kproj $project; done`) are safe even when one project's pipeline fails.

## User Stories

Stories are grouped by actor. Each carries Gherkin acceptance criteria — the user-observable conditions that anchor the requirement.

### Project author — primary actor, the developer iterating on a board

#### Story 1 — Publish a project
*As a project author, I want to publish my project's current state to the SPCoast site, so that I can share the design without manual file copying.*

```gherkin path=null start=null
GIVEN a kicad_project at <path> with a populated title_block
AND the project's `production/` directory contains fresh jBOM output (gerber pack + bom.csv + pos.csv)
WHEN I run `kproj <path>`
THEN the site repo has `_versions/<Project>/<board_rev>.md` with front-matter matching the project state
AND the site repo has `versions/<Project>/<board_rev>/<P>-<R>.<asset>` files for the standard asset set (top.png, bottom.png, step, sch.svg, sch.pdf, ibom.html, fab.zip, source.zip, thumbnail.png)
AND the site repo has `pages/<Project>.md` with content from the project's README.md
AND the site repo is committed and pushed
```

*Note*: when `production/` is missing or empty, `fab.zip` is omitted from the asset set and a warning Finding is surfaced. The rest of the publish proceeds. See ADR 0003 / docs/DESIGN.md § *FabPackager*.

#### Story 2 — Preview without publishing
*As a project author, I want to preview what kproj would publish without actually publishing, so that I can verify my project is ready.*

```gherkin path=null start=null
GIVEN a kicad_project at <path>
WHEN I run `kproj --dry-run <path>`
THEN no files are written to the site repo
AND no git operations are performed on the site repo
AND stderr lists the audit findings, DRC/ERC findings, and the would-be writes (file paths only, not content)
```

#### Story 3 — Find my project automatically
*As a project author, I want kproj to find my project without typing a full path, so that I can publish from anywhere convenient.*

```gherkin path=null start=null
GIVEN I am in a directory containing exactly one *.kicad_pro file
WHEN I run `kproj` (no argument)
THEN kproj resolves the current directory as the project
```

```gherkin path=null start=null
GIVEN I am elsewhere
WHEN I run `kproj <basename>` where <basename> matches a known KiCad project directory under ~/Dropbox/KiCad/projects/
THEN kproj resolves the basename to the project directory
```

#### Story 4 — Iterate freely on metadata
*As a project author, I want kproj to publish even when my project has audit warnings, so that I can iterate against the published findings.*

```gherkin path=null start=null
GIVEN a kicad_project with audit warnings (e.g. SCH/PCB title-block disagreement)
WHEN I run `kproj <path>`
THEN the publish proceeds successfully (no blocking)
AND the version page content body shows a Markdown table of the audit findings
AND kproj's exit code is 1 (findings present but pipeline complete)
```

#### Story 5 — See current state honestly on the site
*As a project author, I want each published version's quality state (audit + DRC/ERC) to be visible on the site, so that I and visitors know what they're looking at.*

```gherkin path=null start=null
GIVEN a kicad_project with DRC warnings
WHEN I publish via `kproj`
THEN the version page front-matter includes `audit: {errors: 0, warnings: N}` and `drc: {errors: 0, warnings: M, exclusions: K}`
AND the version page body shows two adjacent Markdown tables: metadata audit findings, and DRC/ERC findings
```

#### Story 6 — Update status without re-running everything
*As a project author, I want to update a release's status (e.g. experimental → active) without re-generating renders / fab / etc., so that status transitions are cheap.*

```gherkin path=null start=null
GIVEN a version already published with `status: experimental`
AND I have edited ${COMMENT9} in the SCH title-block to `active`
WHEN I run `kproj`
THEN the version markdown is re-written with `status: active`
AND no renders / SVGs / iBOM / fab.zip are regenerated
AND the site repo is committed with a `refresh:` commit-message prefix
```

*Note*: `${COMMENT9}` is read from the SCH title-block per the locked per-field metadata precedence (SCH is canonical for `comment2`/`comment3`/`comment9`; PCB title-blocks routinely omit them). See `docs/DESIGN.md` § *Metadata precedence*.

#### Story 7 — Skip a private project
*As a project author with a project not for public release (cpOD pattern), I want to mark it as `status: private`, so that kproj skips the site-publish step automatically.*

```gherkin path=null start=null
GIVEN a kicad_project with ${COMMENT9} = `private`
WHEN I run `kproj`
THEN the audit + DRC/ERC run normally (for the user's stderr)
AND no files are written to the site repo
AND no git operations are performed on the site repo
AND kproj exits with code 0 when no findings exist
AND kproj exits with code 1 when audit/DRC/ERC findings exist (uniform with the global findings-present rule)
```

*Semantics*: `private` is **prospective only**. kproj will not publish *future* snapshots while the status is private; any previously published version of the project remains on the site unchanged. The site-repo cleanliness check and iBOM availability check are deferred past status detection so a `private` project never fails preflight on either condition.

*Out of scope for v1*: retroactive unpublishing of a version that was mistakenly published. If a public version was published and the user now wants to hide it, that is a separate "mistakenly-published unpublish" workflow (deferred discussable sub-project, see plan).

#### Story 8 — Batch-publish without N pushes
*As a project author, I want to publish many projects in a corpus-wide batch, so that I can update the site after a bulk cleanup pass.*

```gherkin path=null start=null
GIVEN N kicad_projects in ~/Dropbox/KiCad/projects/*/
WHEN I run `for p in projects/*/; do KPROJ_NO_PUSH=1 kproj "$p"; done; git -C <site_repo> push`
THEN each project produces one commit in the site repo
AND only one push to the site remote occurs (at the end)
AND the SPCoast site rebuilds exactly once via GitHub Pages
```

#### Story 9 — Recover cleanly from mid-pipeline failure
*As a project author running a batch, I want kproj to roll back the site repo cleanly if any single project's pipeline fails, so that the batch isn't poisoned by one failure.*

```gherkin path=null start=null
GIVEN a kicad_project for which the iBOM plugin invocation will fail
WHEN I run `kproj <path>`
THEN no partial files remain in the site repo
AND `git status --porcelain` in the site repo shows the same state as before kproj ran
AND kproj exits with code 2 (mechanical failure)
AND stderr contains a clear description of the failure
```

#### Story 10 — Refuse to mix my edits with kproj's
*As a project author, I want kproj to refuse to publish if my site repo has uncommitted edits, so that my hand-edits don't entangle with kproj's commit.*

```gherkin path=null start=null
GIVEN the site repo has uncommitted changes (`git status --porcelain` non-empty)
WHEN I run `kproj <path>` (without --dry-run)
THEN kproj exits with code 2 (mechanical failure) before any writes
AND stderr explains the uncommitted state and recommends commit/stash/clean
```

#### Story 11 — Compose with my Makefile workflow
*As a project author, I want kproj to compose with my existing Makefile workflow, so that `make publish` does the right thing without me re-learning anything.*

```gherkin path=null start=null
GIVEN a kicad_project with `Makefile -> ~/Dropbox/KiCad/kproj/templates/Makefile.kicad` (symlink)
WHEN I run `make publish`
THEN make runs `jbom fab --fabricator <FAB>` (the prerequisite)
AND then runs `kproj`
AND the project is published to the site
```

#### Story 12 — Debug failures with verbose output
*As a project author when something goes wrong, I want kproj to surface diagnostics on stderr with `-v`, so that I can understand what failed.*

```gherkin path=null start=null
GIVEN a kicad_project that fails to publish
WHEN I run `kproj -v <path>`
THEN stderr contains the kicad-cli subprocess command lines and their stdout/stderr
AND stderr contains the git command lines and their stdout/stderr
```

#### Story 13 — Recognize no-op runs
*As a project author, I want kproj to recognize when nothing has changed and do no work, so that re-runs after a successful publish are cheap and silent.*

```gherkin path=null start=null
GIVEN a kicad_project already published, where:
  - the current front-matter kproj would emit matches the on-disk `_versions/<P>/<R>.md` front-matter
  - the current body kproj would emit matches the on-disk body
  - the project's README.md content matches the on-disk `pages/<P>.md` body
  - every artifact referenced in the front-matter exists on disk and is not older than its source
WHEN I run `kproj <path>`
THEN no files are written
AND no commit is made
AND kproj exits with code 0
AND stderr is silent at default verbosity
```

*Note*: a README edit, a status change, or a stale artifact each force a re-run that is more than a no-op. See `docs/DESIGN.md` § *New-release detection* for the full comparison matrix.

### Project visitor — secondary actor, browsing the site

#### Story 14 — Browse projects visually
*As a project visitor, I want each KiCad project listed with a thumbnail, so that I can browse projects visually.*

```gherkin path=null start=null
GIVEN the SPCoast site contains multiple KiCad projects published via kproj
WHEN I visit /electronics.html (the live KiCad landing page)
THEN each project is listed with a thumbnail image
AND the thumbnail is drawn from the latest version of that project
```

#### Story 15 — Inspect a version's quality state
*As a project visitor, I want to see each version's audit and DRC/ERC state on the version page, so that I know the trustworthiness of the design.*

```gherkin path=null start=null
GIVEN a published version page
WHEN I view the page
THEN I see a quality badge near the top showing audit + DRC/ERC counts
AND I see two adjacent Markdown tables in the body: metadata audit findings, DRC/ERC findings
```

### Project consumer — tertiary actor, fabricating or replicating a board

#### Story 16 — Download fab artifacts
*As a project consumer, I want to download the fab pack from a published version, so that I can fabricate the board myself.*

```gherkin path=null start=null
GIVEN a published version page where the project's `production/` directory contained fresh jBOM output at publish time
WHEN I click the fab.zip artifact link
THEN I download a zip containing exactly three files: bom.csv, pos.csv, gerbers.zip
```

*Note*: when `production/` was missing or stale at publish time, no `fab.zip` artifact is listed on the version page (the standard asset set is reduced). The publish still succeeds for the non-fab artifacts.

#### Story 17 — Replicate the design in KiCad
*As a project consumer, I want to download the source archive from a published version, so that I can iterate on the design in KiCad.*

```gherkin path=null start=null
GIVEN a published version page
WHEN I click the source.zip artifact link
THEN I download a zip containing the project's non-derived KiCad files (*.kicad_pro/sch/pcb/sym/pretty/dru/wks plus library tables + README.md + LICENSE + CHANGELOG.md)
AND the zip contains a top-level `SOURCE_README.md` documenting the (small) limits of opening the project without the original external libraries
AND I can unzip the archive and open `<Project>.kicad_pro` in KiCad 9 with the schematic and PCB rendering correctly
```

*Scope*: the source archive captures **project artifacts**, not the larger KiCad-install context (libraries, plugins, etc.). KiCad 6.0+ embeds all symbols and footprints used in the design inside the project's `.kicad_sch` and `.kicad_pcb` files, so the archive is sufficient for opening + viewing + editing + generating manufacturing files.

*Known limits without the original libraries* (documented in `SOURCE_README.md`):

- **3D viewer shows the bare PCB.** 3D models are linked by absolute filesystem path, not embedded; the 3D viewer renders the board without component shapes. 2D PCB view and fabrication output are unaffected.
- **"Update Symbols from Library" does not work.** Requires the source libraries; the consumer has the embedded copies, not the originals.
- **Reusing parts in other projects is awkward.** Pulling a custom symbol into a new design requires the source library.

For users who want full library access, `SOURCE_README.md` lists the external libraries referenced by the project (e.g. `SPCoast_KiCad_Library`) with install pointers. See `docs/DESIGN.md` § *SourcePackager*.

#### Story 18 — Inspect the BOM interactively
*As a project consumer planning a build, I want to view the interactive HTML BOM, so that I can plan component sourcing without unzipping anything.*

```gherkin path=null start=null
GIVEN a published version page
WHEN I click the interactive-BOM link (or the iBOM is embedded inline)
THEN the iBOM HTML loads with the board view + component table + checkbox state controls
```

## Out of Scope

The following are explicitly NOT part of kproj v1. Each is documented in an ADR or noted as a deferred subproject:

- **Git tag creation in the project repo.** The `release/<board_rev>` tag is created by the user's Makefile (`make release`), not by kproj. (ADR 0002)
- **`gh release create` on the project repo.** Same — Makefile composes it externally. (ADR 0002)
- **`--force` flag.** Nothing blocks in v1; nothing to override. (ADR 0004)
- **Working-tree-clean preconditions on the project repo.** kproj reads project files from disk regardless of project-repo git state. (ADR 0002)
- **CI / GitHub Actions integration.** kproj v1 runs locally. The cross-repo push problem is deferred to Phase 6+. (ADR 0007)
- **Running jBOM from inside kproj.** kproj reads `<project_dir>/production/` outputs; the user runs jBOM separately. (ADR 0003)
- **Multi-variant project disambiguation** (e.g. `Brakeman-BLUE` / `Brakeman-RED` sharing the basename `Brakeman.kicad_pro`). User fixes at source via KiCad project rename; not a kproj feature.
- **Hierarchical schematic display in v1's layout.** Root sheet renders inline; full multi-sheet PDF is a download. Phase 6+ may add hierarchical UX.
- **`--json` output mode.** Phase 6+ feature paired with the two-phase architecture (extract → render) deepening.
- **Per-step CLI invocation (`--step <name>`).** v1's pipeline is fast enough not to need per-step debug toggles.
- **Configuration profile system.** v1's `~/.kproj.yaml` has 2 keys. If config surface grows past ~5 keys with composition needs, revisit.
- **Hand-drawn / abstract thumbnails per project.** v1 uses revision-specific 3D renders. If "thumbnail drift between revisions" becomes a real UX problem, a hand-drawn-override mechanism can be added.
- **Per-project kproj config (`.kproj/config.yaml`).** Deferred until per-project defaults become a real need.

## Further Notes

- The user-facing CLI surface is intentionally minimal: `kproj [<project-or-dir-or-file>] [--site-repo PATH] [--dry-run] [--no-push] [-v|--verbose] [-d|--debug]`. Six flags, one positional. `--site-repo` is the highest-precedence site-repo override; `KPROJ_SITE_REPO` env var and `~/.kproj.yaml` `site_repo` key are the fallbacks. See `docs/DESIGN.md` for the parsing mechanics.
- kproj is designed to compose with sibling tools (jBOM for fab artifact generation, a future `kproj rename` for multi-variant disambiguation, a future `kicad-meta` for bulk metadata edits) via Makefile recipes — see `templates/Makefile.kicad`.
- The `ChangeJournal` transactional write model (ADR 0005) is the foundation for v1's batch-safety promise. Any future kproj features that touch the site repo must use the same pattern.
- Phase 6+ deepening candidates (not committed; recorded for future scoping): two-phase architecture (extract → render with `--json` intermediate), PCM-package refresh for the user-facing interactive jobset, DRC visualization as an iBOM extension, richer per-project config, CI integration with cross-repo PAT.
- Phase 7 (Validation, PR, merge) validates the v1 against the Phase 7 target project (`~/Dropbox/KiCad/projects/MRCS/cpNode-Xiao-68x90`). The acceptance is that all user stories above can be demonstrated against that project.
