# jBOM Reuse Map for `kproj` (Phase 1)

Source surveyed: `/Users/jplocher/Dropbox/KiCad/jBOM` @ commit on disk 2026‑05‑29, `version = "7.2.0"`, AGPL‑3.0‑only, Python ≥3.10, ~24.2k LoC under `src/jbom/`.

## Executive summary

- jBOM is a **library‑quality, adapter‑neutral** Python package on PyPI (`pip install jbom`). The `application/` and `services/` layers are clean to import; only `cli/` and `plugin/` are adapter‑coupled. Default recommendation for kproj: **import‑as‑library**.
- The "find the right KiCad project" logic and the "extract title‑block metadata" logic are **already factored cleanly**: `jbom.application.pcb_project_loader.resolve_pcb_input` + `jbom.services.project_file_resolver.ProjectFileResolver` + `jbom.services.pcb_reader.DefaultKiCadReaderService.read_metadata()` + `jbom.services.schematic_reader.SchematicReader.read_metadata()`. No SWIG / no `pcbnew` import — pure `sexpdata`.
- `jbom.application.fabrication_orchestration.FabricationWorkflow` is the BOM + POS + Gerber + backup pipeline kproj's internal `fab` module should call. Adapter‑neutral, takes a frozen `FabricationRequest`, returns a frozen `FabricationResult` with all artifacts and diagnostics. Supports `dry_run`.
- **Critical gap**: jBOM's `TitleBlockMetadata` carries **only** `title / revision / date / company`. It does **not** parse `(comment 1..9)` entries in `(title_block ...)`, and it **never reads the `.kicad_pro` JSON's `text_variables` map**. Therefore `${COMMENT1..9}` and `${STATUS}` — central to the kproj→Jekyll contract — are **not currently obtainable from jBOM**. kproj must implement this itself (or extend jBOM via PR; out of scope for Phase 1).
- jBOM has **no render / STEP / 3D model / thumbnail / git / `gh release` / Jekyll** logic. Those modules of kproj are entirely greenfield.
- jBOM's gerber path shells out to `kicad-cli pcb export gerbers|drill|ipc356`. The locator probes PATH and the macOS app bundle. Reusable as a library entry point; kproj can rely on this rather than re‑implementing gerber export.
- AGPL‑3.0 license on jBOM means **vendoring code** into kproj triggers AGPL on kproj. **Importing as a dependency** does not by itself relicense kproj, but a network‑service deployment would. Recommendation: keep all reuse at the import boundary; vendor nothing.
- One open architectural question: jBOM exposes the orchestration via the *concrete* `FabricationWorkflow` class — there is no protocol/abc separating contract from implementation. If kproj wants to mock the boundary for unit tests, it must do so via the frozen `FabricationRequest`/`FabricationResult` dataclasses (which are stable and dependency‑free).

## 1. Repo shape

```
/Users/jplocher/Dropbox/KiCad/jBOM/
├── pyproject.toml              # PEP 621, build via setuptools, name="jbom"
├── setup.py                    # minimal legacy shim (re-exports pyproject)
├── kicad_jbom_plugin.py        # KiCad Eeschema BOM plugin shim (NOT for kproj)
├── src/jbom/
│   ├── __init__.py             # __version__ = "7.2.0"
│   ├── __main__.py             # `python -m jbom` → cli.main:main
│   ├── application/            # adapter-neutral orchestrators
│   ├── cli/                    # argparse handlers (jbom CLI)
│   ├── common/                 # shared types, sexp parser, kicad_runtime
│   ├── config/                 # fabricator + supplier YAML profiles, pydantic
│   ├── plugin/                 # wx-based KiCad ActionPlugin (irrelevant)
│   ├── services/               # ~40 stateful service classes
│   ├── suppliers/              # supplier search adapters (mouser/lcsc/null)
│   └── workflows/              # empty (legacy, ignore)
├── features/                   # behave/Gherkin BDD suite
├── tests/                      # pytest unit + integration
├── docs/, examples/, scripts/, legacy/, poc/, ...
```

