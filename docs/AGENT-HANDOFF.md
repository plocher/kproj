# kproj — Agent Handoff Notes
Compiled 2026-07-01 after the SiteProfile abstraction PR (#21) merged. Distills the state, locked decisions, and lessons from the Jekyll → Hugo migration + kproj Phase F work so a fresh agent session can pick up Phase G (Phase 7 end-to-end validation) without re-deriving context.
## Current state
- **kproj repo (`plocher/kproj`)**: `main` at the merge of PR #21. Phases 0–6 (foundation → publishing waves) + hygiene PR #19 + SiteProfile abstraction PR #21 all merged. Local test baseline: **365 pytest / 1 skipped (iBOM/pcbnew, kproj#10) / 15 Behave scenarios (87 steps) / ruff + mypy strict clean**. No GitHub CI configured — local tests are the gate.
- **SPCoast site (`SPCoast/SPCoast.github.io`)**: Hugo site live at https://www.spcoast.com, deployed via `.github/workflows/hugo.yml` (native `actions/deploy-pages@v5`, Node 24). MVP content = SPINS PDFs + PCB Notes + placeholder homepage. Custom minimal Hugo layouts (no external theme). Pre-migration Jekyll state preserved at tag `archive/jekyll-final`; deploy source is `main` (not `jekyll4-actions`, which is stale).
- **Open kproj issues (not blocking Phase G)**:
  - #10 iBOM-Python spike (the one skipped test)
  - #12–#16 v1.1 deferred MAJORs from wave-3 adversarial review
  - #17 profile hooks (produces the measurement baseline for future smart-refresh work)
  - #20 CAMTool capability comparison — discovery/gap-list task; includes the cross-domain-links example (KiCad ↔ Arduino, KiCad ↔ KiCad daughterboards)
## Next milestone: Phase G — kproj Phase 7 end-to-end validation
- **Target project**: `~/Dropbox/KiCad/projects/MRCS/cpNode-Xiao-68x90` (the Phase 0 scope-contract validation target).
- **Acceptance**: every user story in `docs/PRD.md` demonstrable against that project — publish, dry-run, project resolution, batch-safety, private-status, no-op detection, source archive, iBOM link, etc. All 18 stories carry Gherkin acceptance criteria.
- **Prerequisites**: all satisfied. SiteProfile abstraction lets kproj emit into Hugo's `content/versions/`, and `load_config` selects HUGO for production.
- **Expected outcome**: real KiCad content will surface issues that don't show up against fixture projects (thumbnail recipe, iBOM path discovery, asset-freshness edge cases, front-matter YAML corners). File follow-up issues per gap; don't inline-fix everything.
## Key documents (source-of-truth locations)
### In the kproj repo
- `docs/PRD.md` — user-facing v1 requirements. 18 stories with Gherkin acceptance criteria.
- `docs/DESIGN.md` — implementation specs. **Owns § *SiteProfile abstraction*** (single-source of the profile rationale — do not restate it in consumer docstrings).
- `docs/GLOSSARY.md` — canonical vocabulary (release, version, publish, tag, status, ProjectInfo, AnalysisInfo, Publication, Producer Pattern).
- `docs/adr/000{1..9}-*.md` — Architectural Decision Records. Key ones for Phase G:
  - ADR 0002 — publisher boundary (kproj does not touch project-repo git tags/releases)
  - ADR 0003 — FabPackager consumes existing `production/` output; kproj doesn't run jBOM
  - ADR 0004 — audit findings surfaced, not blocking
  - ADR 0005 — ChangeJournal transactional rollback
  - ADR 0007 — local CLI v1, CI deferred
  - ADR 0008 — iBOM via direct script invocation (not `kicad-cli jobset run`)
  - ADR 0009 — KicadInstallLocator (`common.kicad_install`)
- `docs/CHANGELOG.md` — running history per PR.
- `docs/phase{1,4}-*.md` — historical review artifacts, preserved verbatim.
### Cross-repo reference (kproj borrows patterns from jBOM)
- `/Users/jplocher/Dropbox/KiCad/jBOM/docs/architecture/adr/0008-unified-jbom-config-schema.md` — the GENERIC-vs-named-profile pattern kproj mirrors in `SiteProfile`. Read this if a design question involves profiles, config layering, or CLI flag defaults.
- jBOM's `src/jbom/config/defaults.py` — reference for the `_resolve_*` pattern kproj uses in `src/kproj/config.py`.
## Architectural decisions locked this session
1. **Jekyll → Hugo migration.** Site backend cutover driven by empirical Ruby/Bundler dependency treadmill (Jekyll deploy failed continuously Dec 2025 → Jun 2026 across three layers: Bundler-vs-Ruby incompatibility, Gemfile.lock stale, platform lock). Migration is a one-time cost that avoids ongoing Ruby maintenance. Custom minimal Hugo layouts under `layouts/_default/{baseof,single,list}.html` + `layouts/partials/{head,menu,footer}.html`, plus a hand-written `static/css/main.css` — no external theme dependency, no theme-migration debt later.
2. **Site-repo path unification.** `~/Dropbox/workspace/SPCoast.github.io` is the single canonical checkout location (was `~/Dropbox/eagle/SPCoast.github.io`). `DEFAULT_SITE_REPO` in `src/kproj/config.py` is the sole source of truth. Docs / ADRs / templates use the generic `$SITE_REPO` placeholder + cite the constant.
3. **SiteProfile abstraction (PR #21).** The seam between kproj and the site backend:
    - **`GENERIC_SITE_PROFILE`** = abstract test anchor. `versions_dir="versions"`, `pages_dir="pages"`, `layout_field=None`. **Backend-neutral. Not intended for deployment.** Behave scenarios + unit-test fixtures reference this constant so tests validate the abstraction contract without pinning to any real backend layout.
    - **`HUGO_SITE_PROFILE`** = concrete Hugo backend. `versions_dir="content/versions"`, `pages_dir="content/pages"`, `layout_field=None` (Hugo picks by section). Selected by `load_config` for production.
    - **No in-code default values anywhere.** Every consumer function takes `site_profile: SiteProfile` as a **required** parameter. `KprojConfig.site_profile` is a required dataclass field. The one place the default is resolved is `_resolve_site_profile()` inside `load_config()` — v1 hardcodes HUGO; v1.1+ grows CLI/env/yaml precedence with argparse-time default = `generic` (jBOM parity).
4. **M11 rip-out (during wave-3 fix-ups, before Phase F).** The title-block-stripped content-hash caching for Story 6's "cheap refresh" was deleted as premature optimization + ADR 0002 boundary violation (persisted state in a site repo kproj doesn't own). Any SCH edit in v1 triggers a full publish. Follow-ups: kproj#17 (profile hooks — produces measurement baseline) + kproj#18 (smart refresh — closed as not-planned pending that data).
## Patterns and anti-patterns learned
- **Cut the knot.** When infrastructure debt keeps compounding (Ruby bump → Bundler pin → lockfile → platform lock → environment protection → …), stop patching and re-target the platform. The Jekyll deploy failure surfaced three cascading layers before we decided to migrate; earlier detection would have saved cycles.
- **Preserve before greenfield.** Always tag or branch the pre-migration state before destructive rewrites. `archive/jekyll-final` on the site repo is the recoverable reference; nothing is deleted from git history.
- **DRY: design docs vs. code docs.** Own the design rationale in exactly one place — usually `docs/DESIGN.md` + the owning module's docstring. Consumer docstrings describe *only what their own parameter does for that function*; the "why" and "how it's resolved" live upstream. The type hint (`site_profile: SiteProfile`) links readers to the source. This was the specific critique that produced the doc-trimming pass at the end of PR #21.
- **Function-level defaults create DRY hazards.** If six functions each have `x: T = DEFAULT_X`, changing the default means editing six places and hoping nobody forgot. Worse, a new function author can silently forget the default entirely. Better: required parameter + single resolution point at argparse / config layer. Type system enforces it.
- **GENERIC ≠ production default.** The abstract profile is a *test anchor* (backend-neutral values, not deployable). Production selects a named backend profile via `load_config`. This is jBOM's ADR 0008 pattern: `generic.jbom.yaml` is the no-flag fallback for tests; named profiles (`jlc`, etc.) are for real deployments.
- **Tests reference constants, not string literals.** `context.site_repo / GENERIC_SITE_PROFILE.versions_dir / P / f"{R}.md"`, never `context.site_repo / "content/versions" / P / f"{R}.md"`. If the constant's value ever changes, tests follow transparently.
- **Kill the M11-shaped feature before it lands.** Any v1 code that exists to make things *faster* (versus *correct* or *safe*) should have a measurement anchor before landing. "Cheap" and "metadata" were unmeasured qualitative claims; the state-persistence machinery to enable them coupled kproj's correctness to a repo it doesn't own. State that kproj needs for its own correctness must live in storage kproj owns, not storage kproj writes to as a side effect.
## Environment gotchas
- **Local Python**: use `.venv/bin/python -m pytest ...` (after `uv sync --extra dev`). `uv run pytest` sometimes falls back to system Python 3.10, which doesn't have the package installed.
- **Behave tests live under `tests/features/`**, not `features/`. Invoke as `.venv/bin/python -m behave tests/features --no-color --format progress`.
- **GitHub token scoping.** The user's PAT can push to `plocher/*` repos and read `SPCoast/*` repos, but **cannot** create PRs on `SPCoast/*` or modify environment branch policies via API (403 Resource not accessible). UI intervention is required for anything on the SPCoast org (deployment branch policies, PR creation). Don't waste cycles retrying the API — surface the UI link.
- **The SPCoast site does not use PRs.** Push to `main` / `gh-pages` / `jekyll4-actions` directly triggers deploy. `jekyll4-actions` is stale from the Jekyll era; the current deploy source is `main`.
- **CI on `plocher/kproj`: not configured.** Local test run is the gate. If merged PRs break something, it won't show up until the next local run.
- **Homebrew installs used this cycle**: `hugo` (extended, 0.163.3), `uv`. Both re-installable via `brew install <name>`.
- **Worktrees clean up manually.** After each wave PR merges, remove the merged branch's worktree (`git worktree remove ../kproj-wt-<name>`) and delete the local branch. Don't leave stale worktrees on disk.
- **Commit messages: plain ASCII only.** zsh double-quoted strings do NOT expand `\u2014` / `\u2192` / other unicode escapes, so `git commit -m "...\u2014..."` stores the literal 6-character escape in the commit subject. Use ASCII hyphen `-` (not em-dash), `->` (not arrow), and plain punctuation everywhere in commit messages / gh CLI arguments. Reserve Unicode typography for markdown files where it renders correctly.
## User working style
- **TDD.** Red-green-refactor. Behave scenarios for user-facing stories; unit tests for internal abstractions. All tests pass before commit.
- **Feature branches + PRs.** Never work directly on `main`. Semantic-commit messages. `Closes #N` trailers required in PR descriptions for GitHub to auto-close.
- **Hygiene.** ruff auto-fix, mypy strict, pre-commit hooks may modify files (re-add after). `docs/CHANGELOG.md` updated per PR.
- **Design consultations before code** for non-trivial architectural changes. Propose, get feedback, iterate, then implement. The user critiques both under-explaining (missing rationale) and over-explaining (DRY-duplicated rationale across files).
- **"Slow down / don't get ahead of me."** Checkpoint often, especially before dispatching workers or making cross-repo changes. Prefer asking a targeted single-select / multi-select question over inferring intent from context. Do not batch multi-step changes without pause.
- **Direct technical critique preferred over validation.** When the user says "this still feels like X is Y" or "double checking …", the correct response is to actually engage the critique — often it's architecturally correct — not to defend the current state. Twice in this session the user surfaced abstraction leaks (Hugo values in GENERIC; DRY-duplicated docstrings) that resulted in real design improvements.
- **Cut-the-knot decisions** when infrastructure debt is compounding. The user tolerates larger one-time costs to avoid ongoing maintenance drag (Jekyll → Hugo was the canonical example this session).
## Advice for Phase G specifically
1. **Start by reading** — this file, `docs/PRD.md`, `docs/DESIGN.md` § *Pipeline orchestration sequence* + § *SiteProfile abstraction*, and the four ADRs called out above (0002, 0004, 0005, 0008). That's ~30 minutes and covers everything needed to run `kproj` against `cpNode-Xiao-68x90` and start validating.
2. **Expect real content to surface issues.** Phase 7 is validation, not implementation. Front-matter shape edge cases, asset paths, thumbnail recipe tuning, iBOM path discovery — all may need tweaks. File follow-up issues per gap; don't inline-fix everything.
3. **First real publish → Hugo site verification.** After `kproj` writes the first `content/versions/cpNode-Xiao-68x90/<R>.md`, verify it renders on the live Hugo site (may need a `layouts/versions/single.html` — currently the site only has `_default/single.html`).
4. **Ask before committing.** Even for docs. The user has been explicit about not being surprised by proactive commits.
5. **Mirror jBOM patterns when in doubt.** kproj is designed as a sibling of jBOM; jBOM's ADRs and code are the primary reference for cross-cutting design choices.
