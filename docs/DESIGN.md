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
kproj [<project-or-dir-or-file>] [--dry-run] [--no-push] [-v|--verbose] [-d|--debug]
```

- **Positional** — optional path; if absent, use CWD. Delegates to `KicadProjectReader.resolve(path or ".")` which wraps `jbom.application.pcb_project_loader.resolve_pcb_input()`.
- **`--dry-run`** — boolean flag. Sets `PublishRequest.dry_run = True`.
- **`--no-push`** — boolean flag. Sets `PublishRequest.no_push = True` (or env `KPROJ_NO_PUSH=1`, or `no_push: true` in `~/.kproj.yaml`).
- **`-v` / `--verbose`** — count flag (`action="count"`). Sets `PublishRequest.verbose_level = 1` when `-v`, 2 when `-v -d` (combined).
- **`-d` / `--debug`** — boolean flag. Implementation-private dev output; not a stable interface.

`cli.py` is the only module that imports `argparse` or calls `sys.exit` (ADR 0006).

## Configuration layer

`src/kproj/config.py`: `KprojConfig` dataclass + `load_config()` function.

```python path=null start=null
@dataclass(frozen=True)
class KprojConfig:
    site_repo: Path
    no_push: bool

def load_config(cli_args: argparse.Namespace) -> KprojConfig:
    # Precedence (highest first):
    #   1. CLI flag value (if argparse saw it)
    #   2. Environment variable (KPROJ_SITE_REPO, KPROJ_NO_PUSH)
    #   3. ~/.kproj.yaml key (site_repo, no_push)
    #   4. Hardcoded fallback (~/Dropbox/eagle/SPCoast.github.io, false)
    ...
```

`~/.kproj.yaml` schema:

```yaml path=null start=null
site_repo: /Users/jplocher/Dropbox/eagle/SPCoast.github.io
no_push: false
```

Missing file is fine; defaults apply.

## Project resolution

`KicadProjectReader.resolve(path: str | Path) -> Path` delegates to `jbom.application.pcb_project_loader.resolve_pcb_input()`. Behavior per jBOM ADR 0011:

- `kproj` (CWD as positional) → `resolve_pcb_input(".")`
- `kproj <dir>/` → `resolve_pcb_input(<dir>)`
- `kproj <basename>` → `resolve_pcb_input(<basename>)` (jBOM walks common locations)
- `kproj <path>/<file>.kicad_{pro,sch,pcb}` → `resolve_pcb_input(<file-path>)`

Returns the canonical `.kicad_pro` path. If resolution fails (zero or multiple candidates), jBOM raises; kproj catches, formats, exits with code 2.

## Pipeline orchestration sequence

`PublishWorkflow.run(PublishRequest) -> PublishResult`:

```text path=null start=null
1. Pre-flight checks
   - Resolve project (KicadProjectReader.resolve)
   - If not dry_run: check site_repo cleanliness (git status --porcelain)
   - Check iBOM plugin path (KICAD9_3RD_PARTY / .../generate_interactive_bom.py)
   - Failure of any pre-flight → return PublishResult(outcome="failed", exit_code=2)
2. Read project metadata
   - KicadProjectReader.read(project_path) → ProjectInfo
3. Analyze
   - MetadataAnalyzer.analyze(project_info, project_path) → metadata_findings
   - DesignAnalyzer.analyze(project_path) → drc_erc_findings
   - Merge into AnalysisInfo
4. New-release detection (consults site_repo)
   - Compute target path: <site_repo>/_versions/<P>/<board_rev>.md
   - If exists and front-matter matches → outcome="noop", return early (exit 0 or 1 based on findings)
   - If exists and front-matter would differ → outcome="refresh", continue to step 6 only
   - If absent → outcome="publish", continue to step 5
5. Status: private → outcome="private-skip", return without site writes
6. Generate artifacts (only on outcome="publish"; skipped on "refresh"/"noop"/"private-skip")
   - PcbExporter.export_render(side=top) → <site_repo>/versions/<P>/<R>/<P>-<R>.top.png
   - PcbExporter.export_render(side=bottom) → ...bottom.png
   - PcbExporter.export_step() → ...step
   - SchematicExporter.export_svg(root_only=True) → ...sch.svg
   - SchematicExporter.export_pdf(all_sheets=True) → ...sch.pdf
   - IbomGenerator.generate() → ...ibom.html
   - FabPackager.package(production_dir) → ...fab.zip
   - SourcePackager.package(project_dir) → ...source.zip
   - Compute thumbnail (Phase 6 recipe TBD)
