# ADR 0004: "Show What Is Provided" Audit Policy
Date: 2026-06-29
Status: Accepted
Related: ADR 0002 (A/B split), jBOM ADR 0006 (Diagnostic Collection Principle)

## Context

Most CI tools and release pipelines treat warnings and errors as gates: stop the pipeline on findings, force the user to clean up before proceeding. This is the conventional CI mental model.

kproj's audit module surfaces metadata-quality findings (placeholder values, missing `${COMMENT9}`, SCH/PCB title-block disagreements, date-format violations, etc.). KiCad's DRC and ERC surface design-quality findings (track-spacing violations, ERC mismatches, etc.). If kproj applied the conventional CI model, every finding would block publish — leaving the user with a binary "fix everything then publish, OR see nothing at all" choice.

The user's framing during Phase 2 grilling: the SPCoast site is a **developer-time tool**, not just a customer-facing production catalogue. Visitors include the developer themselves, mid-iteration, who benefits from seeing project state honestly — including known issues — rather than only polished-final views.

## Decision

kproj v1 audit, DRC, and ERC findings are **surfaced, never blocking**.

### What "surfaced" means

Every finding appears in multiple surfaces simultaneously (per the Diagnostic Collection Principle inherited from jBOM ADR 0006):

1. **stderr** — human-readable, one finding per line: `<severity> [<step>] <project>:<field>: <reason> (value: <value>)`. CI logs, terminal, copy-paste-friendly.
2. **Markdown table embedded in the version page content body** — `_versions/<P>/<R>.md` below the front-matter. Visitors to the site see the audit + DRC/ERC tables when they view the version page.
3. **Front-matter summary** — `audit: {errors: N, warnings: M}`, `drc: {errors: N, warnings: M, exclusions: K}`, `erc: ...` so the layout can render badges at the top of the version page.
4. **Structured Findings list** — internal `Finding(severity, project, field, value, reason)` dataclasses, available for future formatters (JSON output, dashboards, etc.).

### What "never blocking" means

- kproj v1 has **no `--force` flag** — nothing blocks, nothing to override.
- DRC errors do NOT cause kproj to exit non-zero. The publish proceeds; the errors are visible.
- Audit errors do NOT cause kproj to exit non-zero. Same.
- Exit code 1 signals "findings present" (informational); exit code 2 signals "mechanical failure" (file missing, plugin not installed, git push rejected). See `docs/DESIGN.md` for the exit-code mapping spec.

### Severities are labels, not gates

KiCad's DRC severity vocabulary (`error` / `warning` / `exclusion`) is preserved in the published output. kproj's audit uses two severities (`error` / `warning`); no `exclusion` because audit has no per-violation suppression UI equivalent. All severities surface; none block publish in v1.

### Where the strict bar lives

The (B) release-lifecycle layer (tag, gh-release) is where strict quality gating belongs — see ADR 0002. When (B) is built (post-v1), tag creation will refuse on DRC errors unless explicitly overridden. The audit/DRC visibility in (A) feeds the user's decision to advance to (B); (B) enforces the bar.

## Consequences

### Positive

- Site reflects actual project state honestly. Visitors (incl. the developer) see issues in context.
- Developer can iterate freely — fix metadata, re-publish, see the audit deltas — without the friction of pipeline gates.
- The strict-quality-bar discipline lives where it belongs: at release time (B), not at publish time (A).
- Aligns with the "publisher of point-in-time snapshot" framing of ADR 0002.

### Tradeoffs

- Published version pages may carry known issues. Readers must check the audit/DRC tables to know the trustworthiness of a given snapshot.
- Mitigation: front-matter badge counts make issue density visible at a glance.
- A user who expects "release tools" to enforce quality may find the v1 leniency surprising.
- Mitigation: ADR 0002 + ADR 0007 make the v1 scope explicit. Strict gating is (B)-layer's job.

### Reversibility

The "never blocking" stance is a v1 default. A future `--strict` flag (or `kproj-strict` sibling) could promote errors to release-blocking. Adding strictness is mechanical; the data structures (Finding severity, exit codes) already support it. The decision here is to default to lenient for v1, not to forbid strict forever.
