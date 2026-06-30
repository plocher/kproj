# kproj — Implementation Design (v1)
Phase 3 deliverable. Specifies **how** kproj v1 is built: module structure, inter-module contracts, sequencing, file/path conventions, subprocess invocations, and the testing strategy.

This document is **implementation specs**. It does not redefine vocabulary or restate decisions:
- Vocabulary → `docs/GLOSSARY.md`
- Architecture decisions → `docs/adr/`
- User-facing requirements → `docs/PRD.md`

When implementation choices evolve, update this document. When a change is *hard to reverse / surprising without context / a real trade-off*, also capture it as an ADR.

## Architecture overview

kproj follows the layered architecture inherited from jBOM ADR 0013 (referenced via ADR 0001):

```text path=null start=null
┌────────────────────────────────────────────────────┐
│ Interface (src/kproj/cli.py)                       │
│   argparse · sys.argv · sys.exit · stderr writes   │
├────────────────────────────────────────────────────┤
│ Application (src/kproj/application/)               │
│   PublishWorkflow.run(PublishRequest)              │
├────────────────────────────────────────────────────┤
│ Domain Services (src/kproj/services/, 11 modules)  │
│   KicadProjectReader · MetadataAnalyzer · ...      │
├────────────────────────────────────────────────────┤
│ Domain Model (src/kproj/model/)                    │
│   ProjectInfo · AnalysisInfo · Publication ·       │
│   Finding · Severity                               │
└────────────────────────────────────────────────────┘
```

Dependencies flow downward only. Domain Model has no dependencies beyond stdlib + a few jBOM library imports for parsing. ADR 0006 (library-shape boundary discipline) makes the layer boundaries crisp.

Cross-cutting utilities live in `src/kproj/common/` (currently `kicad_install` per ADR 0009). These are pure-function modules consumed by services via dependency injection at construction time — not a separate layer, not Producer-Pattern services.

## Source layout

```text path=null start=null
src/kproj/
├── __init__.py              # __version__ = "0.1.0"
├── cli.py                   # argparse + main() + exit-code mapping
├── config.py                # ~/.kproj.yaml + env vars + CLI precedence
├── model/
│   ├── __init__.py
│   ├── project_info.py      # ProjectInfo, Status enum
│   ├── analysis_info.py     # AnalysisInfo
│   ├── publication.py       # Publication
│   ├── finding.py           # Finding
│   └── severity.py          # Severity enum
├── services/
│   ├── __init__.py
│   ├── kicad_project_reader.py
│   ├── metadata_analyzer.py
│   ├── design_analyzer.py
│   ├── pcb_exporter.py
│   ├── schematic_exporter.py
│   ├── ibom_generator.py
│   ├── fab_packager.py
│   ├── source_packager.py
│   ├── zip_archiver.py
│   ├── site_publisher.py
│   └── change_journal.py
├── common/
│   ├── __init__.py
│   ├── kicad_install.py     # KiCad install discovery (ADR 0009)
│   └── subprocess_runner.py # Shared subprocess runner (timeouts + signals)
├── application/
│   ├── __init__.py
│   └── publish_workflow.py  # PublishWorkflow, PublishRequest, PublishResult
└── formatters/
    ├── __init__.py
    ├── stderr_formatter.py
    ├── markdown_table_formatter.py
    └── front_matter_summary_formatter.py

tests/
├── unit/                    # per-service unit tests (pytest)
│   └── ...
└── features/                # Behave Gherkin scenarios (per-Workflow)
    ├── steps/
    ├── publish.feature
    └── ...
```

## CLI surface mechanics

Argparse setup in `src/kproj/cli.py`. Parses argv → builds `PublishRequest` → calls `PublishWorkflow().run(request)` → maps `PublishResult` to exit code.

```text path=null start=null
kproj [<project-or-dir-or-file>] [--site-repo PATH] [--dry-run] [--no-push] [-v|--verbose] [-d|--debug]
```

- **Positional** — optional path; if absent, use CWD. Delegates to `KicadProjectReader.resolve(path or ".")` which wraps `jbom.application.pcb_project_loader.resolve_pcb_input()`.
- **`--site-repo PATH`** — override the site repo location. Highest precedence in the config layer (above `KPROJ_SITE_REPO` env, `~/.kproj.yaml` `site_repo` key, and the hardcoded default). Useful for testing against a scratch site repo without editing the user's primary config (per ADR 0007).
- **`--dry-run`** — boolean flag. Sets `PublishRequest.dry_run = True`.
- **`--no-push`** — boolean flag. Sets `PublishRequest.no_push = True` (or env `KPROJ_NO_PUSH=1`, or `no_push: true` in `~/.kproj.yaml`).
- **`-v` / `--verbose`** — count flag (`action="count"`). Sets `PublishRequest.verbose_level = 1` when `-v`, 2 when `-v -d` (combined).
- **`-d` / `--debug`** — boolean flag. Implementation-private dev output; not a stable interface.

`cli.py` is the only module that imports `argparse` or calls `sys.exit` (ADR 0006).

## Configuration layer

`src/kproj/config.py`: `KprojConfig` dataclass + `ConfigOverrides` dataclass + `load_config()` function. Per ADR 0006, `argparse` lives only inside `cli.py`; `cli.py` translates `argparse.Namespace` into a kproj-owned `ConfigOverrides` shape before calling `load_config()`. The config layer never imports `argparse`.

```python path=null start=null
@dataclass(frozen=True)
class ConfigOverrides:
    """CLI-derived overrides constructed in cli.py.
    None = field not provided by CLI; precedence falls through to env / yaml / default."""
    site_repo: Path | None = None
    no_push: bool | None = None
    kicad_cli: Path | None = None

@dataclass(frozen=True)
class KprojConfig:
    site_repo: Path
    no_push: bool
    kicad_cli: Path | None  # None → use common.kicad_install.find_kicad_cli() discovery

def load_config(overrides: ConfigOverrides) -> KprojConfig:
    # Precedence (highest first):
    #   1. ConfigOverrides field (set by a CLI flag)
    #   2. Environment variable (KPROJ_SITE_REPO, KPROJ_NO_PUSH, KPROJ_KICAD_CLI)
    #   3. ~/.kproj.yaml key (site_repo, no_push, kicad_cli)
    #   4. Hardcoded fallback (~/Dropbox/eagle/SPCoast.github.io, false, None)
    ...
```

`~/.kproj.yaml` schema (all keys optional):

```yaml path=null start=null
site_repo: /Users/jplocher/Dropbox/eagle/SPCoast.github.io
no_push: false
kicad_cli: /Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli   # optional override; locator probes default if absent
```

Missing file is fine; defaults apply.

## Project resolution