7. Build Publication (compose ProjectInfo + AnalysisInfo + asset_refs + body_md)
8. SitePublisher.publish(publication, site_repo, no_push, dry_run)
   - Atomic per-file writes via tempfile + os.replace under ChangeJournal supervision
   - Writes _versions/<P>/<R>.md, pages/<P>.md, asset files
   - If not dry_run: git add + git commit + (unless no_push) git push
9. Return PublishResult with outcome, exit_code, diagnostics

Mid-step exceptions trigger ChangeJournal rollback (per ADR 0005).
```

## New-release detection

`SitePublisher` reads `<site_repo>/_versions/<Project>/<board_rev>.md` if it exists, parses the front-matter, and compares to the front-matter kproj would emit (computed from the current `Publication`):

- File missing → new release. Full pipeline runs.
- File present, parsed front-matter == new front-matter → no-op. Return without writes.
- File present, parsed front-matter ≠ new front-matter → metadata refresh. Rewrite `_versions/<P>/<R>.md` only. Skip asset generation (renders, iBOM, fab.zip, source.zip).

The status transition (e.g. `experimental` → `active`) is the canonical metadata-refresh case.

## Release asset set — filenames and subprocess commands

Files emitted into `<site_repo>/versions/<Project>/<board_rev>/`. Filename token `<P>-<R>` = `<project-basename>-<board_rev>` (e.g. `cpNode-Xiao-68x90-1.0B`).

| Asset | Producer | Subprocess command (or library call) |
|---|---|---|
| `<P>-<R>.top.png` | `PcbExporter.export_render(side=top)` | `kicad-cli pcb render --side top --output <P>-<R>.top.png <pcb>` |
| `<P>-<R>.bottom.png` | `PcbExporter.export_render(side=bottom)` | `kicad-cli pcb render --side bottom --output <P>-<R>.bottom.png <pcb>` |
| `<P>-<R>.step` | `PcbExporter.export_step()` | `kicad-cli pcb export step --output <P>-<R>.step <pcb>` |
| `<P>-<R>.sch.svg` | `SchematicExporter.export_svg(root_only=True)` | `kicad-cli sch export svg --output <P>-<R>.sch.svg <root.kicad_sch>` |
| `<P>-<R>.sch.pdf` | `SchematicExporter.export_pdf(all_sheets=True)` | `kicad-cli sch export pdf --output <P>-<R>.sch.pdf <root.kicad_sch>` |
| `<P>-<R>.ibom.html` | `IbomGenerator.generate()` | `python <ibom-script> --no-browser --no-compression --dest-dir <out> --name-format "<P>-<R>.ibom" --extra-data-file <pcb> --dnp-field kicad_dnp --extra-fields MPN,Manufacturer --include-tracks <pcb>` |
| `<P>-<R>.fab.zip` | `FabPackager.package()` | reads `<project_dir>/production/{bom.csv, pos.csv, gerbers.zip}` → assembles via `ZipArchiver` |
| `<P>-<R>.source.zip` | `SourcePackager.package()` | walks `<project_dir>` per include/exclude rules → assembles via `ZipArchiver` |
| `<P>-<R>.thumbnail.{png,svg}` | TBD Phase 6 | open: PIL crop of `top.png`, or PCB SVG outline |

iBOM script path: `${KICAD9_3RD_PARTY}/plugins/org_openscopeproject_InteractiveHtmlBom/generate_interactive_bom.py`. Pre-flight checks the path exists; missing → exit 2 with message: `kproj: iBOM plugin not installed at <expected-path>. Install via KiCad's Plugin and Content Manager: org_openscopeproject_InteractiveHtmlBom.`

## Per-service contracts

Each service follows the **Producer Pattern** (per GLOSSARY): constructor takes config; single primary method returns typed result with `diagnostics: tuple[Finding, ...]`.

### `KicadProjectReader`