- **Packaging**: `setuptools>=61` with `pyproject.toml`. Build backend `setuptools.build_meta`. **Not** `uv`; kproj uses `uv` but the two compose — `uv` consumes a wheel/sdist transparently.
- **Python**: declared `requires-python = ">=3.10"` (compatible with kproj's 3.11+).
- **Runtime dependencies (mandatory)**: `sexpdata>=0.0.3`, `PyYAML>=5.4.0`, `pydantic>=2.0`.
- **Optional dependency groups**: `excel` (openpyxl), `numbers` (numbers‑parser), `search` (requests), `all` rolls them up.
- **Console scripts** (`[project.scripts]`):
  - `jbom = jbom.cli.main:main` — single entry point. Subcommands: `audit`, `annotate`, `bom`, `config`, `fab`, `gerbers`, `inventory`, `pos`, `parts`, `promote`, `search`. All routed via direct `register_command(subparsers)` calls in `src/jbom/cli/main.py`.
- **Module entry**: `python -m jbom` works (`src/jbom/__main__.py` → `jbom.cli.main:main`).
- **License**: AGPL‑3.0‑only. **Read AGPL implications carefully before vendoring.**
- **Version policy**: Semantic‑release driven by Angular‑style commits. Plugin `kicad_jbom_plugin.py` at repo root is a KiCad BOM‑plugin shim only (not relevant to kproj).

## 2. Per‑module inventory

Each section: module path → purpose, public API surface (with import paths a kproj caller would write), external dependencies, coupling notes, and the per‑module recommendation.

### 2.1 `jbom.application.pcb_project_loader`
Path: `src/jbom/application/pcb_project_loader.py`

- **Purpose**: Centralised "resolve user input → PCB project" + canonical schematic enumeration; consumed by both BOM and POS workflows.
- **Public API**:
  - `from jbom.application.pcb_project_loader import resolve_pcb_input` — `(input_path: str, *, artifact_name: str = "BOM", options: GeneratorOptions | None = None) -> ResolvedPcbProject`. Accepts a directory, base name, `.kicad_pcb`, `.kicad_sch`, or `.kicad_pro`. Returns the resolved PCB path, `ProjectContext`, and informational diagnostics.
  - `from jbom.application.pcb_project_loader import ResolvedPcbProject` — frozen dataclass with `resolved_input`, `pcb_path`, `project_context`, `diagnostics`.
  - `from jbom.application.pcb_project_loader import load_board` — `(pcb_path: Path) -> BoardModel`. Reads the PCB via `DefaultKiCadReaderService`.
  - `from jbom.application.pcb_project_loader import list_hierarchical_schematic_files` — `(project_context: ProjectContext) -> list[Path]`. Existing `.kicad_sch` files in hierarchy.
  - `from jbom.application.pcb_project_loader import load_schematic_components` — `(schematic_files, *, options=None, verbose=False) -> tuple[list[Component], tuple[Diagnostic, ...]]`.
  - `from jbom.application.pcb_project_loader import collect_project_graph` — helper that wraps `ProjectComponentCollector` (probably not needed by kproj).
- **External deps**: `jbom.services.*` only. No `kicad‑cli`, no `pcbnew`. Pure Python (`sexpdata`).
- **Coupling**: Zero CLI coupling. Pure adapter‑neutral. Designed exactly for what kproj needs.
- **Recommendation**: `import-as-library`.

### 2.2 `jbom.application.fabrication_orchestration`
Path: `src/jbom/application/fabrication_orchestration.py`

- **Purpose**: Sequence BOM → POS → Gerbers → optional designators → backup, each independently skippable, with diagnostics aggregated.
- **Public API**:
  - `from jbom.application.fabrication_orchestration import FabricationWorkflow` — class with `.run(request: FabricationRequest, *, step_callback: Callable[[str, str], None] | None = None) -> FabricationResult`.
  - `from jbom.application.fabrication_orchestration import FabricationRequest` — frozen dataclass; key fields: `input_path` (str), `fabricator` (str, default `"generic"`), `production_root` (str, where `production/` is created), `inventory_files` (tuple[str, ...]), `skip_bom / skip_pos / skip_gerbers / skip_backup / generate_designators / dry_run / debug / verbose` (bool), `smd_only` (bool), `pos_layer` ("TOP"/"BOTTOM"/""), `pos_origin` ("board"/"aux"), `archive_stem` (pre‑expanded archive name), `archive_template` (template like `"${TITLE}_${REVISION}"`), `apply_corrections` (bool, rotation/offset CSV corrections).
  - `from jbom.application.fabrication_orchestration import FabricationResult` — frozen dataclass; fields: `artifacts: tuple[FabricationArtifact, ...]`, `diagnostics: tuple[Diagnostic, ...]`, `bom_result`, `pos_result`, `gerber_result`, `production_dir`, `backup_archive`.
  - `from jbom.application.fabrication_orchestration import FabricationArtifact` — `(artifact_type: str, path: Path | None, media_type: str)`. `artifact_type ∈ {"bom","pos","gerber","designators","backup"}`.
- **External deps**: `kicad-cli` subprocess at fabrication time (via `GerberExporter`); `BOMWriter` writes `production/jbom.csv`; `POSWriter` writes `production/cpl.csv`; `BackupService` writes `production/backups/<stem>_<date>.zip`.
- **Coupling**: Adapter‑neutral (no argparse, stdout, exit codes inside). CLI integration done by `jbom.cli.fabrication.handle_fab`. `step_callback` is a naked `Callable` — no wx/asyncio dependency.
- **Recommendation**: `import-as-library`. This is the backbone of kproj's internal `fab` module. Note: there is no protocol/abstract base — kproj couples to the concrete class. The frozen request/result dataclasses are the stable contract.

### 2.3 `jbom.application.bom_workflow`
Path: `src/jbom/application/bom_workflow.py`

- **Purpose**: BOM‑specific orchestration — PCB is the canonical row set; schematic + inventory enrich; fabricator presets select fields.
- **Public API**:
  - `from jbom.application.bom_workflow import BOMWorkflow` → `.run(BOMRequest) -> BOMResult`.
  - `from jbom.application.bom_workflow import BOMRequest` → `input_path, fabricator, fields_argument, inventory_files, filter_config, verbose, list_fields`.
  - `from jbom.application.bom_workflow import BOMResult, BOMMode, BOMGenerationPayload, BOMFieldListingPayload`.
- **External deps**: `jbom.services.bom_*`, `jbom.config.fabricators`, `jbom.services.inventory_overlay_service`, `jbom.services.fabricator_projection_service`.
- **Coupling**: Adapter‑neutral. Used by `FabricationWorkflow._run_bom` internally — kproj should call `FabricationWorkflow` and not this directly unless it wants BOM without POS/Gerbers.
- **Recommendation**: `import-as-library` (indirectly via `FabricationWorkflow`).

### 2.4 `jbom.application.pos_workflow`
Path: `src/jbom/application/pos_workflow.py`

- **Purpose**: Component placement (CPL) orchestration.
- **Public API**:
  - `from jbom.application.pos_workflow import POSWorkflow, POSRequest, POSResult, POSMode, POSGenerationPayload, POSFieldListingPayload`.
- **External deps**: `jbom.services.pos_*`, `jbom.services.rotation_correction_service`, `jbom.config.fabricators`.
- **Coupling**: Adapter‑neutral.
- **Recommendation**: `import-as-library` (indirectly via `FabricationWorkflow`).

### 2.5 `jbom.services.project_file_resolver`, `jbom.services.project_context`, `jbom.services.project_discovery`
Paths: `src/jbom/services/project_{file_resolver,context,discovery}.py`

- **Purpose**: Layered "find the right KiCad project" stack.
  - `ProjectDiscovery` enforces "exactly one `*.kicad_pro` per directory" and matches `.kicad_sch` / `.kicad_pcb` by directory name with autosave fallback.
  - `ProjectContext` wraps a discovered project and adds hierarchical schematic enumeration via regex on `(property "Sheetfile" ...)`, lock‑file detection (`*.lck`), expected‑path queries, and `get_project_metadata()` returning a dict snapshot.
  - `ProjectFileResolver` resolves a user input string (relative path, absolute path, base name, explicit file) into a `ResolvedInput`. Handles target‑type cross‑resolution (give me a PCB even if you gave me a schematic).
- **Public API**:
  - `from jbom.services.project_file_resolver import ProjectFileResolver, ResolvedInput`
    - `ProjectFileResolver(prefer_pcb=True, target_file_type="pcb").resolve_input(user_input) -> ResolvedInput`
    - `ResolvedInput.resolved_path / .is_pcb / .is_schematic / .project_context / .get_hierarchical_files() / .get_matching_pcb() / .get_matching_schematic()`
  - `from jbom.services.project_context import ProjectContext`
    - `ProjectContext(project_directory).project_file / .schematic_file / .pcb_file / .project_base_name / .get_hierarchical_schematic_files() / .lock_file / .is_locked`
  - `from jbom.services.project_discovery import ProjectDiscovery, ProjectFiles`
    - `ProjectDiscovery().find_project_file(dir) / find_schematic_file(dir) / find_pcb_file(dir) / discover_project_files(dir)`
- **External deps**: stdlib only. `sexpdata` not needed for these (regex parses hierarchy).
- **Coupling**: Stateful services with light constructor config (`GeneratorOptions` for verbose). Some `print(...)` to `sys.stderr` for UX messages ("found project X", "WARNING: autosave...") — kproj will inherit these unless it redirects stderr. **Minor surprise**: `ProjectFileResolver._resolve_directory` writes "found project / found schematic / found pcb" to stderr unconditionally.
- **Recommendation**: `import-as-library`. The stderr noise is acceptable for kproj since the parent CLI is also a developer tool; if it becomes objectionable, wrap with `contextlib.redirect_stderr`.

### 2.6 `jbom.services.project_metadata`
Path: `src/jbom/services/project_metadata.py`

- **Purpose**: Wrap PCB + schematic title‑block reads into a single `ProjectMetadata` snapshot plus helpers for archive naming and template expansion.
- **Public API**:
  - `from jbom.services.project_metadata import ProjectMetadata` — frozen `(project_name, pcb_metadata, schematic_metadata, release_timestamp)`.
  - `from jbom.services.project_metadata import create_metadata` — `(project_file: Path, pcb_file=None, schematic_file=None) -> ProjectMetadata`.
  - `from jbom.services.project_metadata import expand_archive_template` — `(template: str, pcb_file: Optional[Path]) -> str`. Resolves `${TITLE}/${REVISION}/${DATE}/${ISSUE_DATE}/${CURRENT_DATE}/${COMPANY}` against the PCB title block.
  - `from jbom.services.project_metadata import normalize_archive_stem` — filename‑safe normaliser.
  - `from jbom.services.project_metadata import DEFAULT_ARCHIVE_TEMPLATE` — `"${TITLE}_${REVISION}"`.
- **External deps**: `pcb_reader`, `schematic_reader`, `text_variable_expander`.
- **Coupling**: Pure.
- **Recommendation**: `import-as-library`. **Note the gap**: `ProjectMetadata` carries `pcb_metadata: TitleBlockMetadata` and `schematic_metadata: TitleBlockMetadata`. Both `TitleBlockMetadata` carry only `title / revision / date / company`. **No `comment_*` fields, no `status`**.

### 2.7 `jbom.services.pcb_reader`, `jbom.services.schematic_reader`
Paths: `src/jbom/services/{pcb_reader,schematic_reader}.py`

- **Purpose**: Pure‑Python KiCad file readers using `sexpdata`. Read components and title‑block metadata. **No `pcbnew` SWIG module required.**
- **Public API**:
  - `from jbom.services.pcb_reader import DefaultKiCadReaderService, KiCadReaderService, KiCadParseError`
    - `.read_pcb_file(pcb_path: Path) -> BoardModel` — full footprint list with x/y/rotation/side/attributes.
    - `.read_metadata(pcb_path: Path) -> TitleBlockMetadata` — title / rev / date / company.
    - `.validate_pcb_file(path) -> bool`.
  - `from jbom.services.schematic_reader import SchematicReader`
    - `.load_components(schematic_file: Path) -> list[Component]` (with `value/footprint/uuid/properties/in_bom/exclude_from_sim/dnp`).
    - `.read_metadata(schematic_file: Path) -> TitleBlockMetadata`.
- **External deps**: `sexpdata`.
- **Coupling**: Stateless / minimally configured.
- **Recommendation**: `import-as-library`. These are the right modules for kproj to consume — and the place an upstream PR would add COMMENT1..9 parsing if jBOM ever adopts it. See §4 below for the title‑block S‑expression grammar that kproj must extend over.

### 2.8 `jbom.services.text_variable_expander`
Path: `src/jbom/services/text_variable_expander.py`

- **Purpose**: Expand the standard KiCad title‑block variables in a template string.
- **Public API**:
  - `from jbom.services.text_variable_expander import expand_text_variables`
    - `(template: str, metadata: TitleBlockMetadata) -> str`. Substitutes `${TITLE}`, `${REVISION}`, `${DATE}`, `${ISSUE_DATE}`, `${CURRENT_DATE}`, `${COMPANY}`. **Unknown `${VAR}` tokens are preserved unchanged** (passthrough — kproj can layer COMMENT* support on top by re‑running its own expansion after this).
- **External deps**: stdlib only.
- **Coupling**: Pure function.
- **Recommendation**: `import-as-library`. Compose with a kproj‑side expander for `${COMMENT1..9}` and `${STATUS}`.

### 2.9 `jbom.services.gerber_service`
Path: `src/jbom/services/gerber_service.py`

- **Purpose**: Tiered Gerber/drill/IPC‑D‑356 export. Locates `kicad-cli` on PATH and platform install dirs (`/Applications/KiCad/KiCad.app/Contents/MacOS/`, `C:\Program Files\KiCad\<v>\bin\`, `/usr/bin`, `/usr/local/bin`, `/snap/bin`). Graceful degradation: returns `GerberResult(skipped=True, skip_reason="kicad_cli_not_found")` if not found.
- **Public API**:
  - `from jbom.services.gerber_service import GerberExporter, GerberRequest, GerberResult, gerber_request_from_config`
    - `GerberExporter().generate(GerberRequest(pcb_file, output_directory, fabricator="generic", include_drill=True, include_netlist=False, layers=None, protel_extensions=True, drill_split_plated_holes=False, drill_map_format=None)) -> GerberResult(artifacts, diagnostics, skipped, skip_reason)`.
- **External deps**: `kicad-cli` (subprocess). Inside‑KiCad path is a stub (returns skipped + diagnostic).
- **Coupling**: Adapter‑neutral. `is_running_inside_kicad()` decides between subprocess vs. (currently stub) plugin path.
- **Recommendation**: `import-as-library`. Even though kproj's pipeline routes Gerbers through `FabricationWorkflow`, kproj could call this directly if it ever wants pure‑Gerber export without BOM/POS.

### 2.10 `jbom.services.gerber_packager`, `backup_service`, `zip_archiver`, `designators_writer`
Paths: `src/jbom/services/{gerber_packager,backup_service,zip_archiver,designators_writer}.py`

- **Purpose**: Concrete helpers used by `FabricationWorkflow`.
  - `GerberPackager.package(artifact_paths, archive_path, *, debug=False) -> Path` — zips a gerber set and optionally removes the intermediate `gerbers/` directory.
  - `BackupService.backup(artifact_paths, backup_dir, archive_stem) -> Path` — dated archive in `production/backups/`.
  - `ZipArchiver.archive(paths, archive_path)` — flat zip primitive.
  - `DesignatorsWriter.write(references, path, force=True)` — writes REF:COUNT CSV.
- **External deps**: stdlib only.
- **Recommendation**: `import-as-library` (indirectly via `FabricationWorkflow`; direct import only if kproj needs the primitive outside the workflow).

### 2.11 `jbom.services.bom_writer`, `jbom.services.pos_writer`, `jbom.services.bom_generator`, `jbom.services.pos_generator`
Paths: `src/jbom/services/{bom_writer,pos_writer,bom_generator,pos_generator}.py`

- **Purpose**: Final CSV emit + aggregation logic. Called inside `FabricationWorkflow`. Public, but kproj should not call directly — go through the workflow so column policy stays consistent with the fabricator profile.
- **Recommendation**: `import-as-library` (transitive); direct import only as an emergency hatch.

### 2.12 `jbom.services.{audit_service,annotation_service,inventory_*,sophisticated_inventory_matcher,fabricator_*,...}`
- **Purpose**: jBOM‑specific BOM enrichment, audit, annotation back‑to‑schematic, supplier search. Not relevant to kproj's release pipeline.
- **Recommendation**: skip entirely. If kproj needs inventory‑enhanced BOMs, pass `inventory_files=(...)` to `FabricationRequest` and let jBOM handle it internally.

### 2.13 `jbom.services.search/*`, `jbom.suppliers/*`
- **Purpose**: Mouser / LCSC / JLC supplier APIs and search providers.
- **Recommendation**: skip. kproj is not in the supplier search business.

### 2.14 `jbom.common.types`
Path: `src/jbom/common/types.py`

- **Public API**:
  - `from jbom.common.types import TitleBlockMetadata` — **frozen dataclass; fields = `title, revision, date, company`** (all `str`, default `""`). **No comments, no status.**
  - `from jbom.common.types import Diagnostic` — frozen `(severity ∈ {"info","warning","error"}, message: str)`.
  - `from jbom.common.types import Component` — schematic component dataclass.
  - `from jbom.common.types import InventoryItem`, `DEFAULT_PRIORITY` — inventory‑only.
- **Recommendation**: `import-as-library` for `TitleBlockMetadata` and `Diagnostic`.

### 2.15 `jbom.common.sexp_parser`
Path: `src/jbom/common/sexp_parser.py`

- **Purpose**: Thin shared `sexpdata` wrapper.
- **Public API**:
  - `from jbom.common.sexp_parser import load_kicad_file, walk_nodes, find_child, find_all_children`.
- **Recommendation**: `import-as-library` — kproj will need this to read the additional title‑block `(comment 1..9 "...")` fields jBOM does not currently extract, and to parse `.kicad_pro` JSON's `text_variables` map (note: `.kicad_pro` is JSON, not S‑expr, so `load_kicad_file` is only relevant for `.kicad_sch` / `.kicad_pcb`).

### 2.16 `jbom.common.kicad_runtime`
Path: `src/jbom/common/kicad_runtime.py`

- **Public API**:
  - `from jbom.common.kicad_runtime import is_running_inside_kicad, check_write_permitted`
- **Recommendation**: skip — kproj is a CLI / CI tool that never runs inside KiCad's embedded Python.

### 2.17 `jbom.common.{options,fields,field_parser,field_taxonomy,packages,package_matching,...}`
- **Purpose**: BOM field naming, component classification, package matching heuristics.
- **Recommendation**: skip unless kproj surfaces field‑level BOM customisation, which is not in the current scope.

### 2.18 `jbom.config.*`
Path: `src/jbom/config/`

- **Purpose**: Fabricator and supplier profile YAML loader (built‑in profiles: `generic`, `jlc`, `pcbway`, `seeed`). Heavy `pydantic` schemas.
- **Public API touched by kproj if any**:
  - `from jbom.config.fabricators import get_available_fabricators, get_fabricator_presets, load_fabricator, FabricatorConfig`.
- **Recommendation**: skip direct use. kproj just passes `fabricator="jlc"` (or `"generic"`) in the `FabricationRequest`; the workflow loads the profile internally.

### 2.19 `jbom.cli.*`
Path: `src/jbom/cli/`

- **Purpose**: argparse subcommand handlers. `cli/main.py` registers `audit / annotate / bom / config / fab / gerbers / inventory / pos / parts / promote / search`. Each handler builds a `JobRequest`, wraps the workflow call via `application.jobs.runner.JobRunner`, and prints diagnostics to stderr.
- **Recommendation**: `shell-out` only as a fallback. **Default**: do not call CLI — call the `application/` workflows directly. The `application.jobs.*` job‑runner abstraction is overkill and not needed by kproj. If a future need forces shell‑out, the exact subprocess form would be:
  - `subprocess.run([sys.executable, "-m", "jbom", "fab", project_dir, "--jlc", "--archive-name", "${TITLE}_${REVISION}", "-o", workdir], check=True)`.

### 2.20 `jbom.plugin.*`
Path: `src/jbom/plugin/`

- **Purpose**: KiCad ActionPlugin (wx‑based GUI dialog, gerber generation via `pcbnew`).
- **Recommendation**: skip entirely.

### 2.21 `jbom.application.jobs.*`
Path: `src/jbom/application/jobs/` (referenced from `cli/bom.py`, `cli/fabrication.py`).

- **Purpose**: `JobRunner`, `JobRequest`, `JobContext`, `JobOutcome`, `JobArtifact`, `JobEventStream`. A generic "execute, emit progress events, collect diagnostics" wrapper that the CLI uses to standardise adapter behaviour across subcommands.
- **Coupling**: Adapter‑agnostic, but kproj will already have its own pipeline orchestrator and step abstraction (`render / ibom / fab / tag / publish / site`) — wrapping itself in jBOM's job runner would couple kproj to jBOM's event contract for no clear benefit.
- **Recommendation**: skip. Build kproj's own thin pipeline orchestrator.

## 3. Reuse recommendation per module

| Module | Recommendation | One‑line rationale |
|---|---|---|
| `jbom.application.pcb_project_loader` | import‑as‑library | Adapter‑neutral, exactly the "find KiCad project + load board + enumerate hierarchy" surface kproj needs. |
| `jbom.application.fabrication_orchestration` | import‑as‑library | Single‑call BOM+POS+Gerber+backup pipeline with frozen request/result; supports dry‑run; is the backend of kproj's `fab` step. |
| `jbom.application.bom_workflow` | import‑as‑library (indirect) | Used inside `FabricationWorkflow`; direct call only if kproj ever wants BOM without POS/gerbers. |
| `jbom.application.pos_workflow` | import‑as‑library (indirect) | Same as above for placement. |
| `jbom.services.project_file_resolver` | import‑as‑library | Stable resolver for directory/file/base‑name input forms. |
| `jbom.services.project_context` | import‑as‑library | Hierarchical schematic enumeration + lock‑file awareness. |
| `jbom.services.project_discovery` | import‑as‑library | Low‑level helper used by ProjectContext; direct use rarely needed. |
| `jbom.services.project_metadata` | import‑as‑library | `create_metadata`, `expand_archive_template`, `normalize_archive_stem` — needed for archive naming and Jekyll front‑matter base name. |
| `jbom.services.pcb_reader` | import‑as‑library | Title‑block + footprint reader, pure Python S‑expr, no SWIG. |
| `jbom.services.schematic_reader` | import‑as‑library | Schematic title‑block reader; companion to pcb_reader. |
| `jbom.services.text_variable_expander` | import‑as‑library | Variable expansion with passthrough for unknown vars — kproj layers COMMENT*/STATUS on top. |
| `jbom.services.gerber_service` | import‑as‑library | `kicad-cli` locator + gerber/drill/ipc356 runner; reusable outside the fab workflow if needed. |
| `jbom.services.gerber_packager` / `backup_service` / `zip_archiver` / `designators_writer` | import‑as‑library (indirect) | Used through `FabricationWorkflow`; direct import only as emergency hatch. |
| `jbom.services.bom_*` / `pos_*` / `inventory_*` / `audit_service` / `annotation_service` / `search/*` / `suppliers/*` | skip (transitive) | BOM/inventory/audit/supplier logic kproj doesn't own. Inventory data is forwarded via `FabricationRequest.inventory_files`. |
| `jbom.common.types` | import‑as‑library | `TitleBlockMetadata`, `Diagnostic`. |
| `jbom.common.sexp_parser` | import‑as‑library | Needed because kproj has to parse comment 1..9 itself (see §4). |
| `jbom.common.kicad_runtime` | skip | kproj is never embedded in KiCad. |
| `jbom.common.{options,fields,field_*,packages,package_matching,...}` | skip | BOM field internals. |
| `jbom.config.*` | skip (transitive) | Fabricator profile loaded inside `FabricationWorkflow`. |
| `jbom.cli.*` | shell‑out (fallback only) | Application workflows are the supported library surface; CLI is the supported user surface. |
| `jbom.plugin.*` | skip | wx‑based KiCad ActionPlugin. |
| `jbom.application.jobs.*` | skip | Generic adapter wrapping not needed by kproj. |

Rationales (one paragraph each, the three boundary modules):

- **`jbom.application.fabrication_orchestration` — import‑as‑library.** `FabricationWorkflow.run(FabricationRequest)` is the exact contract kproj's internal `fab` module needs. It is adapter‑neutral (no argparse, no stdout, no exit codes), accepts a frozen request, returns a frozen result with typed artifacts and diagnostics, supports `dry_run`, optional step callbacks (kproj can ignore the callback by passing `None`), and writes all output beneath a `production/` subdirectory it manages. The only downside is that kproj inherits all of jBOM's runtime dependencies (`sexpdata`, `PyYAML`, `pydantic>=2.0`), but those are mainstream and already present in most release‑automation environments. Vendoring would mean replicating ~1.5k lines of cross‑service coupling and is not justified.

- **`jbom.services.pcb_reader` + `jbom.services.schematic_reader` — import‑as‑library.** These are the right level of abstraction for kproj to mine for title‑block reads, and they intentionally do not depend on KiCad's `pcbnew` SWIG bindings, which makes them safe inside a CI environment without a KiCad install (the `kicad-cli` binary is still needed for gerbers, but file reads work standalone). The same readers are used inside `FabricationWorkflow`, so kproj's direct calls do not duplicate parsing — they are cheap.

- **`jbom.cli.*` — shell‑out (fallback only).** Calling `jbom` as a subprocess is an option, but the workflows are already library‑quality and the CLI handlers wrap them with `JobRunner` + diagnostics‑to‑stderr + argparse + the `--fabricator`/`--jlc`/`--pcbway`/`--seeed` selector polymorphism. None of that adds value for kproj. Reserve shell‑out for the case where a future jBOM CLI surface is added that has no library equivalent.

## 4. KiCad‑interaction logic

### 4.1 "Find the right KiCad project"

Primary entry point kproj should use:

```python path=null start=null
from jbom.application.pcb_project_loader import resolve_pcb_input

resolved = resolve_pcb_input(user_input_path, artifact_name="kproj")
# resolved.pcb_path           -> Path to .kicad_pcb
# resolved.project_context    -> ProjectContext
#   .project_file             -> Path to .kicad_pro
#   .schematic_file           -> Path to .kicad_sch (root)
#   .pcb_file                 -> Path to .kicad_pcb
#   .project_base_name        -> stem of .kicad_pro
#   .get_hierarchical_schematic_files() -> list[Path]
#   .is_locked / .lock_file   -> KiCad lock-file awareness
# resolved.diagnostics        -> info diagnostics emitted during resolution
```

Behaviour:
- Accepts directory, base name, `.kicad_pro`, `.kicad_pcb`, `.kicad_sch`.
- Enforces "exactly one `*.kicad_pro` per project directory" — raises `ValueError` if zero or ambiguous; tie‑breaks by directory‑name match, then alphabetical fallback (`services/project_discovery.py:48-62`).
- Crosses file types: pass a `.kicad_sch` and ask for `target_file_type="pcb"`, get the sibling `.kicad_pcb`.
- Warns on autosave‑only files via stderr.

### 4.2 Title‑block parsing (and the COMMENT*/STATUS gap)

**What jBOM does today**:

```python path=null start=null
from jbom.services.pcb_reader import DefaultKiCadReaderService
meta = DefaultKiCadReaderService().read_metadata(pcb_path)
# meta is a frozen jbom.common.types.TitleBlockMetadata:
#   meta.title      <- (title_block (title "..."))
#   meta.revision   <- (title_block (rev "..."))
#   meta.date       <- (title_block (date "..."))
#   meta.company    <- (title_block (company "..."))
```

The schematic reader has the equivalent. See `services/pcb_reader.py:178-215` and `services/schematic_reader.py:172-209` for the extraction loops. Both iterate the `(title_block ...)` stanza but only recognise the four keys above.

**What jBOM does NOT do** (and what kproj needs):

1. **`(comment N "...")`** — KiCad's title‑block stanza supports `(comment 1 "...")` through `(comment 9 "...")`. jBOM's `_extract_title_block_metadata` does not look for the `comment` symbol. These are the on‑PCB / on‑schematic title‑block COMMENT fields and they are written by KiCad when the user fills in "Page Settings → Issue Date / Comment1..Comment9".
2. **`.kicad_pro` `text_variables` map** — the `.kicad_pro` file is JSON (not S‑expression) and carries a `text_variables` object that holds **project‑level** custom text variables. KiCad expands `${COMMENT1..9}` against the **title‑block** stanza, and `${MyCustomVar}` against the **project‑level** `text_variables` map. `${STATUS}` (per the plan's open decision) almost certainly lives in `text_variables` — jBOM has zero code that opens `.kicad_pro` as JSON.

KiCad variable syntax reminder (from the architect handoff): `${COMMENT1}` through `${COMMENT9}` — **one‑indexed, no hyphen**. The hyphenated `${COMMENT-N}` form is incorrect and must not be propagated.

**Recommended kproj implementation**: write a thin `kproj.kicad.metadata` module that:

  1. Calls `jbom.services.pcb_reader.DefaultKiCadReaderService().read_metadata(pcb_path)` to populate the four standard fields.
  2. Reopens the same PCB / schematic file via `jbom.common.sexp_parser.load_kicad_file` and walks the `(title_block ...)` stanza for `(comment N "...")` entries (extending what jBOM does today by one extra symbol match).
  3. Opens `<project>.kicad_pro` as JSON (`json.load`) and reads the `text_variables` mapping for `STATUS` (and any other project‑level variables the SPCoast convention introduces).
  4. Returns an extended dataclass — e.g. `KprojMetadata(title, revision, date, company, comments: dict[int, str], project_text_variables: dict[str, str])`.

This deliberately does not modify jBOM. If the COMMENT extraction proves stable, an upstream PR to jBOM's `TitleBlockMetadata` (adding `comment_1..9` or `comments: tuple[str, ...]`) would be a clean follow‑up. **Cleanest split**: keep that extension in kproj for Phase 1‑6, propose upstream after Phase 7.

### 4.3 BOM / fabrication artifact generation

Single call:

```python path=null start=null
from jbom.application.fabrication_orchestration import (
    FabricationWorkflow, FabricationRequest,
)

result = FabricationWorkflow().run(FabricationRequest(
    input_path=str(project_dir),       # accepts dir, .kicad_pro, .kicad_pcb, .kicad_sch
    fabricator="jlc",                  # or "pcbway", "seeed", "generic"
    production_root=str(work_dir),     # parent of `production/`; defaults to project dir
    inventory_files=(str(inv_csv),),   # optional; empty tuple = no inventory enrichment
    archive_template="${TITLE}_${REVISION}",
    skip_bom=False, skip_pos=False, skip_gerbers=False,
    generate_designators=True,         # writes production/designators.csv
    dry_run=False,
    verbose=False,
))
# result.production_dir       -> Path(work_dir / "production")
# result.backup_archive       -> Path(work_dir / "production/backups/<stem>_<date>.zip")
# result.artifacts            -> tuple[FabricationArtifact, ...]
#   each: artifact_type in {"bom","pos","gerber","designators","backup"}
#         path, media_type
# result.diagnostics          -> tuple[Diagnostic, ...]
# result.bom_result / pos_result / gerber_result  -> per-step results
```

This single call produces all of the artifacts kproj's Jekyll front‑matter contract names with `tag: "fab"`, `tag: "bom"`, `tag: "ibom"` (no — iBOM is not jBOM; see below), and the source zip / backup. For Gerbers it shells out to `kicad-cli pcb export gerbers|drill|ipc356`.

**What `FabricationWorkflow` does NOT produce** — and kproj must add itself:

- **Top render** (`kicad-cli pcb render --side top --output top.png ... PCB`).
- **Bottom render** (`kicad-cli pcb render --side bottom --output bottom.png ...`).
- **Thumbnail** (PIL/Pillow crop of the top render to ~400×400 px).
- **Schematic SVG** (`kicad-cli sch export svg --output schematic.svg ... SCH`).
- **PCB SVG** (`kicad-cli pcb export svg --output board.svg ... PCB`).
- **STEP model** (`kicad-cli pcb export step --output model.step ... PCB`).
- **Interactive HTML BOM** (`InteractiveHtmlBom` plugin — a separate project, not jBOM. kproj must invoke its standalone CLI script, e.g. `python -m InteractiveHtmlBom.generate_interactive_bom <pcb>`, or vendor that one specifically).
- **DRC / ERC reports** (`kicad-cli pcb drc` / `kicad-cli sch erc`).
- **Source snapshot zip** (kproj zips the project tree itself).
- **Git tag**, **`gh release create`**, **Jekyll front‑matter and asset deployment**.

## 5. Suggested fab boundary

kproj's internal `fab` module calls jBOM at exactly one seam:

```python path=null start=null
# kproj/fab.py (sketch)
from jbom.application.fabrication_orchestration import (
    FabricationWorkflow,
    FabricationRequest,
)

def run_fab(*, project_dir: Path, work_dir: Path,
            fabricator: str = "jlc",
            inventory_files: tuple[str, ...] = (),
            dry_run: bool = False) -> FabricationResult:
    return FabricationWorkflow().run(FabricationRequest(
        input_path=str(project_dir),
        fabricator=fabricator,
        production_root=str(work_dir),
        inventory_files=inventory_files,
        archive_template="${TITLE}_${REVISION}",
        generate_designators=True,
        dry_run=dry_run,
    ))
```

Contract:
- **Inputs**: project directory (or `.kicad_pro` / `.kicad_pcb` / `.kicad_sch`); fabricator id; optional inventory CSV paths; dry‑run flag.
- **Outputs**: a `FabricationResult` with `production_dir`, `backup_archive`, `artifacts` (each tagged `bom / pos / gerber / designators / backup` with a filesystem path and media type), and `diagnostics`.
- **Side effects**: writes the `production/` subtree under `production_root` (typically `work_dir`). No mutation of the source KiCad project. No network access (gerber generation uses local `kicad-cli`).
- **Exit semantics**: `FabricationResult.diagnostics` may carry `severity="error"` entries (e.g. `kicad_cli_not_found`); kproj decides how that maps to its CLI exit code. For CI, propagate any error severity as non‑zero.

## 6. Risks

- **`${COMMENT1..9}` / `${STATUS}` gap.** Already covered in §4.2 — jBOM does not extract them. kproj must build the reader. Mitigation: small kproj module + jBOM's `sexp_parser.load_kicad_file`. Risk: ongoing drift if jBOM later adds its own COMMENT support with a different shape.
- **AGPL‑3.0 license.** Vendoring jBOM source into kproj (whose license is not yet stated in the plan) would require kproj to be AGPL‑3.0‑compatible. Importing as a runtime dependency is fine. Recommendation: never vendor.
- **stderr noise from `ProjectFileResolver._resolve_directory`** — prints `"found project X / found schematic Y / found pcb Z"` to stderr unconditionally on directory inputs (`services/project_file_resolver.py:236-250`). kproj's CI/log‑friendly output requirement means we may need to suppress this with `contextlib.redirect_stderr` or by patching `print` semantics. Alternative: file an upstream issue to gate this on `options.verbose` (small upstream PR, low risk).
- **`pydantic>=2.0` dependency**. jBOM forces a pydantic 2.x install (used heavily in `config/fabricators.py` and `config/suppliers.py`). kproj inherits this even if it never touches the config layer. Acceptable for Python ≥3.11 but pin compatibility carefully in `pyproject.toml`.
- **Mandatory `requires-python = ">=3.10"` in jBOM vs. kproj's `>=3.11`** — no conflict (kproj's narrower range is a subset).
- **`is_running_inside_kicad()` import side effect** — calls `import pcbnew`. In a non‑KiCad env this raises `ImportError` which is caught. Safe, but noisy on `strace`/import‑order diagnostics. Not a real risk; mention so the architect knows what shows up in `python -X importtime`.
- **Lock file detection** (`ProjectContext.is_locked`) — useful, but kproj's release pipeline should refuse to release while KiCad is open. Plan should incorporate a precheck step.
- **Hierarchy schematic regex parsing** — `ProjectContext._extract_sheet_files` uses a regex on `(property "Sheetfile" "...")`. Acceptable for current KiCad 9 files; could miss edge cases (e.g. `Sheetfile` written with single quotes). Low risk; jBOM's tests cover it.
- **`FabricationWorkflow` couples to concrete services** (`BOMWriter`, `POSWriter`, `BackupService`, `GerberExporter`, `DefaultKiCadReaderService`) via direct imports inside `run()`. There is no DI / no protocol. For kproj's TDD, this means kproj's tests will need to stub at the **request/result** boundary (treat `FabricationWorkflow` as a black box) rather than mocking inner services. Plan accordingly when writing Gherkin scenarios for kproj's `fab` step.
- **No protocol/ABC at the orchestration boundary** — if jBOM later renames `FabricationRequest` fields or adds required params, kproj breaks at import time. Mitigate with a kproj‑side adapter (`kproj/_jbom_adapter.py`) so the rename surface is one file.
- **`JobRunner` indirection inside `cli/fabrication.py`** — if Phase‑7 testing reveals that `JobRunner` does something kproj's CLI also benefits from (cancellation, progress streaming), revisit. Today it adds nothing; default skip.
- **`kicad_jbom_plugin.py` at repo root** — separate from `src/jbom/`; not part of the wheel install. Ignore for kproj.

## 7. Open questions for the architect

1. **AGPL boundary** — does the project intend kproj to be AGPL‑3.0‑compatible (so the import dependency on jBOM is fully clean), or will kproj be released under a different license that needs a careful import‑only treatment? If the latter, surface to the user. (The repo location `plocher/kproj` and the existing `plocher/jBOM` both being owned by the same user mitigates much of the practical risk, but the license headers should be coherent.)
2. **`${COMMENT1..9}` reader location** — is the kproj‑side extension acceptable for Phase 1, or does the user want an upstream PR to `jbom.services.pcb_reader` / `schematic_reader` and a TitleBlockMetadata field addition (e.g. `comments: tuple[str, ...]` or `comment_1..comment_9: str`) before the Phase‑6 implementation kicks off? Either way, name the field shape now so kproj does not have to refactor twice.
3. **`${STATUS}` source** — confirm that "`${STATUS}` lives in `.kicad_pro` `text_variables` map" is the working assumption. The `survey-kicad-fields` sibling agent's report will give the empirical answer; the architect should reconcile that with this report's recommendation before locking the Phase‑3 PRD.
4. **`kicad-cli` location strategy** — jBOM's `gerber_service` probes PATH + macOS app bundle + Windows Program Files + Linux defaults. kproj's `render`, `ibom`, `tag`, etc. all need to invoke other `kicad-cli` subcommands. Should kproj reuse jBOM's `_find_kicad_cli()` (it is module‑private — would need either an upstream `kicad_cli_locator` extraction PR or kproj reimplementing the probe)? **Recommendation**: small upstream PR to `jbom.services.gerber_service` exposing `find_kicad_cli()` as public, then `from jbom.services.gerber_service import find_kicad_cli` from kproj.
5. **iBOM tool surface** — InteractiveHtmlBom is a separate KiCad plugin/CLI script, not jBOM. The plan calls for kproj to embed iBOM artifacts; how does the architect want iBOM invoked (vendored copy of `generate_interactive_bom.py`, PyPI dependency on `InteractiveHtmlBom` (the upstream `openscopeproject/InteractiveHtmlBom` does publish a Python package), or `kicad-cli` plugin invocation)? This was not part of `ingest-jbom` scope but it materially affects the kproj `ibom` module design and worth flagging.
6. **stderr suppression policy** — kproj's primary execution context is Makefile/CI with structured JSON status. jBOM's `ProjectFileResolver` will leak `"found project X / found schematic Y / found pcb Z"` to stderr. Acceptable, or should kproj wrap every jBOM call in a stderr redirect? **Recommendation**: redirect for `--json` mode, pass through for default mode.
7. **DRC / ERC artifacts** — the Jekyll contract optionally includes `drc.json` and `erc.json`. Neither is produced by jBOM. Confirm kproj's `fab` module is responsible for those via direct `kicad-cli pcb drc` / `kicad-cli sch erc` calls; jBOM is purely for BOM/POS/Gerber.
8. **Source snapshot scope** — what goes into the `source.zip` artifact? Just the project tree (`.kicad_pro / .kicad_sch / .kicad_pcb / *.kicad_sym / *.pretty/`) or the full git tree? jBOM has zero opinion here; kproj decides.

---

End of `ingest-jbom` Phase 1 report.
