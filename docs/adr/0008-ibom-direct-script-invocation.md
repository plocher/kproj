# ADR 0008: iBOM via Direct Script Invocation
Date: 2026-06-29
Status: Accepted (amended 2026-07-01, see Amendment 1)
Related: ADR 0007 (Local-CLI v1), ADR 0009 (KicadInstallLocator)
Supersedes: Plan § Phase 1 Closeout / Locked Decisions / iBOM invocation

## Context

Phase 1 closeout locked iBOM invocation as `kicad-cli jobset run` against a kproj-generated `.kicad_jobset` file. The architectural intent was sound:

- Treat iBOM as a plugin, not a library or hard dependency.
- Let KiCad's job runner resolve the plugin script path, so kproj never hardcodes `generate_interactive_bom.py` location.
- Compose with KiCad's existing job format rather than inventing a new invocation convention.

Phase 4 adversarial review (gpt-5-5-xhigh) flagged the DESIGN doc had drifted to direct invocation of `generate_interactive_bom.py` as a `BLOCKER` because it contradicted the locked plan.

User correction during Phase 4 resolution: **the plan is stale, not DESIGN**. The user's lived experience with `kicad-cli jobset run` is that the job runner requires a running KiCad instance (the GUI process being available to coordinate plugin execution). That fundamentally conflicts with Phase 0 scope contract / ADR 0007's locked decision that kproj must run non-interactively in a Makefile or CI context, with no GUI assumed.

The architect did not catch this when authoring Phase 1 closeout. The drift in DESIGN was the right answer; the lock was based on incorrect operational assumptions.

## Decision

kproj v1 invokes the iBOM generator script **directly** via `subprocess.run`:

```text path=null start=null
<python> <ibom-script> --no-browser --no-compression
        --dest-dir <out>
        --name-format "<P>-<R>.ibom"
        --extra-data-file <pcb>
        --dnp-field kicad_dnp
        --extra-fields MPN,Manufacturer
        --include-tracks
        <pcb>
```

The `<ibom-script>` path is discovered by the `KicadInstallLocator` utility (ADR 0009), not hardcoded. Pre-flight failure when the iBOM plugin is not installed is a hard exit-2 mechanical failure (per user direction during Phase 4 resolution).

The `<python>` interpreter is **KiCad's bundled Python** (see Amendment 1 below). The original decision claimed it could be `sys.executable`; that was wrong and is corrected there.

## Consequences

### Positive

- Works non-interactively in a Makefile or CI without a running KiCad GUI process.
- Direct path to the script means clearer failure modes (FileNotFoundError on the script path, subprocess non-zero return otherwise) — no opaque "job runner failed" diagnostics from KiCad.
- No `.kicad_jobset` file generation needed inside kproj — one fewer artifact, one fewer file format to learn.
- Aligns with the actual workflow the user has already validated for iBOM generation in the SPCoast corpus.

### Tradeoffs

- kproj depends on the iBOM script's CLI surface remaining stable. iBOM's CLI has been stable across recent KiCad PCM releases; risk is low.
- Future migration to iBOM's IPC-API backend (openscopeproject/InteractiveHtmlBom#555) when KiCad 11 ships will require revisiting the invocation — but it would require revisiting `kicad-cli jobset run` too, so this is not a regression.

### Reversibility

If `kicad-cli jobset run` ever gains a headless mode (or KiCad's plugin architecture changes such that the job runner no longer requires a GUI), kproj can revert to the jobset approach by replacing the iBOM subprocess command — the rest of the pipeline is unaffected. The IbomGenerator service contract isolates the invocation from the rest of kproj.

## Amendment 1 (2026-07-01): the interpreter is KiCad's bundled Python, not `sys.executable`

The original Decision stated the `<python>` interpreter "is the same Python that runs kproj — the iBOM script is a portable Python module ... runnable in any modern Python environment." **This is incorrect.** The PCM iBOM script (`generate_interactive_bom.py`) does `import pcbnew` unconditionally, and `pcbnew` is a SWIG-bound C-extension that resolves **only** inside KiCad's own bundled Python interpreter — never in kproj's `uv`-managed venv. Invoking iBOM with `sys.executable` fails immediately with `ModuleNotFoundError: No module named 'pcbnew'` (surfaced as the Phase G blocker; see [kproj#10](https://github.com/plocher/kproj/issues/10)).

Corrected decision:

- `<python>` is **KiCad's bundled Python interpreter**, located by `common.kicad_install.find_kicad_python()` (ADR 0009 locator family). The interpreter is derived from the same KiCad install anchor as `kicad-cli` (single source of truth), with a `KPROJ_KICAD_PYTHON` env override. macOS derivation is implemented; Linux / Windows are documented follow-ups in kproj#10.
- `IbomGenerator.__init__` takes a **required** `python_exe: Path` (no default, so no caller can silently fall back to `sys.executable`). The workflow resolves it in pre-flight (step 5a) alongside the iBOM script; a miss is the same hard exit-2 mechanical failure as a missing iBOM plugin, before any change journal opens.
- The `INTERACTIVE_HTML_BOM_NO_DISPLAY=1` env var (already set by `IbomGenerator`) remains required so the script runs headless without wxPython.

The direct-script-invocation decision itself (vs `kicad-cli jobset run`) is unchanged; only the interpreter-choice nuance is corrected.

### Plan staleness

This ADR explicitly supersedes the Phase 1 closeout iBOM invocation line. The plan document gets an inline note pointing here.

## References

- ADR 0007 — Local-CLI v1, CI deferred (the non-interactive use case this ADR supports).
- ADR 0009 — KicadInstallLocator (discovers the script path).
- Plan `496d47fb-92d5-49d9-bbb0-5dea1bf0e99c` § Phase 1 Closeout → Locked decisions → "iBOM invocation" (the line being superseded).