```python path=null start=null
class KicadProjectReader:
    def __init__(self) -> None: ...
    def resolve(self, path_or_basename: str | Path) -> Path:
        """Wrap jbom.application.pcb_project_loader.resolve_pcb_input.
        Returns the canonical .kicad_pro path; raises on resolution failure."""
    def read(self, project_path: Path) -> tuple[ProjectInfo, tuple[Finding, ...]]:
        """Read title-block + ${COMMENT9} from .kicad_sch + .kicad_pcb.
        Apply PCB-precedence rule for fields that differ between sides.
        Walks (comment N "...") via jbom.common.sexp_parser until the
        jBOM upstream PR lands; then thin-wraps jbom.services.pcb_reader."""
```

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
    def __init__(self) -> None: ...
    def analyze(self, project_path: Path) -> AnalysisInfo:
        """Invoke kicad-cli pcb drc and sch erc, parse JSON outputs into Findings.
        Preserves KiCad's exclusion severity via Severity.exclusion."""
```

DRC subprocess: `kicad-cli pcb drc --format json --severity-all --output <tempfile> <pcb>`.
ERC subprocess: `kicad-cli sch erc --format json --severity-all --output <tempfile> <sch>`.

JSON written to tempfile, read into memory, tempfile deleted. JSON parsed into `Finding` objects with `severity`, `field` (= violation type), `value` (= location string), `reason` (= violation message). No JSON files persist after the call.

### `PcbExporter`

```python path=null start=null
class PcbExporter:
    def __init__(self) -> None: ...
    def export_render(self, pcb_path: Path, side: Literal["top", "bottom"], output: Path) -> Path: ...
    def export_step(self, pcb_path: Path, output: Path) -> Path: ...
    # Future targets: export_svg, export_glb
```

Each method invokes `kicad-cli pcb` with the appropriate subcommand. Default ray-tracing for renders; default settings everywhere (no per-project tuning in v1).

### `SchematicExporter`

```python path=null start=null
class SchematicExporter:
    def __init__(self) -> None: ...
    def export_svg(self, sch_path: Path, output: Path, root_only: bool = True) -> Path: ...
    def export_pdf(self, sch_path: Path, output: Path, all_sheets: bool = True) -> Path: ...
```

v1 emits only the root sheet as SVG (single file inline on version page) and the full multi-sheet PDF as a download. Per-sheet SVGs + hierarchical navigation are Phase 6+ deepening.

### `IbomGenerator`

```python path=null start=null
class IbomGenerator:
    def __init__(self) -> None: ...
    def generate(self, pcb_path: Path, output_dir: Path, name_format: str) -> Path:
        """Pre-flight: check ${KICAD9_3RD_PARTY}/.../generate_interactive_bom.py exists.
        Invoke iBOM via subprocess.run. Return path to the produced HTML."""
```

### `FabPackager`

```python path=null start=null
class FabPackager:
    def __init__(self, zip_archiver: ZipArchiver) -> None: ...
    def package(self, production_dir: Path, output: Path) -> tuple[Path, tuple[Finding, ...]]:
        """Read bom.csv, pos.csv, gerbers.zip from production_dir.
        Assemble into output (the <P>-<R>.fab.zip) via ZipArchiver.
        Findings: warn if production_dir missing or empty,
                  warn if production_dir outputs older than *.kicad_pcb mtime."""
```

### `SourcePackager`

```python path=null start=null
class SourcePackager:
    def __init__(self, zip_archiver: ZipArchiver) -> None: ...
    def package(self, project_dir: Path, output: Path) -> Path:
        """Walk project_dir, collect non-derived KiCad files per the include/exclude rules.
        Assemble via ZipArchiver."""
