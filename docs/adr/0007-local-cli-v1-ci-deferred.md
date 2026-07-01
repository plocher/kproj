# ADR 0007: Local-CLI v1, CI Integration Deferred
Date: 2026-06-29
Status: Accepted
Related: ADR 0002 (A/B split)

## Context

Most "release pipeline" tools assume CI/CD integration from day one — they run inside GitHub Actions on push to main, manage secrets, push to remote repos via PATs, etc. The initial framing during Phase 2 grilling considered this: "kproj runs in CI on every push; most pushes are no-ops because PCB REVISION hasn't changed."

The user's pushback during grilling: cross-repo CI is non-trivial. The project repo's GH Actions runner needs:
- A PAT with push access to the SPCoast site repo.
- Secrets management for that PAT (org-level secret, environment, etc.).
- Concurrency handling: two project repos pushing simultaneously could race on the site repo.
- An understanding of the site repo's branching/deployment model.

None of that has to be solved to deliver kproj v1's value. The simpler runtime model — user invokes `kproj` locally against a checked-out KiCad project, kproj writes to the local SPCoast site repo checkout, commits, pushes from the user's machine — works fine for v1 and matches the user's existing Makefile-driven habits.

## Decision

kproj v1 is a **local CLI tool**. Invoked manually by the user against a KiCad project on disk. Writes to a local checkout of the SPCoast site repo (path from `--site-repo` flag, `KPROJ_SITE_REPO` env var, `~/.kproj.yaml`'s `site_repo` key, or the hardcoded fallback in `src/kproj/config.py::DEFAULT_SITE_REPO`). Commits, pushes via the user's locally-configured git credentials.

### Specifically excluded from v1

- GitHub Actions workflow for kproj.
- Cross-repo PAT credential management.
- Push concurrency handling (kproj v1 assumes only one user runs at a time).
- Project-repo CI integration (no `.github/workflows/kproj.yml` in project repos).

### Specifically reserved for Phase 6+

- A future kproj CI integration story may include: a kproj-callable GH Action, a recipe for cross-repo PAT setup, concurrency handling via GH Actions `concurrency: group:` keys, etc.
- The cross-repo push problem is non-trivial enough to deserve its own design pass, informed by v1 usage experience.

## Consequences

### Positive

- v1 has no secrets. No PAT to manage, no env var to set, no `.github/secrets/` entry.
- v1 is debuggable on the user's own machine. `git diff` shows what kproj did; `git reset` undoes it.
- v1 matches the user's existing Makefile-driven workflow (see `templates/Makefile.kicad`). `make publish` runs `kproj`; no CI yaml needed.
- The "every push" automatic-trigger framing that surfaced briefly during grilling proved to be over-engineering for v1 needs; local invocation is the simpler, sufficient model.

### Tradeoffs

- kproj runs are user-initiated, not automatic on commit. The user must remember to `make publish` after editing project metadata.
- Mitigation: the Makefile target is one command; embedding it in a project workflow (e.g. as part of `make release`) is mechanical.
- Mitigation: the audit's `--dry-run` mode lets the user quickly check "is anything stale on the site for this project?" without a full publish.
- Multi-machine workflows are awkward — if the user works on the same project from two machines, they must each invoke kproj. No "kproj-as-a-service" auto-publish.
- Mitigation: deferred to Phase 6+ when CI integration is in scope.

### Reversibility

CI integration is **additive**: Phase 6+ work can add a GH Action wrapper around kproj's CLI without changing the CLI's own contract. The kproj binary stays the same; CI just becomes another way to invoke it. So this decision is reversible by *adding*, not by rewriting. Low risk.
