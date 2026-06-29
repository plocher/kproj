# Site Platform Assessment — Phase 1 (architect, in-process)

**Status:** draft, awaiting child-agent reports for cross-check
**Author:** architect (orchestrator) — `019f0b2a-6eee-71d3-835d-65f8c655aa36`
**Inputs:** sweep of `/Users/jplocher/Dropbox/eagle/SPCoast.github.io` (`_config.yml`, `_layouts/*.html`, `electronics.html`, `Gemfile`, `.github/workflows/jekyll.yml`, sample `_versions/<P>/<R>.md` and `pages/<P>.md`)

## Executive summary

- **Recommendation: keep Jekyll.** None of the plan's migration triggers actually fire — the GH Pages plugin allowlist is already bypassed by an Actions-driven Jekyll 4 build, iBOM embedding is friction-free (static HTML asset), and the existing layout pipeline does what kproj needs.
- **Layout strategy: reuse `eagle.html` initially.** Defer a dedicated `pcb.html` until a KiCad-specific UI element (e.g. inline iBOM viewer or STEP preview) demands it. Cost of v1 reuse is zero; the existing layout already handles `images[]`, `artifacts[]`, version tabs, and status badges.
- **Electronics page shape: two physical pages, migration-framed.** Repurpose `electronics.html` as the live KiCad landing (filters on `iskicad`); spin out a new `eagle-archive.html` for the frozen EAGLE list (filters on `iseagle`). Cross-link them. Sidebar TOC (`_data/sidebars/spcoast_sidebar.yml`) gains **two adjacent entries** — `KiCad Projects` → `/electronics.html` and `Eagle Projects` → `/eagle-archive.html` — replacing the current `Electronics` entry in place. When the EAGLE→KiCad migration completes, `eagle-archive.html` and its sidebar entry retire without disturbing the live page.
- **Front-matter alignment is good.** The plan's KiCad contract is a small variant of the populated EAGLE shape; no schema redesign needed in the theme/layout.

## Evidence

### 1. Build path: GitHub Actions, not GH Pages plugin allowlist
`.github/workflows/jekyll.yml` runs `bundle exec jekyll build` on Ruby 3.2 with `JEKYLL_ENV=production`, uploads `_site` as a Pages artifact via `actions/deploy-pages@v4`. The `Gemfile` pins `jekyll ~> 4.3` + `jekyll-remote-theme` + `kramdown-parser-gfm` + `jekyll-feed`. Whitelist friction is **not a migration trigger** here — any Jekyll plugin can be added at will. This invalidates one of the plan's three named triggers up front.

### 2. iBOM embedding: zero friction
InteractiveHtmlBom emits a self-contained HTML file. Embedding options:
- Drop into `versions/<Project>/<Revision>/ibom.html` and link from `artifacts[]` (zero Liquid changes).
- Iframe inline in `eagle.html` (one Liquid conditional).
Neither requires a Jekyll plugin. No existing iBOM HTML found under `_versions/` — confirmed greenfield for kproj.

### 3. Build time: not a near-term concern
`_versions/` currently holds ~106 entries; `pages/` ~144. Jekyll 4 builds this in seconds. The plan's "100+ versions" threshold is past, with no observed pain. The two O(n) `where` filters in `electronics.html` are cheap; extending to two more is O(n) total still.

### 4. Liquid limits: not hit
The existing `eagle.html` layout already does the non-trivial work kproj needs:
- Per-version tabs (Bootstrap 3 `nav-tabs`) keyed off `site.versions | where: "project", page.project | reverse`.
- Status-driven callouts (`mature` / `released` / `replaced` / `broken` / `experimental` / fallback) via theme `include`s.
- Image-gallery grouping with row breaks on basename change.
- Artifact list with type discrimination.
- Tag rendering against `site.data.tags.allowed-tags`.
Nothing in kproj's draft contract requires logic the current Liquid templating can't express.

### 5. Theme is a remote dependency
`_config.yml` sets `remote_theme: plocher/documentation-theme-jekyll@gh-pages`. There is no local `_includes/` — `{% include note.html %}`, `{% include callout.html %}`, `{% include disqus.html %}`, `{% include custom/X.html %}` all come from the remote theme. **Implication for kproj's `site` step:** no theme changes are needed on the content repo side; the theme already exposes the callout helpers the eagle layout uses.

### 6. Front-matter contract delta vs. live EAGLE shape
Sampled `_versions/IO4-Turtle/4.6B.md`:
```yaml
iseagle: true
layout: eagle
sidebar: spcoast_sidebar
project: IO4-Turtle
title: 4.6B
designer: John Plocher
fabricated: yes
fab_date: 2018-03
image_path: IO4-Turtle-Graphic.png
status: released
release: yes
tags: [eagle, SPCoast]
tagline: <one-line>
overview: |
  ...
images:
  - {image_path, title}
artifacts:
  - {path, tag, type, post}
```
Delta to the plan's KiCad contract:
- `iseagle: true` → `iskicad: true` (or `'obsolete'`)
- `fabricated`/`fab_date`/`release` → drop or repurpose; kproj uses `${ISSUE_DATE}` (emitted as `YYYY.MM` into `date:` field).
- `tags` becomes `[<company>, kicad]` instead of `[eagle, SPCoast]` — single-source from `${COMPANY}`.
- `designer` continues to map from `${COMMENT1}` per the SPCoast convention (the survey will confirm).
- `overview` is `${COMMENT2}+${COMMENT3}` per the SPCoast convention vs. the EAGLE shape's free-form `overview: >`. Falls back to `README.md` body if Phase 1 evidence forces it.
- Adds `image_path: thumbnail.png` (generated, ~400×400 tight crop).