```

**Include**: `*.kicad_pro`, `*.kicad_sch`, `*.kicad_pcb`, `*.kicad_sym`, `*.pretty/**/*.kicad_mod`, `*.kicad_dru`, `*.kicad_wks`, `fp-lib-table`, `sym-lib-table`, `README.md`, `LICENSE` (any extension), `CHANGELOG.md`.

**Exclude**: `*.kicad_prl`, `*-bak`, `*~`, `_autosave-*.kicad_*`, `*.kicad_lock`, `production/`, `gerbers/`, `bom/`, `*.ibom.html`, `*.step`, `*.svg`, `thumbnail.png`, render PNGs, `.git/`, `.github/`, `.vscode/`, `.idea/`, `.DS_Store`, `dist/`, `build/`, `node_modules/`, `venv/`, `__pycache__/`, `*.pyc`, `release.yaml`.

### `ZipArchiver`

```python path=null start=null
class ZipArchiver:
    def archive(self, source_paths: list[Path], output: Path) -> Path:
        """Create a zip at output containing source_paths.
        Domain-agnostic. Used by FabPackager and SourcePackager."""
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
| error | `comment9_missing` | `${COMMENT9}` is empty or absent (after corpus bulk-populate; treat as warning during transition) |
| error | `comment9_taxonomy` | `${COMMENT9}` value not in `{experimental, active, retired, broken, replaced-by:<X>, private}` |
| warning | `sch_titleblock_empty` | `.kicad_sch` has empty/missing `(title_block ...)` stanza |
| warning | `pcb_titleblock_empty` | `.kicad_pcb` has empty/missing `(title_block ...)` stanza |
| warning | `sch_pcb_disagree` | non-legitimate string mismatch on a title-block field between SCH and PCB (excluding the legitimate `rev` and `date` patterns documented in CONTEXT history) |
| warning | `date_format` | populated date doesn't match `^\d{4}\.\d{2}$` |
| warning | `designer_format` | populated `comment1` doesn't match `^[A-Z][\w'-]+(\s+[A-Z][\w'-]+)+$` |
| warning | `rev_relation` | `pcb_rev` doesn't start with `sch_rev` (board_rev not extending design_rev) |
| warning | `replaced_by_target_missing` | `replaced-by:<X>` references nonexistent project under `~/Dropbox/KiCad/projects/` |
| warning | `production_missing` | `<project_dir>/production/` missing or empty when fab artifacts expected |
| warning | `production_stale` | `production/<gerber>.zip` mtime older than `<pcb>.kicad_pcb` mtime |

## Front-matter shape

What `SitePublisher` writes into `_versions/<Project>/<board_rev>.md` (YAML front-matter, then body):

```yaml path=null start=null
iskicad: true                      # or 'obsolete' for retired/replaced-by
layout: kicad                      # thin wrapper around eagle.html in v1
sidebar: spcoast_sidebar
project: <project-basename>
title: <board_rev>                 # e.g. 1.0B — the per-version key
date: <YYYY.MM>                    # from PCB title-block date
design_rev: <sch_rev>              # e.g. 3.0
board_rev: <board_rev>             # same as title; explicit for layout convenience
designer: <comment1>
tagline: <comment2>
overview: <comment2 + comment3 joined>
company: <company>
tags: [<company>, kicad]           # if company contains "/", split into multiple tags
status: <comment9>                 # one of the closed taxonomy values
image_path: <P>-<R>.thumbnail.png
images:
  - {image_path: <P>-<R>.top.png, title: Top}
  - {image_path: <P>-<R>.bottom.png, title: Bottom}
  - {image_path: <P>-<R>.sch.svg, title: Schematic}
artifacts:
  - {path: <P>-<R>.sch.pdf, tag: schematic-pdf, type: download, post: Full schematic (all sheets)}
  - {path: <P>-<R>.ibom.html, tag: interactive-bom, type: download, post: Interactive HTML BOM}
  - {path: <P>-<R>.step, tag: step-model, type: download, post: 3D STEP model}
  - {path: <P>-<R>.fab.zip, tag: fab-pack, type: download, post: Fab-house bundle (BOM + POS + gerbers)}
  - {path: <P>-<R>.source.zip, tag: source-archive, type: download, post: KiCad source archive}
audit: {errors: N, warnings: M}
drc: {errors: N, warnings: M, exclusions: K}
erc: {errors: N, warnings: M, exclusions: K}
```

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

`--dry-run` is read-only, idempotent, fast (milliseconds).

## Verbosity

`cli.py` configures Python `logging`:

- Default — only findings (audit + DRC/ERC + mechanical errors) to stderr.
- `-v` / `--verbose` — adds subprocess command lines + their stderr/stdout + git command lines.
- `-d` / `--debug` — implementation-private diagnostics (dataclass state transitions, finding-rule evaluation traces, ChangeJournal state). **Not a committed interface**; output content changes freely per developer needs.

Combined `-v -d` is permitted; gives both.

## Testing strategy

Per the user's hygiene rule ("Use Test Driven Development for all functionality"), Phase 6 implements tests first, then code (red-green-refactor via `tdd` skill).

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

Per the hygiene rule, all unit + functional tests pass before any commit. Coverage target: 100% of public service methods + Workflow paths. Implementation modules whose only side effect is subprocess invocation (PcbExporter, SchematicExporter, IbomGenerator, DesignAnalyzer) have their subprocess calls mocked in unit tests; their integration with real `kicad-cli` is validated only in Behave scenarios against real fixture projects.

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

All exceptions bubble up to `cli.py`'s top-level handler, which formats and exits.

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
