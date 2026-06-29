# kproj

KiCad project Jekyll publisher for the SPCoast site.

`kproj` takes a point-in-time snapshot of a KiCad project (renders, schematic SVG/PDF, interactive HTML BOM, fabrication artifacts, KiCad source archive) and publishes it as a version entry on the SPCoast Jekyll site.

## Status

**Phase 3 (PRD authoring)** — v1 design is locked, implementation has not started.

- ✅ Phase 0 — scope contract
- ✅ Phase 1 — analysis (jBOM reuse map, KiCad metadata survey, site platform assessment, audit prototype)
- ✅ Phase 2 — informed grilling (locked v1 vocabulary in [`docs/GLOSSARY.md`](docs/GLOSSARY.md))
- 🔄 Phase 3 — PRD + architecture proposal
- ⏳ Phase 4 — adversarial review
- ⏳ Phase 5 — issue breakdown into vertical tracer-bullet slices
- ⏳ Phase 6 — TDD implementation
- ⏳ Phase 7 — validation + PR + merge

## v1 contract — quick orient

Full glossary in [`docs/GLOSSARY.md`](docs/GLOSSARY.md); v1 requirements in [`docs/PRD.md`](docs/PRD.md); implementation specs in [`docs/DESIGN.md`](docs/DESIGN.md). Headlines:

- **What v1 is**: a local CLI Jekyll publisher. One invocation publishes a point-in-time snapshot of a KiCad project to the SPCoast site.
- **What v1 isn't**: a release-lifecycle tool. No `git tag`, no `gh release create`, no CI integration. Those are the (B) lifecycle layer, composed externally via Makefile.
- **Pipeline**: `render` → `ibom` → `fab` → `publish`. Four steps.
- **CLI surface**: `kproj [<project-or-dir-or-file>] [--dry-run] [--no-push] [-v|--verbose] [-d|--debug]` — five flags total.
- **Config**: `~/.kproj.yaml` (`site_repo`, `no_push`). Env vars (`KPROJ_*`). CLI flag highest precedence.
- **Audit + DRC/ERC**: surfaced on the version page (Markdown table) and stderr; **never blocking** in v1.
- **WriteTracker rollback**: site-repo writes are transactional. Mid-pipeline failure rolls back cleanly. No stray-file pollution across batch runs.
- **Exit codes**: 0 clean / 1 findings present / 2 mechanical failure.

## Research artifacts

- [`docs/GLOSSARY.md`](docs/GLOSSARY.md) — canonical vocabulary (terms-only; Phase 2 deliverable).
- [`docs/PRD.md`](docs/PRD.md) — v1 user-facing requirements (Phase 3 deliverable).
- [`docs/DESIGN.md`](docs/DESIGN.md) — v1 implementation specs (Phase 3 deliverable).
- [`docs/adr/`](docs/adr/) — Architecture Decision Records (Phase 3 deliverable; 7 entries).
- [`docs/phase1/jbom-reuse-map.md`](docs/phase1/jbom-reuse-map.md) — module-by-module jBOM reuse analysis.
- [`docs/phase1/kicad-metadata-survey.md`](docs/phase1/kicad-metadata-survey.md) — survey of `${COMMENT1..9}` / `${REVISION}` / `${COMPANY}` / `${ISSUE_DATE}` population across the SPCoast KiCad corpus, plus structured `survey.json`/`.csv`.
- [`docs/phase1/site-platform-assessment.md`](docs/phase1/site-platform-assessment.md) — keep-Jekyll site-platform decision.
- [`docs/phase1/audit-rerun/`](docs/phase1/audit-rerun/) — audit-prototype script + outputs (seed for the v1 `--dry-run` quality lint).

## Toolchain

- Python ≥3.11
- `uv` for environment + dependency management (`uv sync`, `uv run`, CI uses `uv sync --frozen`)
- `argparse` for CLI parsing (no external CLI framework dependency)
- `hatchling` build backend
- `pytest` + `behave` for testing (Phase 6)
- `ruff` + `mypy` for linting + type-checking

## Composition with other tools

kproj is one tool in a small ecosystem. The release-lifecycle workflow composes via Makefile (see [`templates/Makefile.kicad`](templates/Makefile.kicad)):

- `jbom fab` — generates fabrication artifacts (bom.csv, pos.csv, gerbers.zip) into `./production/`. Invoked separately by the user before `kproj`.
- `kproj` — reads `./production/` + KiCad project files, publishes a snapshot to the SPCoast site.
- `git tag` + `gh release create` (manual or Makefile-driven) — the (B) release-lifecycle layer, external to kproj.

## License

MIT — see [`LICENSE`](LICENSE).