The shape is compatible enough that `layout: eagle` will render KiCad pages immediately. `release.yaml` fallback only needed if the survey reveals systematic gaps.

## Decisions resolved by this assessment

| Plan open decision (`Open Decisions Surfaced for the Analysis Phase`) | Resolution |
|---|---|
| #4 Site platform | **Keep Jekyll** (Actions-driven Jekyll 4, no allowlist constraint, no friction in evidence). |
| #5 Layout strategy | **Reuse `eagle.html` initially**, plan a `pcb.html` migration only when iBOM/STEP UI is a first-class need. |
| #7 Electronics page shape | **Two physical pages + two sidebar TOC entries.** `electronics.html` becomes the active KiCad landing (filters on `iskicad`); new `eagle-archive.html` hosts the frozen EAGLE list (filters on `iseagle`). Cross-linked. Sidebar adds adjacent entries `KiCad Projects` / `Eagle Projects` replacing the current single `Electronics` entry. Frames the EAGLE archive as archive; entry + page retire cleanly when migration completes. |

## Decisions deferred to child reports

- #1 Status source — pending `survey-kicad-fields` to identify which text variable in `.kicad_pro`'s `text_variables` actually owns project status.
- #2 Overview source rule — pending the same survey: does `${COMMENT2}`+`${COMMENT3}` consistently carry the overview, or do we fall back to `README.md`?
- #3 jBOM reuse boundary — pending `ingest-jbom`'s per-module recommendation.
- #6 Thumbnail recipe — Phase 1 didn't include a render harness; the recipe gets tuned during Phase 6 implementation against real boards.

## Phase 2 implications (for the architect's Gherkin grilling)

- The `site` pipeline step writes two artifacts per release:
  1. `_versions/<Project>/<Revision>.md` with the front-matter shape above (`layout: eagle`, `iskicad: true` for active; `'obsolete'` flag handled by separate process if/when a board is retired).
  2. Assets under `/versions/<Project>/<Revision>/` (renders, SVGs, `ibom.html`, fab pack zip, etc.).
- A **one-time site setup PR** (separate from any per-release run) does the page split and nav update:
  1. Rewrite `electronics.html` so its two loops filter on `iskicad: true` and `iskicad: 'obsolete'` (KiCad-active / KiCad-obsolete). Add a "Looking for EAGLE projects? → /eagle-archive.html" header link.
  2. Create `eagle-archive.html` by copying the current `electronics.html` Liquid (which already filters on `iseagle`) and adding an "Archive — EAGLE designs" framing plus a back-link to `/electronics.html`.
  3. Update `_data/sidebars/spcoast_sidebar.yml`: replace the single `Electronics → /electronics.html` entry (currently lines 14–16) with two adjacent entries:
     ```yaml
     - title: KiCad Projects
       url: /electronics.html
       output: web
     - title: Eagle Projects
       url: /eagle-archive.html
       output: web
     ```
     `_data/topnav.yml` does not need touching — it only holds external GitHub-repo links.
  4. After this setup PR, kproj's per-release runs never touch `electronics.html`, `eagle-archive.html`, or the sidebar — they only emit the per-release version+pages files.
- Theme is not touched by kproj — out of scope for the `site` step.
- Open follow-up for Phase 2: confirm whether `pages/<Project>.md` for KiCad projects also gets `iskicad` (likely yes, to keep `electronics.html`'s `site.pages | where: "iskicad"` loop hitting the parent-project entries the same way the current `iseagle` loop does).

## Risks / surprises

- The remote theme repo (`plocher/documentation-theme-jekyll@gh-pages`) is a hard dependency. If the theme is ever forced into breaking changes, kproj's site output continues to work, but the visual layer is at the theme's mercy. Not a kproj concern, but worth a one-line ADR.
- The EAGLE archive has stale fields (`fabricated`, `fab_date`, `release` boolean) that `eagle.html` reads. KiCad pages will leave these blank; the existing layout's defensive `{% if X != '' %}` checks handle that, but the Phase 2 grilling should confirm no template branch falls through to an "UNKNOWN ARTIFACT" or "UNPUBLISHED" message on KiCad pages.
- `eagle.html` hardcodes the "Fork project on GitHub" link to `site.github_username` (plus a SethNeumann override for the `MRCS` tag). KiCad pages may or may not want this — surface in Phase 2.
