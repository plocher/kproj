# ADR 0011: iBOM UI Customization via user.css/user.js, Not Generated-HTML Splicing
Date: 2026-07-17
Status: Accepted
Related: ADR 0008 (iBOM direct script invocation), ADR 0009 (KicadInstallLocator)

## Context

kproj applies a small set of SPCoast house-style tweaks to every generated iBOM page: compact column widths, default hidden columns (checkboxes/Footprint), a "References" -> "Ref" cosmetic relabel, and (as of the RCA below) a provenance banner. The original implementation (`IbomGenerator._customize_ibom_html_defaults`) applied these by regex/string-replacing literal anchor text directly inside iBOM's *generated* HTML output, after the subprocess call.

This broke in production: a column-visibility dropdown regression (only one menu entry rendering) traced back to one of these splices squeezing the exact table cell that hosts the dropdown (`th.numCol`). Anchor-text splicing is inherently fragile - it silently no-ops if the anchor text shifts even slightly between iBOM releases, and it required "sanity guard" patches layered on top of earlier patches to repair state corruption the splicing approach itself could cause.

Investigating iBOM's own source (`InteractiveHtmlBom/core/ibom.py::generate_file`) surfaced a documented, versioned customization surface that was never used: iBOM reads `user.css` / `user.js` (and `userheader.html` / `userfooter.html`) from `<install-root>/web/` and embeds their content into every generated page via its own `///USERCSS///` / `///USERJS///` placeholders - see https://github.com/openscopeproject/InteractiveHtmlBom/wiki/Customization. `user.css` is appended after iBOM's built-in stylesheet (same-specificity selectors win by source order, no anchor matching needed); `user.js` runs in the same script scope, with a documented event API (`EventHandler.registerCallback(IBOM_EVENT_TYPES.BOM_BODY_CHANGE_EVENT, ...)`) that the maintainer commits to not breaking silently. This is also the exact mechanism iBOM's own maintainer recommends for the "hide specific columns" use case (issue #167).

## Decision

`IbomGenerator` no longer post-processes generated HTML. `write_ibom_user_files()` (a module-level function in `kproj.services.ibom_generator`) writes kproj-owned `user.css`/`user.js` content directly into `<ibom_script.parent>/web/` - a location derived from the already-resolved `ibom_script` path (ADR 0009's `find_ibom_script()`), so no new discovery logic is needed. Both files carry a "Managed by kproj - regenerated on every publish, do not hand-edit" header and are written unconditionally (idempotent) on every publish, independent of whether iBOM's own subprocess actually reruns.

Customizations that have a native CLI flag (`--checkboxes`, `--bom-view`, `--layer-view`, `--extra-fields`, `--dnp-field`, etc.) continue to use that flag; `user.css`/`user.js` is reserved for customizations iBOM's CLI has no flag for.

## Consequences

### Positive

- No anchor-text matching against iBOM's own source at all - immune to iBOM's own internal refactors as long as the documented `user.css`/`user.js` mechanism and event API stay stable (which the upstream maintainer explicitly commits to).
- Eliminates an entire class of self-inflicted bugs: the old "sanity guard" logic existed only to repair corruption the splicing approach itself could cause. Seeding a default through iBOM's own storage-key convention (`localStorage` + `storagePrefix`, only when unset) needs no repair logic, because there's nothing to corrupt.
- `write_ibom_user_files()` running independently of `needs_regen` (see `PublishWorkflow.run`) means a stale/wiped `web/` directory (e.g. after a Plugin and Content Manager reinstall) self-heals on the very next publish, for any project.

### Tradeoffs

- **Shared, machine-global state.** `<ibom_script.parent>/web/user.css`/`user.js` live inside the single, globally-installed iBOM plugin directory - not per-kproj-project, not per-kproj-version. Every kproj-managed project on this machine gets the same SPCoast house style, and whichever kproj install (a PyPI/Homebrew release, or a dev/editable `uv run` checkout) last ran `write_ibom_user_files()` is the one whose content is currently sitting there, with no per-caller isolation. This is a deliberate, accepted last-writer-wins design, not a bug: kproj's customizations are intentionally uniform across all managed projects, and the write is cheap/idempotent/self-healing rather than something that needs locking or per-project scoping. It does mean two *different* kproj installs (or two kproj processes for two different projects) running concurrently on the same machine could interleave writes; kproj v1 has no user base large enough to justify guarding against that today.
- Anything that still genuinely requires reaching into iBOM's generated *output* (not customizable via `user.css`/`user.js`, e.g. because it needs to change a source-of-truth internal field name, not just presentation) has no equivalent - see the escalation policy below.

### Reversibility

`write_ibom_user_files()` is a small, self-contained function called from exactly one place (`PublishWorkflow.run`, right after the iBOM script path is resolved). If iBOM's `user.css`/`user.js` mechanism is ever deprecated upstream, only this function and its two template constants (`_IBOM_USER_CSS_TEMPLATE`, `_IBOM_USER_JS_TEMPLATE`) need to change; the rest of the pipeline is unaffected.

## Escalation policy: upstream PR vs. fork, not more customization

A repeated need to modify iBOM behavior beyond what `user.css`/`user.js` can express (i.e. anything that isn't achievable via CSS overrides, the documented JS event API, or an existing CLI flag) is a signal to escalate, not to accumulate more bespoke JS/CSS post-processing:

1. **First choice: submit an upstream PR to `openscopeproject/InteractiveHtmlBom`.** iBOM is actively maintained, has an open, documented customization surface, and the maintainer has repeatedly added CLI flags / customization hooks in response to user requests (see issue #167, PR #239 for column hiding/reordering). A change that benefits SPCoast likely benefits other users too.
2. **Second choice, only if (1) is impractical** (too SPCoast-specific to be acceptable upstream, or urgency doesn't allow waiting on a release cycle): vendor/fork iBOM into kproj's own tree for tighter integration, rather than growing `user.css`/`user.js` into an increasingly elaborate simulation of a fork via runtime patching.

This policy is deliberately not acted on preemptively - the current `user.css`/`user.js` content is adequate for SPCoast's present needs. This section exists so the *next* time a customization doesn't fit cleanly into `user.css`/`user.js`, the decision criterion is already written down rather than reinvented under time pressure.

## References

- ADR 0008 - iBOM direct script invocation (how kproj invokes the script this ADR's `web/` directory sits beside).
- ADR 0009 - KicadInstallLocator (`find_ibom_script()`, the source of the `web/` directory's parent path).
- iBOM Customization wiki: https://github.com/openscopeproject/InteractiveHtmlBom/wiki/Customization
- iBOM issue #167 ("Make Footprint and Value fields optional") - the maintainer's own `user.js` recipe for hiding BOM columns, the direct precedent for this decision.
- iBOM PR #239 - "BOM Column hiding and reordering", the native feature (`#vismenu`/`#vismenu-content`) that the regression this ADR's context section describes was ultimately traced to.
