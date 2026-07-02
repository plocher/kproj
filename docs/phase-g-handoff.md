# kproj Phase G — session checkpoint / handoff (2026-07-02)
Records what changed this session and what's next. Read `docs/AGENT-HANDOFF.md`
first for locked architectural decisions (Jekyll->Hugo migration, SiteProfile,
boundaries); this doc does not repeat them. Detail lives in `docs/CHANGELOG.md`
and git history — referenced here, not duplicated.
## Status: Phase G effectively complete for `cpNode-Xiao-68x90`
- Real project published end-to-end; the Hugo site is live at
  https://www.spcoast.com (KiCad Projects -> `/versions/`).
- kproj gate (local; **no CI configured on `plocher/kproj`** — local run is the
  gate): 393 pytest, 14 Behave scenarios, ruff + mypy strict clean. Commands:
  `.venv/bin/python -m pytest -q`, `.venv/bin/python -m behave tests/features`,
  `.venv/bin/ruff check src tests`, `.venv/bin/mypy src`.
## kproj — branch `fix/phase-g-validation` (see `docs/CHANGELOG.md` + git log)
- Change detection delegated to **git**; the bespoke `SitePublisher.detect_outcome`,
  `_strip_volatile`, and `force_outcome` were removed. Artifacts regenerate
  **Make-style** (source newer than the on-disk artifact, `_needs_regeneration`);
  the version-page `date` is preserved so an unchanged run is a git no-op.
- Datasheets emitted as `_index.md` front-matter data (`datasheets:`), with a
  README + DESCRIPTION body.
- Datasheet PDFs copied into the site (`static/versions/<P>/datasheets/<name>`,
  Make-style) via `_copy_datasheets` + `common.project_docs.discover_datasheet_files`.
- The git-dependent no-op/commit behaviour is validated **interactively**, not by
  unit/Behave tests (both suites mock git) — a deliberate decision this session.
## site — `SPCoast/SPCoast.github.io`, `main` (deployed); custom-minimal Hugo, no theme
- `layouts/versions/list.html`: project page (header thumbnail + README description +
  collapsible **Documentation** with datasheet PDF links + CSS `:target` version tabs);
  and the `/versions/` index (project cards grouped by first letter, EAGLE-style).
- `layouts/partials/version-panel.html`: per version — image gallery, Gerbers/Project
  downloads, Libraries Used, embedded iBOM, collapsed ERC/DRC/audit "Checks" with counts.
- `layouts/versions/single.html` deep-link; Blowfish-style narrow/wide split
  (`.wide-page` + `--max-width-wide`); `KiCad Projects` nav; home-page link; orphaned
  repo-root `versions/` removed.
- The image lightbox was **reverted** this session — see Next steps.
## Next steps (the "put back lightbox" work)
1. **CSS fingerprinting (do first — this is the root cause).** Visitors get a stale
   `main.css` after every CSS change. The "images shown twice / huge / stacked" report
   was the reverted lightbox rendered under an **old cached `main.css`** (missing
   `.lightbox{display:none}` + the gallery flex), *not* a real lightbox bug. Fix: move
   `static/css/main.css` -> `assets/css/main.css` and reference it via Hugo Pipes in
   `layouts/partials/head.html` (`resources.Get "css/main.css" | minify | fingerprint`
   -> `.RelPermalink`) so the filename is content-hashed and cache-busts automatically.
2. **Restore the image lightbox.** It almost certainly worked. Re-apply the reverted
   edits — `git -C <site> show f83a36b` gives the exact revert diff to invert:
   the checkbox-hack overlay in `version-panel.html` gallery + `list.html` header
   thumbnail, plus the `.lightbox` / `.zoom` CSS. Verify live with a hard-refresh
   (unnecessary once step 1 lands).
3. **Iterate more real projects.** Publish each with
   `kproj <path> --site-repo <site> --no-push` (or without `--no-push` to deploy);
   they drop into the grouped `/versions/` index automatically.
## Parking lot / RFEs
`docs/RFEs.md` — iBOM datasheet column (per-RefDes PDF links); clean project/version
deletion (unpublish / prune).
## Gotchas
- **Stale CSS**: until fingerprinting lands, hard-refresh after any `main.css` change;
  confirm the deployed file with `curl -s https://www.spcoast.com/css/main.css`.
- **Datasheet discovery is broad**: `discover_datasheet_files` picks up ANY `*.pdf` in
  the project tree (it only prunes hidden / `*-backups` / `production/`). Keep stray
  PDFs (e.g. a rendered `*-sitepage.pdf`) out of the project dir or they become "datasheets".
- **Deploy** = `git push origin main` on the site repo (GitHub Pages rebuilds; SPCoast
  has no PR path). kproj uses feature branch + PR on `plocher/kproj`.
- kproj's git no-op won't settle for cpNode while `production/` is incomplete (missing
  `pos.csv` -> `fab.zip` perpetually absent -> republishes each run); run `jbom fab`.
## Suggested skills
- `tdd` for any further kproj code changes (red-green-refactor; user's locked workflow).
- Read `docs/AGENT-HANDOFF.md` for the locked architectural decisions before changing publish/site behaviour.