`KicadProjectReader.resolve(path: str | Path) -> ResolvedProject` wraps `jbom.application.pcb_project_loader.resolve_pcb_input()`. jBOM's resolver returns a `jbom.common.types.ResolvedPcbProject` dataclass with `pcb_path` + `project_context` + diagnostics; kproj wraps that in a kproj-owned `ResolvedProject` so downstream services accept a stable kproj shape and never see jBOM's internal types directly:

```python path=null start=null
@dataclass(frozen=True)
class ResolvedProject:
    """kproj-owned wrapper around jBOM's ResolvedPcbProject.
    All downstream services accept this shape, never bare Path."""
    project_file: Path                        # canonical .kicad_pro
    project_dir: Path                         # parent dir of project_file
    pcb_file: Path                            # .kicad_pcb
    root_schematic: Path                      # root .kicad_sch
    hierarchical_schematics: tuple[Path, ...] # all .kicad_sch files referenced by the root
    jbom_resolved: ResolvedPcbProject         # underlying jBOM artifact (for advanced needs)
    diagnostics: tuple[Finding, ...]          # resolution-time findings
```

Resolution behavior per jBOM ADR 0011:

- `kproj` (CWD as positional) → `resolve_pcb_input(".")`
- `kproj <dir>/` → `resolve_pcb_input(<dir>)`
- `kproj <basename>` → `resolve_pcb_input(<basename>)` (jBOM walks common locations)
- `kproj <path>/<file>.kicad_{pro,sch,pcb}` → `resolve_pcb_input(<file-path>)`

If resolution fails (zero or multiple candidates), jBOM raises; kproj catches, formats, exits with code 2. On success, downstream services (`KicadProjectReader.read`, `MetadataAnalyzer.analyze`, `DesignAnalyzer.analyze`, `PcbExporter`, `SchematicExporter`, `IbomGenerator`, `FabPackager`, `SourcePackager`) accept the `ResolvedProject` rather than a generic `Path`.

## Pipeline orchestration sequence

`PublishWorkflow.run(PublishRequest) -> PublishResult`:

```text path=null start=null
1. Minimal pre-flight (only what's needed to read metadata)
   - Resolve project: KicadProjectReader.resolve(request.project_arg) → ResolvedProject
   - Discover kicad-cli: kicad_cli = config.kicad_cli or common.kicad_install.find_kicad_cli()
     - Verify with kicad_version(kicad_cli); enforce major version 9.x for v1
     - Report binary path + version to stderr at default verbosity (one line)
   - Any failure → PublishResult(outcome="failed", exit_code=2). No journal opened.
2. Read project metadata
   - KicadProjectReader.read(resolved) → ProjectInfo + metadata findings
3. Analyze (uses kicad_cli for DRC/ERC)
   - MetadataAnalyzer.analyze(project_info, resolved) → metadata findings
   - DesignAnalyzer.analyze(resolved, kicad_cli) → DRC + ERC findings
   - Merge into AnalysisInfo
4. Status detection (early — BEFORE iBOM / site preflight)
   - project_info.status == "private" → outcome="private-skip", return without remaining pre-flight, without journal open, without site writes
   - This ordering is mandatory: a private project must not fail on "iBOM plugin missing" or "site repo dirty", since it neither invokes iBOM nor writes to the site
5. Remaining pre-flight (non-private only)
   - ibom_script = common.kicad_install.find_ibom_script()       # ADR 0008; missing → exit 2
   - If not dry_run: check site_repo cleanliness (git -C <site_repo> status --porcelain); dirty → exit 2
   - Any failure → PublishResult(outcome="failed", exit_code=2). No journal opened.
6. New-release detection (consults site_repo)
   - Compute target path: <site_repo>/_versions/<P>/<board_rev>.md
   - Compare full rendered publication to on-disk state (see § New-release detection below)
   - All match → outcome="noop", return early
   - Front-matter or body differs, assets unchanged → outcome="refresh"
   - Absent, or any asset missing/stale, or body changed alongside assets → outcome="publish"
7. Open ChangeJournal scoped to the site_repo
   - Journal lives across steps 8–10. Any unhandled exception triggers full rollback (ADR 0005).
   - On dry_run, the journal is opened in dry-run mode: registers intent only, never writes.
8. Generate artifacts (only on outcome=="publish"; skipped on outcome=="refresh"/"noop")
   - Every artifact-producing service receives the open journal + kicad_cli + (for IbomGenerator) ibom_script.
   - Each service writes to <site_repo>/versions/<P>/<R>/<file> via journaled tempfile + os.replace, OR writes to a journal-managed staging dir for move-into-place at step 10.
   - PcbExporter.export_render(side=top|bottom)        # see ExportResult below
   - PcbExporter.export_step()
   - SchematicExporter.export_svg(root_only=True)      # see SchematicExporter directory-output mechanics
   - SchematicExporter.export_pdf(all_sheets=True)
   - IbomGenerator.generate()                          # ADR 0008: direct script invocation via ibom_script
   - FabPackager.package(resolved.project_dir / "production")
   - SourcePackager.package(resolved.project_dir)      # writes source.zip (project artifacts only)
   - Thumbnail recipe (Phase 6 deepening)
9. Build Publication (compose ProjectInfo + AnalysisInfo + asset_refs + body_md)
10. SitePublisher.publish(publication, journal, site_repo, no_push, dry_run)
    - On outcome ∈ {"publish", "refresh"}: journal-write _versions/<P>/<R>.md + pages/<P>.md (atomic via tempfile + os.replace)
    - If not dry_run: git -C <site_repo> add <touched> ; git commit ; journal.mark_committed() ; (unless no_push) git push ; journal.mark_pushed()
11. Close ChangeJournal cleanly. Return PublishResult.

ADR 0005 rollback scope covers EVERY file produced under journal scope — artifact files written in step 8 are journaled the same as markdown files written in step 10. A mid-step exception during step 8 (e.g. iBOM subprocess returns non-zero, or SchematicExporter's discovered output is missing) leaves the site repo in the same state as before kproj ran.
```

## New-release detection

No-op vs refresh vs publish is decided by comparing the **full rendered publication** to the on-disk site state, not just the front-matter. The reviewer's Phase 4 finding M4 caught the original front-matter-only comparison as too narrow.

The comparison inputs:

