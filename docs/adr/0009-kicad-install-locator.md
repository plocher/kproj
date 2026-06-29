# ADR 0009: KicadInstallLocator Utility
Date: 2026-06-29
Status: Accepted
Related: ADR 0006 (Library-shape boundary discipline), ADR 0008 (iBOM direct script)

## Context

kproj invokes `kicad-cli` (for PCB renders, STEP export, schematic SVG/PDF, DRC, ERC) and the iBOM Python script (per ADR 0008). Both live inside the KiCad install root but are not always reachable through conventional means:

- **macOS**: KiCad's stable install path is `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli`. The system PATH does not include this directory. Running `kicad-cli` from a Makefile shell or CI environment fails.
- **iBOM script path**: documented as `${KICAD9_3RD_PARTY}/plugins/org_openscopeproject_InteractiveHtmlBom/generate_interactive_bom.py`. `KICAD9_3RD_PARTY` is set by the KiCad GUI session, but is generally not exported to Makefile / launchd / sshd / CI shells.
- **Linux**: `kicad-cli` is typically on `$PATH` (`/usr/bin/kicad-cli` from distro packages), but the PCM plugins directory varies by user install.
- **Windows**: `C:\Program Files\KiCad\9.0\bin\kicad-cli.exe` — also not always on PATH.

Phase 4 review (gpt-5-5-xhigh) flagged this as a MAJOR finding: DESIGN's subprocess examples invoke bare `kicad-cli` and reference `${KICAD9_3RD_PARTY}` as if it were always set. Phase 6 unit tests with mocked subprocess would pass; the user's actual Makefile invocation would fail.

jBOM has a private `_find_kicad_cli()` inside `jbom.services.gerber_service` that already encodes the macOS path. The locked plan mentioned exposing this as a jBOM upstream PR (#2) and reusing it from kproj. That PR has not landed; making kproj's iBOM pre-flight depend on it would create an unnecessary cross-repo coupling.

## Decision

kproj v1 has its own **`common/kicad_install.py`** module exposing **plain functions** (per user direction during Phase 4 resolution — not a Producer-Pattern service):

```python path=null start=null
# src/kproj/common/kicad_install.py

def find_kicad_cli() -> Path:
    """Return the kicad-cli executable path, or raise KicadNotFoundError.
    Probing order:
      1. ~/.kproj.yaml's 'kicad_cli' key (if set)
      2. KPROJ_KICAD_CLI environment variable (if set)
      3. Platform-specific defaults:
         - macOS: /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli
         - Linux: /usr/bin/kicad-cli, /usr/local/bin/kicad-cli
         - Windows: C:\\Program Files\\KiCad\\9.0\\bin\\kicad-cli.exe
      4. PATH lookup via shutil.which('kicad-cli')
    """

def find_plugins_dir() -> Path:
    """Return the KICAD9_3RD_PARTY plugins root, or raise KicadNotFoundError.
    Probing order:
      1. KICAD9_3RD_PARTY environment variable (if set)
      2. Platform-specific defaults:
         - macOS: ~/Documents/KiCad/9.0/3rdparty/
         - Linux: ~/.local/share/kicad/9.0/3rdparty/
         - Windows: %APPDATA%\\kicad\\9.0\\3rdparty\\
    """

def find_ibom_script() -> Path:
    """Return the iBOM generator script path, or raise KicadNotFoundError.
    Resolves <plugins_dir>/plugins/org_openscopeproject_InteractiveHtmlBom/generate_interactive_bom.py.
    Pre-flight failure when missing is a hard exit-2 (per ADR 0008)."""

def kicad_version(kicad_cli: Path) -> tuple[int, int, int]:
    """Parse `kicad-cli --version` output. Returns (major, minor, patch).
    Used by pre-flight to enforce the supported major version (9.x for v1)."""
```

All kproj subprocess-invoking services receive a resolved `kicad_cli: Path` (and, for IbomGenerator, an `ibom_script: Path`) at construction time. They never invoke bare `kicad-cli` or interpolate `${KICAD9_3RD_PARTY}` themselves.

PublishWorkflow's pre-flight calls all three locator functions early and includes the discovered paths + `kicad_version()` in the run's stderr summary (so users can confirm which install is being used).

### Where this lives

`src/kproj/common/kicad_install.py` — **utility module**, not a service. Plain functions, no class. This matches jBOM's pattern of putting `_find_kicad_cli` inside `jbom.services.gerber_service` (a utility inside a service file), and aligns with the user's Phase 4 direction.

The function-style API is intentional: locator results are pure values, idempotent within a process run, and don't carry Finding diagnostics — they either return a Path or raise. The Producer Pattern (constructor + primary method + diagnostics) is overkill here.

## Consequences

### Positive

- kproj works on the user's macOS install out of the box without manual PATH/environment setup.
- All subprocess services have a single discovered binary path injected at construction — eliminates "did kproj pick up the right kicad-cli?" ambiguity.
- The pre-flight emits the resolved paths to stderr at default verbosity (one line per run), making install issues self-diagnosing.
- jBOM upstream PR #2 (`find_kicad_cli` exposure) is no longer a kproj prerequisite. It is welcomed (kproj can switch to it later for consistency), but not required.

### Tradeoffs

- Some duplication with jBOM's private `_find_kicad_cli`. Mitigation: when the jBOM upstream PR lands, kproj's `find_kicad_cli()` becomes a thin wrapper around `jbom.services.gerber_service.find_kicad_cli()`; the kproj-side function signatures stay stable.
- The platform-specific path tables are a maintenance liability if KiCad changes its install layout. Mitigation: the probing order tries explicit overrides first (`~/.kproj.yaml` + env var), so users on non-default installs can override without code changes.

### Reversibility

The `kicad_install` module is internal to kproj. If a better approach emerges (e.g. a dedicated `kicad-installation-locator` PyPI package), the function signatures stay stable and only the bodies change. Services depend only on the function signatures.

## References

- ADR 0006 — Library-shape boundary discipline. `kicad_install` is a `common/` utility (allowed); services depend on it via injection at construction, not import.
- ADR 0008 — iBOM direct script invocation depends on `find_ibom_script()`.
- jBOM `src/jbom/services/gerber_service.py` `_find_kicad_cli()` — the prior art kproj's `find_kicad_cli()` mirrors.
- Phase 4 review finding: MAJOR M6 — "kicad-cli locator/version preflight is incomplete".
