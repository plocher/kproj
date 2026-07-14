# kproj development history

This file preserves the retired phase tracker that used to live in `README.md`.
It is historical project-planning context only; the current PyPI-facing README
describes the released v0.3.x tool.

## Retired v1 phase tracker

- ✅ Phase 0 — scope contract
- ✅ Phase 1 — analysis (jBOM reuse map, KiCad metadata survey, site platform assessment, audit prototype)
- ✅ Phase 2 — informed grilling (locked v1 vocabulary in `CONTEXT.md`)
- ✅ Phase 3 — PRD + architecture proposal
- ✅ Phase 4 — adversarial review
- ✅ Phase 5 — issue breakdown into vertical tracer-bullet slices
- ✅ Phase 6 — TDD implementation
- ✅ Phase 7 — validation + PR + merge

Note: the Phase 1 site-platform assessment's "keep Jekyll" recommendation
was later overturned; production kproj targets Hugo via the `SiteProfile`
abstraction (see the supersession note atop `docs/phase1/site-platform-assessment.md`).

## Research artifacts

- [`CONTEXT.md`](../CONTEXT.md) — canonical vocabulary (terms-only; Phase 2 deliverable).
- [`docs/PRD.md`](PRD.md) — v1 user-facing requirements (Phase 3 deliverable).
- [`docs/DESIGN.md`](DESIGN.md) — v1 implementation specs (Phase 3 deliverable).
- [`docs/adr/`](adr/) — Architecture Decision Records.
- [`docs/phase1/jbom-reuse-map.md`](phase1/jbom-reuse-map.md) — module-by-module jBOM reuse analysis.
- [`docs/phase1/kicad-metadata-survey.md`](phase1/kicad-metadata-survey.md) — survey of `${COMMENT1..9}` / `${REVISION}` / `${COMPANY}` / `${ISSUE_DATE}` population across the SPCoast KiCad corpus, plus structured `survey.json`/`.csv`.
- [`docs/phase1/site-platform-assessment.md`](phase1/site-platform-assessment.md) — the (later-superseded) keep-Jekyll site-platform decision.
- [`docs/phase1/audit-rerun/`](phase1/audit-rerun/) — audit-prototype script + outputs (seed for the v1 `--dry-run` quality lint).