1. **Front-matter** of `<site_repo>/_versions/<P>/<R>.md` vs the front-matter kproj would emit (computed from the current `Publication`). Compared after normalizing whitespace and YAML field order; ignores volatile keys.
2. **Body markdown** of the same file vs the body kproj would emit (the audit/DRC/ERC tables).
3. **Project page body** of `<site_repo>/pages/<P>.md` vs the project's current `README.md` content (per ADR 0002, the project page body is always rewritten from README.md).
4. **Asset manifest** for `<site_repo>/versions/<P>/<R>/`:
   - Every artifact listed in the front-matter `artifacts[]` and `images[]` must exist on disk.
   - Each artifact's mtime is compared against the corresponding source mtime (e.g. `<P>-<R>.top.png` vs `<pcb>.kicad_pcb`; `<P>-<R>.ibom.html` vs `<pcb>.kicad_pcb`; `<P>-<R>.source.zip` vs the latest mtime in the project's source-include set; `<P>-<R>.fab.zip` vs the latest mtime in `<project_dir>/production/`).
   - Any asset older than its source is treated as stale and forces `outcome="publish"`.

Outcome decision:

- All four inputs match → `outcome="noop"`. Return early. Exit 0 (or 1 if audit/DRC/ERC findings exist).
- Front-matter or body differs, ALL assets exist and are fresh → `outcome="refresh"`. Rewrite `_versions/<P>/<R>.md` + `pages/<P>.md`. Skip asset regeneration.
- The target file is absent, OR any asset is missing, OR any asset is stale → `outcome="publish"`. Run the full artifact pipeline.

The status transition (e.g. `experimental` → `active`) is the canonical metadata-refresh case. README edits that don't touch any artifact's source files are also refresh-only. Anything that touches a `.kicad_pcb`, `.kicad_sch`, or `production/` files forces a publish.

## Release asset set — filenames and subprocess commands

Files emitted into `<site_repo>/versions/<Project>/<board_rev>/`. Filename token `<P>-<R>` = `<project-basename>-<board_rev>` (e.g. `cpNode-Xiao-68x90-1.0B`).

| Asset | Producer | Subprocess command (or library call) |
|---|---|---|
| `<P>-<R>.top.png` | `PcbExporter.export_render(side=top)` | `kicad-cli pcb render --side top --output <P>-<R>.top.png <pcb>` |
| `<P>-<R>.bottom.png` | `PcbExporter.export_render(side=bottom)` | `kicad-cli pcb render --side bottom --output <P>-<R>.bottom.png <pcb>` |
| `<P>-<R>.step` | `PcbExporter.export_step()` | `kicad-cli pcb export step --output <P>-<R>.step <pcb>` |
| `<P>-<R>.sch.svg` | `SchematicExporter.export_svg(root_only=True)` | `kicad-cli sch export svg --output <P>-<R>.sch.svg <root.kicad_sch>` |
| `<P>-<R>.sch.pdf` | `SchematicExporter.export_pdf(all_sheets=True)` | `kicad-cli sch export pdf --output <P>-<R>.sch.pdf <root.kicad_sch>` |
| `<P>-<R>.ibom.html` | `IbomGenerator.generate()` | direct invocation per ADR 0008: `<python> <ibom_script> --no-browser --no-compression --dest-dir <out> --name-format "<P>-<R>.ibom" --extra-data-file <pcb> --dnp-field kicad_dnp --extra-fields MPN,Manufacturer --include-tracks <pcb>`. `<python>` = `sys.executable`; `<ibom_script>` = `common.kicad_install.find_ibom_script()`. |
| `<P>-<R>.fab.zip` | `FabPackager.package()` | reads jBOM-produced gerber pack from `<project_dir>/production/<title>_<rev>.zip` plus `bom.csv` + `pos.csv` → normalizes filenames inside the zip and assembles via `ZipArchiver` |
| `<P>-<R>.source.zip` | `SourcePackager.package()` | walks `<project_dir>` per include/exclude rules → assembles via `ZipArchiver` |
| `<P>-<R>.thumbnail.{png,svg}` | TBD Phase 6 | open: PIL crop of `top.png`, or PCB SVG outline |

iBOM script discovery is delegated to `common.kicad_install.find_ibom_script()` (ADR 0009). Pre-flight calls this once and injects the resolved path into `IbomGenerator`. Missing iBOM plugin → exit 2 with message: `kproj: iBOM plugin not installed at <probed-path>. Install via KiCad's Plugin and Content Manager: org_openscopeproject_InteractiveHtmlBom.`

Why direct invocation rather than `kicad-cli jobset run`: see ADR 0008. The plan's Phase 1 closeout was based on the assumption that `kicad-cli jobset run` could run headless; in practice it requires a live KiCad instance, which contradicts ADR 0007's locked non-interactive Makefile/CI use case.

## Per-service contracts

Each service follows the **Producer Pattern** (per GLOSSARY): constructor takes config; single primary method returns typed result with `diagnostics: tuple[Finding, ...]`. Side-effect services (anything that writes to disk or invokes a subprocess) return an `ExportResult` so callers receive the produced artifact path + diagnostics + command + timing + skipped flag uniformly. Pure-analysis services (`KicadProjectReader.read`, `MetadataAnalyzer.analyze`, `DesignAnalyzer.analyze`) return their domain result + diagnostics.

### `ExportResult` (common return type for side-effect services)

```python path=null start=null
@dataclass(frozen=True)
class ExportResult:
    """Uniform return type for any service that writes a file via subprocess or zip."""
    path: Path | None                  # the produced artifact; None when skipped
    diagnostics: tuple[Finding, ...]   # findings emitted during production
    command: tuple[str, ...] | None    # invoked argv (subprocess services); None for pure-Python services
    elapsed_seconds: float             # wall-clock time spent in the primary method
    skipped: bool = False              # True when service intentionally produced no output (e.g. fab.zip omitted because production/ missing)
```

Fields:
- `path` is `None` only when `skipped=True`. Successful producers always set `path` to the journaled artifact location.
- `diagnostics` carries warnings/info Findings (errors are raised, not returned, per ADR 0004's audit-vs-mechanical-error split).
- `command` is the argv given to the subprocess runner; useful for verbose-mode logging + contract-test assertions. `None` for services that don't invoke a subprocess (e.g. `ZipArchiver`).
- `elapsed_seconds` supports the dry-run timing summary + the optional structured-status mode (Phase 6+ deepening).
- `skipped=True` is for FabPackager when `production/` is empty, SourcePackager (never skips in v1 — it always emits source.zip), and any future opt-in artifact.

### `KicadProjectReader`

```python path=null start=null
class KicadProjectReader:
    def __init__(self) -> None: ...
    def resolve(self, path_or_basename: str | Path) -> ResolvedProject:
        """Wrap jbom.application.pcb_project_loader.resolve_pcb_input().
        Returns the kproj-owned ResolvedProject wrapper; raises on resolution failure."""
    def read(self, resolved: ResolvedProject) -> tuple[ProjectInfo, tuple[Finding, ...]]:
        """Read title-block + ${COMMENT9} from resolved.root_schematic + resolved.pcb_file.
        Apply per-field metadata precedence (see Metadata precedence section below).
        Walks (comment N "...") via jbom.common.sexp_parser until the
        jBOM upstream PR lands; then thin-wraps jbom.services.pcb_reader."""
```

#### Metadata precedence (per-field)

The generic "PCB-precedence rule" from the original DESIGN draft was too coarse: PCB title-blocks routinely omit `comment2`/`comment3`/`comment9` even on fabricated boards, so a blanket PCB-wins rule would lose the SPCoast-convention status field. The Phase 4 reviewer (MAJOR M1) flagged this; the locked plan already specifies per-field rules. kproj implements those rules:

| Field | Canonical source | Fallback | Notes |
|---|---|---|---|
| `title`    | PCB title-block | SCH title-block | Layout-complete projects may have empty PCB title; use SCH if blank. |
| `company`  | PCB title-block | SCH title-block | Same fallback semantics. |
| `rev`      | PCB title-block | SCH title-block | Where they differ legitimately (`pcb_rev` extends `sch_rev`), both are kept: PCB becomes `board_rev`, SCH becomes `design_rev`. |
| `date`     | PCB title-block | SCH title-block | Where they differ legitimately (PCB date follows SCH date within 90 days), the PCB date is used in `date`/`fab_date` and the SCH date is audit-only. |
| `comment1` (designer) | either side, must match | n/a | Audit warning if they disagree on a non-empty value; either non-empty value wins. |
| `comment2` (tagline) | SCH title-block | PCB title-block | PCB rarely sets comment fields. |
| `comment3` (overview continuation) | SCH title-block | PCB title-block | Same. |
| `comment9` (status) | SCH title-block | PCB title-block | Same. SPCoast convention. |
| `comment4..8` | unused | n/a | Reserved per locked SPCoast convention; ignored by kproj. |

All raw SCH and PCB values are retained inside `ProjectInfo` for the audit layer (so `sch_pcb_disagree` findings can carry both sides in their `value` field). The canonical/fallback choice only determines what kproj emits into the Jekyll front-matter.

### `MetadataAnalyzer`

```python path=null start=null
class MetadataAnalyzer:
    def __init__(self) -> None: ...
    def analyze(self, project_info: ProjectInfo, project_path: Path) -> AnalysisInfo:
        """Apply the audit heuristic list (below) to project_info + adjacent files.
        Returns AnalysisInfo with metadata Findings."""
```

### `DesignAnalyzer`

```python path=null start=null
class DesignAnalyzer:
    def __init__(self, kicad_cli: Path) -> None:
        """kicad_cli is the discovered executable path from common.kicad_install.find_kicad_cli()."""
    def analyze(self, resolved: ResolvedProject) -> AnalysisInfo:
        """Invoke `<kicad_cli> pcb drc` and `<kicad_cli> sch erc`, parse JSON outputs into Findings.
        Preserves KiCad's exclusion severity via Severity.exclusion."""
```

DRC subprocess: `<kicad_cli> pcb drc --format json --severity-all --output <tempfile> <resolved.pcb_file>`.
ERC subprocess: `<kicad_cli> sch erc --format json --severity-all --output <tempfile> <resolved.root_schematic>`.

JSON written to tempfile, read into memory, tempfile deleted. JSON parsed into `Finding` objects with `severity`, `field` (= violation type), `value` (= location string), `reason` (= violation message). No JSON files persist after the call.

### `PcbExporter`

```python path=null start=null
class PcbExporter:
    def __init__(self, kicad_cli: Path) -> None: ...
    def export_render(self, pcb_path: Path, side: Literal["top", "bottom"], output: Path) -> ExportResult: ...
    def export_step(self, pcb_path: Path, output: Path) -> ExportResult: ...
    # Future targets: export_svg, export_glb
```

Each method invokes `<kicad_cli> pcb` with the appropriate subcommand via the shared subprocess runner (see Subprocess runner section). Default ray-tracing for renders; default settings everywhere (no per-project tuning in v1).

### `SchematicExporter`

`kicad-cli sch export svg`'s `--output` argument is an OUTPUT_DIR, not a single file path. KiCad writes one SVG per sheet into the directory, named from the sheet hierarchy. `kicad-cli sch export pdf` may differ (TBD verify in Phase 6 against the kicad-cli 9.x build the user has installed). Both methods therefore work in a temp output directory + post-process discover-and-move pattern:

```python path=null start=null
class SchematicExporter:
    def __init__(self, kicad_cli: Path) -> None: ...
    def export_svg(self, sch_path: Path, output_file: Path, root_only: bool = True) -> ExportResult:
        """Run `<kicad_cli> sch export svg --output <tempdir> --pages 1 <sch_path>` (or omit
        --pages and discover the root-sheet file when root_only=True).
        Move the discovered root-sheet SVG from <tempdir> to output_file via the open
        ChangeJournal. Returns ExportResult(path=output_file, command=<argv>, diagnostics=...)."""
    def export_pdf(self, sch_path: Path, output_file: Path, all_sheets: bool = True) -> ExportResult:
        """Run `<kicad_cli> sch export pdf --output <tempdir-or-file> <sch_path>`. KiCad's
        pdf exporter may produce a single multi-sheet PDF directly to --output, or a directory
        with one PDF per sheet; the implementation discovers and moves into place accordingly.
        Returns ExportResult."""
```

Key mechanics:

1. Both methods create a private temp output directory under the ChangeJournal's staging area (so the temp files are journal-rollback-clean).
2. Both methods invoke kicad-cli with `--output <tempdir>` and pass `--pages <root-sheet-selector>` for SVG when `root_only=True`. The exact root-sheet selector is verified against the local kicad-cli help in Phase 6's contract tests (see Testing strategy).
3. After kicad-cli completes, the method discovers the produced file(s) (`*.svg` or `*.pdf` in the tempdir), validates exactly one matches the expected root sheet, and journal-moves it to `output_file`.
4. If kicad-cli produces zero files or more than one when only one was expected, the method raises a `SchematicExportError`, which the workflow catches and converts into a `Finding(severity=error, ...)` + triggers ChangeJournal rollback.

v1 emits only the root sheet as SVG (single file inline on version page) and the full multi-sheet PDF as a download. Per-sheet SVGs + hierarchical navigation are Phase 6+ deepening.

### `IbomGenerator`

```python path=null start=null
class IbomGenerator:
    def __init__(self, ibom_script: Path) -> None:
        """ibom_script is the discovered generate_interactive_bom.py path
        (from common.kicad_install.find_ibom_script(), run once in pre-flight)."""
    def generate(self, pcb_path: Path, output_dir: Path, name_format: str) -> ExportResult:
        """Invoke iBOM directly per ADR 0008:
          common.subprocess_runner.run([sys.executable, str(self.ibom_script), ...args..., str(pcb_path)])
        Pre-flight already verified the script exists; this method assumes it does.
        Returns ExportResult with path = produced HTML file."""
```

### `FabPackager`

```python path=null start=null
class FabPackager:
    def __init__(self, zip_archiver: ZipArchiver) -> None: ...
    def package(self, production_dir: Path, output: Path) -> ExportResult:
        """Discover jBOM's gerber pack and assemble <P>-<R>.fab.zip.

        Gerber-zip discovery (per ADR 0003 / jBOM convention):
          1. <production_dir>/<title>_<rev>.zip when title + rev are known.
          2. Otherwise: the single *.zip in production_dir (warn if zero or >1).
        The discovered zip is added to <P>-<R>.fab.zip under the normalized
        entry name `gerbers.zip` regardless of its source filename.

        Also reads bom.csv + pos.csv from production_dir and adds them under
        their canonical entry names.

        Findings:
          - warn if production_dir missing or empty (fab.zip omitted from output)
          - warn if production_dir outputs older than <pcb>.kicad_pcb mtime (stale)
          - warn if gerber-pack discovery is ambiguous (multiple *.zip candidates)

        Returns ExportResult with skipped=True (and diagnostics) when production_dir is missing/empty."""
```

### `SourcePackager`

The v1 source archive captures the **project artifacts** — the non-derived KiCad files for the project itself. It does NOT vendor external libraries (the SPCoast shared library, KiCad's bundled standard libraries, vendor-specific symbol/footprint sets); those are KiCad-install context, not project context.

This is sufficient for opening + editing the project: KiCad 6.0+ embeds all schematic symbols and PCB footprints used in the design directly inside the `.kicad_sch` and `.kicad_pcb` files, so a consumer who unzips the archive and opens `<Project>.kicad_pro` will see the schematic and the board render correctly without needing to install any external libraries. When a referenced library is genuinely missing on the consumer's machine KiCad's own UI surfaces the gap on open; v1 does not vendor a manifest file describing it.

```python path=null start=null
class SourcePackager:
    def __init__(self, zip_archiver: ZipArchiver) -> None: ...
    def package(self, project_dir: Path, output: Path) -> ExportResult:
        """Walk project_dir per include/exclude rules and assemble project
        files into output via ZipArchiver.
        Returns ExportResult with path=output and command=None."""
```

**Include**: `*.kicad_pro`, `*.kicad_sch`, `*.kicad_pcb`, `*.kicad_sym`, `*.pretty/**/*.kicad_mod`, `*.kicad_dru`, `*.kicad_wks`, `fp-lib-table`, `sym-lib-table`, `README.md`, `LICENSE` (any extension), `CHANGELOG.md`.

**Exclude**: `*.kicad_prl`, `*-bak`, `*~`, `_autosave-*.kicad_*`, `*.kicad_lock`, `production/`, `gerbers/`, `bom/`, `*.ibom.html`, `*.step`, `*.svg`, `thumbnail.png`, render PNGs, `.git/`, `.github/`, `.vscode/`, `.idea/`, `.DS_Store`, `dist/`, `build/`, `node_modules/`, `venv/`, `__pycache__/`, `*.pyc`, `release.yaml`.

### `ZipArchiver`

```python path=null start=null
class ZipArchiver:
    def archive(self, source_paths: list[Path], output: Path) -> ExportResult:
        """Create a zip at output containing source_paths.
        Domain-agnostic. Used by FabPackager and SourcePackager.
        Returns ExportResult with path=output, command=None (no subprocess)."""
```

### `SitePublisher`

```python path=null start=null
class SitePublisher:
    def __init__(self, change_journal: ChangeJournal) -> None: ...
    def publish(self, publication: Publication, site_repo: Path, no_push: bool, dry_run: bool) -> PublishResult:
        """Compute new-release detection.
        Write _versions/<P>/<R>.md (atomic).
        Write pages/<P>.md (atomic; always rewritten from Publication's body_md).
        For new releases: assets are already in place (PcbExporter et al wrote directly).
        git add + git commit + (unless no_push) git push.
        All writes journaled for rollback."""
```

Front-matter rendering happens inside SitePublisher (Jekyll-specific YAML shape — see below). Body markdown comes from `Publication.body_md` (already rendered upstream with the audit/DRC tables).

Commit message format:
- New release: `publish: <Project>-<board_rev>`
- Metadata refresh: `refresh: <Project>-<board_rev> (<reason>)`
- First release for a new project: `add: <Project> <board_rev>`

### `ChangeJournal`

```python path=null start=null
class ChangeJournal:
    def __init__(self, site_repo: Path) -> None: ...
    def __enter__(self) -> "ChangeJournal": ...
    def __exit__(self, exc_type, exc, tb) -> bool:
        """If exc_type is not None, rollback."""
    def will_create(self, path: Path) -> None: ...
    def will_modify(self, path: Path) -> None: ...
    def mark_committed(self) -> None: ...
    def mark_pushed(self) -> None: ...
    def rollback(self) -> None: ...  # ADR 0005 semantics
```

## Audit heuristic list

Implemented by `MetadataAnalyzer`. Each heuristic produces a `Finding(severity, field, value, reason)`:

| Severity | Heuristic | Trigger |
|---|---|---|
| error | `kicad_sch_missing` | adjacent `.kicad_sch` doesn't exist |
| error | `kicad_pcb_missing` | adjacent `.kicad_pcb` doesn't exist |
| error | `placeholder_value` | field value is `${...}` literal, `DATE`, `Fab Date`, `Designer Name`, `Sheet Title Line N`, locale-default date |
| warning | `comment9_missing` | `${COMMENT9}` is empty or absent. v1 emits `status: active` as the default in this case (per locked Phase 1 closeout) and surfaces the warning so the user can populate the field. Promotion to `error` is deferred until after corpus bulk-populate (future ADR). |
| error | `comment9_taxonomy` | `${COMMENT9}` value not in `{experimental, active, retired, broken, replaced-by:<X>, private}` |
| warning | `sch_titleblock_empty` | `.kicad_sch` has empty/missing `(title_block ...)` stanza |
| warning | `pcb_titleblock_empty` | `.kicad_pcb` has empty/missing `(title_block ...)` stanza |
| warning | `sch_pcb_disagree` | non-legitimate string mismatch on a title-block field between SCH and PCB (excluding the legitimate `rev` and `date` patterns documented in CONTEXT history) |
| warning | `date_format` | populated date doesn't match `^\d{4}\.\d{2}$` |
| warning | `designer_format` | populated `comment1` doesn't match `^[A-Z][\w'-]+(\s+[A-Z][\w'-]+)+$` |
| warning | `rev_relation` | `pcb_rev` does not match `^<escaped sch_rev>[A-Z]+$` (board_rev must be design_rev + one or more uppercase-letter suffix). E.g. SCH `3.0` / PCB `3.0B` is OK; SCH `3.0` / PCB `3.0.1` or `3.0-beta` or `3.1` is a finding. |
| warning | `replaced_by_target_missing` | `replaced-by:<X>` references nonexistent project under `~/Dropbox/KiCad/projects/` |
| warning | `production_missing` | `<project_dir>/production/` missing or empty when fab artifacts expected |
| warning | `production_stale` | `production/<gerber>.zip` mtime older than `<pcb>.kicad_pcb` mtime |

## Front-matter shape

What `SitePublisher` writes into `_versions/<Project>/<board_rev>.md` (YAML front-matter, then body). **This shape is the authoritative kproj contract.** The site (`/Users/jplocher/Dropbox/eagle/SPCoast.github.io`) evolves via the locked site-setup PR (Phase 1 closeout) to consume it. Reuse of `layout: eagle` and `publish: true` is a pragmatic v1 minimization that keeps the site-setup PR small — it is NOT a constraint that retrofits kproj to the EAGLE-era shape. KiCad has different capabilities and limits than EAGLE; the site is expected to grow new keys, new conditional branches, and (eventually) a dedicated `kicad.html` layout to match.

```yaml path=null start=null
iskicad: true                      # Phase 1 closeout discriminator: true | 'obsolete'
layout: eagle                      # reuse existing layout (ADR 0002 / Phase 1 closeout)
sidebar: spcoast_sidebar
project: <project-basename>        # consumed by eagle.html's site.versions | where: "project", page.project
title: <board_rev>                 # e.g. 1.0B — per-version key; consumed by version tabs
date: <YYYY.MM>                    # PCB title-block date
design_rev: <sch_rev>              # kproj convention; not consumed by eagle.html
board_rev: <board_rev>             # same as title; convenience for grep/audit
designer: <comment1>               # consumed (informational)
fabricated: <YYYY-MM>              # truthy date string when PCB has been fabbed; gates eagle.html's "First built" line
fab_date: <YYYY-MM>                # optional explicit fab date (defaults to title-block date)
tagline: <comment2>                # consumed (one-line description)
overview: <comment2 + comment3>    # consumed via markdownify
company: <company>                 # used to derive tags
tags: [<company>, kicad]           # kproj-authoritative tag set. If company contains "/", split. The site-setup PR extends _data/tags.yml allowed-tags to include "kicad" and any company values kproj emits; this is part of the locked site-setup PR scope, not an open question. Until that PR lands, non-allowlisted tags emit to front-matter but don't render as buttons — still searchable in the front-matter source.
status: <comment9>                 # emitted verbatim per locked taxonomy: experimental/active/retired/broken/replaced-by:<X>
publish: true                      # REQUIRED gate — eagle.html only renders artifacts/version body inside {% if version.publish == true %}
image_path: /versions/<P>/<R>/<P>-<R>.thumbnail.png   # ABSOLUTE site path (live site convention)
images:
  - {image_path: /versions/<P>/<R>/<P>-<R>.top.png,    title: Top}
  - {image_path: /versions/<P>/<R>/<P>-<R>.bottom.png, title: Bottom}
  - {image_path: /versions/<P>/<R>/<P>-<R>.sch.svg,    title: Schematic}
artifacts:
  - {path: /versions/<P>/<R>/<P>-<R>.sch.pdf,    tag: schematic-pdf,   type: download, post: Full schematic (all sheets)}
  - {path: /versions/<P>/<R>/<P>-<R>.ibom.html,  tag: interactive-bom, type: download, post: Interactive HTML BOM}
  - {path: /versions/<P>/<R>/<P>-<R>.step,       tag: step-model,      type: download, post: 3D STEP model}
  - {path: /versions/<P>/<R>/<P>-<R>.fab.zip,    tag: fab-pack,        type: download, post: Fab-house bundle (BOM + POS + gerbers)}
  - {path: /versions/<P>/<R>/<P>-<R>.source.zip, tag: source-archive,  type: download, post: KiCad source archive}
# kproj-emitted, not yet consumed by eagle.html (reserved for site-setup-PR layout enhancement):
audit: {errors: N, warnings: M}
drc:   {errors: N, warnings: M, exclusions: K}
erc:   {errors: N, warnings: M, exclusions: K}
```

For `status == "private"`: no file is written (private-skip outcome). For `status ∈ {"retired", "replaced-by:<X>"}`: `iskicad: 'obsolete'` instead of `true`.

**Site-setup PR scope** (locked in Phase 1 closeout; mandatory Phase 5/6 prerequisite; NOT in kproj itself):

kproj is the driver of the site's evolution from EAGLE-era to KiCad-aware. The site-setup PR brings the live SPCoast site up to consume kproj's authoritative emission contract. None of these are open design questions — they're follow-through work on a decision already taken.

1. Repurpose `electronics.html` (filter on `iskicad`), add `eagle-archive.html` (filter on `iseagle`), update the sidebar TOC to split into "KiCad Projects" + "Eagle Projects" — the migration-framed shape from the Phase 1 closeout.
2. Extend `_data/tags.yml` `allowed-tags` to include `kicad` and any new company names emitted by kproj. Without this, kproj-emitted tags are present in front-matter but don't render as buttons.
3. Extend `_layouts/eagle.html`'s status-conditional block to recognize the v1 taxonomy values (`active`, `retired`, `replaced-by:<X>`) that don't currently match its `mature/released/replaced/broken/experimental` branches. v1 emits the locked kproj taxonomy verbatim; the layout PR adds the new branches.
4. Optionally add quality-badge rendering for `audit`/`drc`/`erc` front-matter (deferred deepening; not v1-blocking). KiCad has DRC/ERC concepts EAGLE did not; surfacing the counts is a KiCad-specific UI evolution.
5. Future: a dedicated `kicad.html` layout when KiCad-specific UI elements (inline iBOM viewer, inline STEP preview, hierarchical schematic navigation) outgrow `eagle.html`. Out of v1 site-setup-PR scope; tracked as a Phase 6+ deepening candidate.

Body content (below the `---` front-matter terminator): the audit + DRC/ERC findings rendered as two adjacent Markdown tables via `MarkdownTableFormatter`. Optionally followed by README.md content if the user wants verbose project documentation in the version body (Phase 6 decision; for v1, body is just the tables).

`pages/<Project>.md` is similar but covers project-level metadata; body content is the project's README.md content (always rewritten).

## Site-repo git workflow

Inside `SitePublisher.publish()` (after all writes are staged via `ChangeJournal`):

```bash path=null start=null
git -C <site_repo> add <touched files>
git -C <site_repo> commit -m "<commit-message>"
journal.mark_committed()
git -C <site_repo> push    # skipped if no_push
journal.mark_pushed()
```

Commit messages per pattern in *Per-service contracts › SitePublisher*. Push target is whatever branch is checked out (user keeps the site repo on the deployment branch; kproj does not `git checkout`).

## Exit code mapping

`cli.py` maps `PublishResult` to process exit codes:

| Code | When |
|---|---|
| 0 | `outcome` in `{published, refreshed, noop, private-skip}` AND no findings of any severity |
| 1 | `outcome` in `{published, refreshed, noop, private-skip}` AND audit/DRC/ERC findings exist |
| 2 | `outcome == failed` (pre-flight failure, mid-pipeline exception, rollback triggered) |

## Dry-run semantics

`PublishRequest.dry_run = True` short-circuits all side effects:

- Skip pre-flight site-repo cleanliness check (no writes will happen anyway).
- Run `KicadProjectReader.read` (read-only).
- Run `MetadataAnalyzer.analyze` (read-only).
- Run `DesignAnalyzer.analyze` (read-only; JSON in-memory only, no JSON files written to disk).
- **Skip** `PcbExporter`, `SchematicExporter`, `IbomGenerator`, `FabPackager`, `SourcePackager` invocations.
- **Skip** all writes to the site repo.
- **Skip** all git operations on the site repo.
- Log to stderr: pre-flight pass/fail, findings, would-be file paths, would-be commit message, would-be push target.

`--dry-run` is read-only and idempotent. Wall-clock time is dominated by the DRC/ERC subprocess invocations (typically seconds per project, longer for boards with many violations).

## Verbosity

`cli.py` configures Python `logging`:

- Default — only findings (audit + DRC/ERC + mechanical errors) to stderr.
- `-v` / `--verbose` — adds subprocess command lines + their stderr/stdout + git command lines.
- `-d` / `--debug` — implementation-private diagnostics (dataclass state transitions, finding-rule evaluation traces, ChangeJournal state). **Not a committed interface**; output content changes freely per developer needs.

Combined `-v -d` is permitted; gives both.

## Testing strategy

Per the user's hygiene rule ("Use Test Driven Development for all functionality"), Phase 6 implements tests first, then code (red-green-refactor via `tdd` skill).

### Layer principles

The three test layers each have a different evolution cadence and a different reason to exist; tests at one layer never duplicate the responsibilities of another. (Distinction inherited from jBOM's hard-learned lesson.)

- **Behave Gherkin features (`tests/features/`)** — functional feature testing. The acceptance gate for user-expectation correctness and regression prevention. Each scenario maps directly to a PRD user story; scenarios are written in the *user's vocabulary*, not the implementation's. **Additive only.** Once a scenario is correct, it never changes unless the user-facing behavior it documents changes. New stories add new scenarios; existing scenarios never get rewritten to track internal refactors. These tests never replicate implementation details.
- **Unit tests (`tests/unit/`)** — implementation + internal design testing. Tests the kproj code surface that the Behave scenarios exercise indirectly. **Evolves with the implementation.** When a service's internal contract changes, the unit tests change with it. Unit tests never replicate functional details that belong in Behave scenarios; they exercise types, dataclass shapes, mocked subprocess invocations, and edge cases at the API level. Coverage target is per-service, per-method.
- **Contract tests (`tests/contract/`)** — external-tool surface testing. Validates that kproj's assumptions about kicad-cli + iBOM (output shapes, file layouts, JSON schemas, exit codes) actually hold against the locally-installed binary. **Evolves with the external tool.** When a KiCad version changes the JSON shape of `pcb drc`, the contract test catches it; unit tests with mocked subprocess do not. Contract tests are `@pytest.mark.skipif`-gated on `common.kicad_install.find_kicad_cli()` succeeding so CI without KiCad skips the layer rather than failing it.

**Summary of distinct duties:**

- Behave: "does this user story still hold?" (additive, user-vocabulary)
- Unit: "does this code still do what the design says?" (evolves with code, implementation-vocabulary)
- Contract: "does the external tool still produce what we assume?" (evolves with the external tool)

### Unit tests — `tests/unit/`, pytest

Per service + per model module. Each unit test:
- Constructs a service with controlled config.
- Calls the service's primary method with controlled input (mocked file paths via `tmp_path` fixture; mocked subprocess calls via `monkeypatch` or `subprocess.run` stubs).
- Asserts on the typed return + diagnostics.

Test files:
- `tests/unit/model/test_project_info.py`
- `tests/unit/model/test_finding.py`
- ... (one per model module)
- `tests/unit/services/test_kicad_project_reader.py`
- `tests/unit/services/test_metadata_analyzer.py`
- ... (one per service module)
- `tests/unit/formatters/test_stderr_formatter.py`
- ... (one per formatter)
- `tests/unit/test_config.py`
- `tests/unit/test_cli.py` (argparse plumbing + exit-code mapping)

### Contract tests — `tests/contract/`, pytest

Contract tests validate the *external surface* of every tool kproj invokes. They run real `kicad-cli` against tiny fixture projects and assert on the produced output shape — file names, directory layout, JSON schema, exit codes — not the file *contents*. The goal is to catch a kicad-cli version-skew that would otherwise only surface as a Phase 7 integration failure.

Each contract test is `@pytest.mark.skipif` gated on `common.kicad_install.find_kicad_cli()` succeeding; CI environments without KiCad installed skip the layer rather than fail it. Local developer machines (and the Phase 7 validation host) always run them.

Test files:
- `tests/contract/test_kicad_cli_drc.py` — `kicad-cli pcb drc --format json` produces the expected top-level JSON keys (`source`, `coordinate_units`, `violations`); each violation has `severity`/`type`/`description`/`items[]`.
- `tests/contract/test_kicad_cli_erc.py` — same shape for `kicad-cli sch erc --format json`.
- `tests/contract/test_kicad_cli_sch_export_svg.py` — `--output <tempdir>` is OUTPUT_DIR; produces `*.svg` per sheet; `--pages` selector exists and selects single sheet.
- `tests/contract/test_kicad_cli_sch_export_pdf.py` — verifies whether `--output` is a file or directory for the local kicad-cli build; locks the SchematicExporter implementation choice.
- `tests/contract/test_kicad_cli_pcb_render.py` — `--side top|bottom --output <file>.png` produces a PNG.
- `tests/contract/test_kicad_cli_pcb_step.py` — `pcb export step --output <file>.step` produces a STEP file.
- `tests/contract/test_ibom.py` — the discovered `generate_interactive_bom.py` accepts `--no-browser --no-compression --dest-dir --name-format --extra-data-file --dnp-field --extra-fields --include-tracks` and produces a single HTML file named per `--name-format`.
- `tests/contract/test_kicad_install_locator.py` — `common.kicad_install.{find_kicad_cli, find_ibom_script, find_plugins_dir, kicad_version}` return paths that exist and a sane version tuple.

Fixtures for contract tests are minimal (a 1-component PCB with a 1-sheet schematic) so the layer is fast; the goal is shape validation, not project coverage.

### Behave Gherkin features — `tests/features/`

The Gherkin scenarios from PRD.md user stories become Behave features. Each feature exercises `PublishWorkflow.run()` against a fixture project + a fixture site repo (`tmp_path` based).

Feature files:
- `publish.feature` — Stories 1, 13 (publish + no-op).
- `dry_run.feature` — Story 2.
- `project_resolution.feature` — Story 3.
- `findings_surfaced.feature` — Stories 4, 5.
- `metadata_refresh.feature` — Story 6.
- `private_status.feature` — Story 7.
- `batch_safety.feature` — Stories 8, 9 (no-push + mid-pipeline failure rollback).
- `site_repo_cleanliness.feature` — Story 10.
- `verbose.feature` — Story 12.

Stories 14–18 (visitor / consumer-facing) are Phase 7 manual validation against the live site, not Behave scenarios (they cross the Jekyll build).

### Fixtures — `tests/fixtures/`

- `cpNode-Xiao-68x90/` — a minimal fixture project mirroring the Phase 7 target's structure (PCB + SCH + populated title-block). Used by happy-path tests.
- `private-project/` — fixture with `${COMMENT9} = private`.
- `audit-warning-project/` — fixture with audit warnings (e.g. designer not in FirstName LastName form).
- `placeholder-project/` — fixture with `${PROJECTNAME}` literal in title.
- `ibom-missing/` — a fixture used to test pre-flight failure when the iBOM plugin path is patched away.

### Coverage expectations

Per the hygiene rule, all unit + functional tests pass before any commit. Coverage target: 100% of public service methods + Workflow paths. Implementation modules whose only side effect is subprocess invocation (PcbExporter, SchematicExporter, IbomGenerator, DesignAnalyzer) have their subprocess calls mocked in unit tests; their integration with real `kicad-cli` is validated in the contract test layer; full end-to-end use is validated in Behave scenarios against real fixture projects. The three layers together cover the failure modes the Phase 4 reviewer flagged.

## Cross-cutting concerns

### Logging

`logging.getLogger("kproj")` root. Handlers configured in `cli.py` based on verbose/debug flags. Format: `<level> [<step>] <message>` (no timestamp — CI logs add their own).

### Secrets

None. kproj v1 does not call the GitHub API. The site-repo `git push` uses the user's locally-configured git credentials (SSH key or credential helper). No `KPROJ_TOKEN` or similar in v1.

### Error handling

- `KicadProjectReader.resolve` failures (zero / multiple `.kicad_pro` candidates) → exit 2 with jBOM's diagnostic.
- Subprocess failures (non-zero exit from kicad-cli / iBOM / git) → captured, surfaced on stderr, trigger ChangeJournal rollback if mid-publish, exit 2.
- File-system errors (permission, disk full) → trigger rollback, exit 2.
- `git push` rejection → `git reset --hard HEAD^` to undo the local commit, exit 2.
- Subprocess timeout (`subprocess.TimeoutExpired`) → captured by the shared subprocess runner (see Subprocess runner section below), surfaced on stderr, rollback, exit 2.
- Signal interruption (`KeyboardInterrupt`, `SIGTERM` handler) → the open ChangeJournal's `__exit__` catches the `BaseException`, performs rollback, re-raises so the process exits with the standard signal-handling exit code.

All exceptions bubble up to `cli.py`'s top-level handler, which formats and exits.

### Subprocess runner

All subprocess invocations (kicad-cli, iBOM script, git) go through a shared `common.subprocess_runner` utility that:

- Wraps `subprocess.run` with per-step timeouts (default: 120s for kicad-cli + iBOM, 30s for git operations; both configurable via `~/.kproj.yaml`).
- Captures stdout + stderr into the run's verbose-mode log.
- Translates `subprocess.TimeoutExpired` into a kproj-level `SubprocessTimeoutError` carrying the command + elapsed time.
- Translates non-zero return into a `SubprocessFailedError` carrying the command + stdout + stderr.
- Re-raises `KeyboardInterrupt` after attempting to terminate the child process cleanly (SIGTERM, 5s grace, then SIGKILL).
- Returns a `SubprocessResult` dataclass (`command`, `returncode`, `stdout`, `stderr`, `elapsed_seconds`) on success.

This utility is the only place in kproj that calls `subprocess.run`; services depend on it via import. Mocking `common.subprocess_runner.run` in unit tests is sufficient to stub all external invocations.

### Python imports

kproj imports from jBOM (library-only, per ADR 0003):
- `jbom.application.pcb_project_loader` (project resolution)
- `jbom.services.pcb_reader`, `jbom.services.schematic_reader` (title-block reading)
- `jbom.common.sexp_parser` (S-expression walking for COMMENT9 until upstream PR)
- `jbom.common.types` (TitleBlockMetadata, Diagnostic — reused as foundation for kproj's Finding)

kproj does NOT import:
- `jbom.application.fabrication_orchestration` (kproj reads `production/`, doesn't invoke jBOM)
- `jbom.cli.*` (CLI surface; not for library use)
- `jbom.plugin.*` (KiCad plugin code; kproj is not a plugin)

### Python packaging

`pyproject.toml` (already in the repo): Python ≥3.11, MIT, hatchling build, `kproj = "kproj.cli:main"` console-script entry point. `uv sync` for dev environment; `uv sync --frozen` in CI (when Phase 6+ CI lands).

### Performance assumption

v1 makes an unbounded assumption that a full `kproj` invocation against a typical SPCoast project is fast enough not to need per-step subsetting (no `--step <name>` flag, no `--only-render` / `--only-ibom` switches). The expected runtime budget is on the order of tens of seconds per project, dominated by kicad-cli's DRC/ERC + iBOM HTML generation + STEP export.

If POC validation or tracer-bullet work proves this assumption wrong — i.e. typical runs are slow enough that quick iteration is painful — BOTH the performance problem AND the debugability/subset problem get re-opened together. The fix could be:

- Adding `--step <name>` for one-shot debugging.
- Parallelizing independent exporters (PCB renders + SVG exports + iBOM are pure functions of the PCB, can run concurrently).
- Adding a cache layer keyed on PCB mtime.

Until empirical evidence justifies it, kproj does not pre-architect for these. The escape hatch is documented in PRD's "Out of Scope" list (`--step` deferred) and ADR 0007 (CLI surface intentionally minimal).
