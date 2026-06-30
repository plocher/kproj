# Changelog

All notable changes to **kproj** are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); semantic
versioning per [SemVer](https://semver.org).

## [Unreleased]

### Added - issue #2 (Phase 6 wave-2: read services)
- `pyproject.toml`: depend on `jbom>=7.3.0` (PR plocher/jBOM#333 merged);
  local-editable `tool.uv.sources` path during development; mypy override
  ignores missing jBOM library stubs.
- `src/kproj/model/publish_request.py` + `src/kproj/model/publish_result.py`:
  relocated wave-1 `PublishRequest` / `PublishResult` from
  `application/publish_workflow.py` to the model layer.  Added the
  authoritative `compute_exit_code(outcome, findings)` helper +
  `PublishResult.build(...)` factory so the workflow populates
  `PublishResult.exit_code` instead of `cli.py` re-deriving it.
  `services/site_publisher.py` drops its `TYPE_CHECKING` import in
  favour of a direct model-layer import.  Wave-1 carry-forward
  decisions both resolved.
- `src/kproj/model/raw_title_block.py`: new `RawTitleBlock` dataclass
  carrying per-file SCH + PCB title-block snapshots on `ProjectInfo`
  for the audit layer.
- `src/kproj/services/kicad_project_reader.py`: rewrites the wave-1
  walking-skeleton resolver as a thin wrapper over
  `jbom.application.pcb_project_loader.resolve_pcb_input` per ADR
  0003; preserves the SPCoast `<basename>` fallback against
  `~/Dropbox/KiCad/projects/`; implements `read()` using jBOM's
  `DefaultKiCadReaderService` + `SchematicReader` and applies the
  per-field metadata precedence locked in `docs/DESIGN.md`
  (PCB-canonical title/company/rev/date with SCH fallback; SCH-canonical
  COMMENT2/3/9 with PCB fallback; first-non-empty COMMENT1).
- `src/kproj/model/resolved_project.py`: now exposes the jBOM 7.3.0
  `text_variables` mapping on `ResolvedProject` (v1 does not consume it;
  forward-compat carry-through).
- `src/kproj/services/metadata_analyzer.py`: 14-rule audit table from
  DESIGN's heuristic list - file existence, title-block presence,
  SCH/PCB disagreement, placeholder values, COMMENT9 taxonomy +
  missing-defaulting, date format, designer format, rev relation
  (board_rev = design_rev + uppercase suffix), replaced-by target
  existence, production/ presence + staleness.
- `src/kproj/services/design_analyzer.py`: invokes `kicad-cli pcb drc`
  and `kicad-cli sch erc` via the shared subprocess runner with
  `--format json --severity-all`, writes to a tempfile that is
  deleted before return, parses violations + per-item findings,
  preserves KiCad's `exclusion` severity (ADR 0004 - exclusions do
  NOT contribute to the exit-code-1 findings-present rule).
- `application/publish_workflow.py`: wires DESIGN steps 2-4 (read +
  analyze + status detection) onto the wave-1 pre-flight.  A project
  whose `${COMMENT9}` is `private` short-circuits with
  `outcome="private-skip"` BEFORE the iBOM / site-cleanliness
  pre-flight wave-3 will add.  Steps 5-11 remain stubbed.
- `tests/_kicad_fixtures.py`: shared fixture builder producing minimal
  `.kicad_sch` / `.kicad_pcb` / `.kicad_pro` from a `TitleBlockSpec`.
- `tests/unit/services/test_kicad_project_reader.py`: rewrites the
  wave-1 self-contained-resolver tests + adds per-field-precedence
  read tests (19 tests).
- `tests/unit/services/test_metadata_analyzer.py`: per-rule audit
  coverage (31 tests).
- `tests/unit/services/test_design_analyzer.py`: DRC + ERC JSON
  parser tests using an injected runner (8 tests).
- `tests/unit/application/test_publish_workflow.py`: wave-2 pre-flight
  + read + analyze + status-detection assertions (9 tests).
- `tests/features/private_status.feature` + steps: PRD Story 7
  (private-skip) Behave scenario.

### Added - issue #3 (Phase 6 wave-3: producer services)

- `services/pcb_exporter.py`: `PcbExporter.export_render(side)` +
  `export_step()` per `docs/DESIGN.md` section PcbExporter. Atomic via
  sibling-tempfile + `os.replace`; optional `ChangeJournal` injection
  registers the artifact for ADR-0005 rollback before kicad-cli runs.
  Argv: `<kicad_cli> pcb render --side {top|bottom} --output <file>
  <pcb>` and `<kicad_cli> pcb export step --force --output <file>
  <pcb>` (the `--force` is needed by KiCad 9/10 to overwrite the
  staging tempfile path).
- `tests/fixtures/minimal/minimal.kicad_{sch,pcb}`: tiny hand-written
  v8+ KiCad files for contract-test bootstrap (one rectangle on
  Edge.Cuts, empty schematic).
- Contract tests against the local kicad-cli for `pcb render top` +
  `pcb render bottom` (PNG magic bytes) + `pcb export step`
  (`ISO-10303-21` header).
- `services/schematic_exporter.py`: `SchematicExporter.export_svg(
  root_only=True)` + `export_pdf(all_sheets=True)` per
  `docs/DESIGN.md` § SchematicExporter. SVG uses a private temp
  directory + `--pages 1` selector + discover-and-move pattern
  (kicad-cli's SVG `--output` is OUTPUT_DIR per the locally-installed
  build's help text). PDF is direct-file output through a sibling
  tempfile (`--output` is OUTPUT_FILE in the same build). Adds a
  `SchematicExportError` raised when kicad-cli emits zero or (in
  `root_only=True` mode) multiple SVGs.
- Contract tests against the local kicad-cli for `sch export svg`
  (root-only, XML/SVG header) + `sch export pdf` (`%PDF-` header).
- `services/ibom_generator.py`: `IbomGenerator.generate(pcb_path,
  output_file, name_format)` per ADR 0008. Invokes
  `<sys.executable> <ibom_script> --no-browser --no-compression
  --dest-dir <tempdir> --name-format <P>-<R>.ibom --extra-data-file
  <pcb> --dnp-field kicad_dnp --extra-fields MPN,Manufacturer
  --include-tracks <pcb>` directly via `common.subprocess_runner`,
  then atomically moves `<tempdir>/<name_format>.html` into
  *output_file*. Signature changed from the foundation stub's
  `output_dir` form to `output_file` so callers don't have to know
  the iBOM staging-dir convention.
- Contract test against the locally-installed iBOM PCM plugin
  (skipif when not present).
- `services/fab_packager.py`: `FabPackager.package(production_dir,
  output, title, rev, pcb_path)` per `docs/DESIGN.md` § FabPackager +
  ADR 0003. Discovers the gerber pack as
  `<production_dir>/<title>_<rev>.zip` first, falling back to the
  single `*.zip` in production. Produces a fab.zip containing exactly
  three entries: `bom.csv`, `pos.csv`, `gerbers.zip` (the discovered
  gerber pack, renamed to the normalized name regardless of source
  filename). Returns `ExportResult(skipped=True)` when `production/`
  is missing/empty, BOM or POS files are absent, or gerber-zip
  discovery is ambiguous. Emits a `production_stale` warning when
  production files are older than the PCB. Atomic via sibling-
  tempfile + `os.replace`; optional ChangeJournal injection.

### Added - issue #1 (Phase 6 foundation)

- Walking-skeleton package layout under `src/kproj/` matching
  `docs/DESIGN.md` section Source layout - `model/`, `services/`, `common/`,
  `application/`, `formatters/`.
- Frozen domain dataclasses: `Severity`, `Finding`, `ProjectInfo`,
  `AnalysisInfo`, `Publication`, `ResolvedProject`, `ExportResult`.
- Configuration layer: `ConfigOverrides`, `KprojConfig`,
  `load_config()` with precedence CLI flag > env > `~/.kproj.yaml` >
  default per `docs/DESIGN.md` section Configuration layer.
- CLI surface: `kproj [<project-or-dir-or-file>] [--site-repo PATH] [--dry-run] [--no-push] [-v] [-d]`
  with argparse confined to `cli.py` (ADR 0006) and exit-code mapping
  0 / 1 / 2 per section Exit code mapping.
- `common/kicad_install.py` per ADR 0009: `find_kicad_cli`,
  `find_plugins_dir`, `find_ibom_script`, `kicad_version` with
  per-platform probes (macOS / Linux / Windows) plus env + PATH fallback.
- `common/subprocess_runner.py`: single `run()` entry point with
  per-step timeouts, signal handling, `SubprocessTimeoutError`,
  `SubprocessFailedError`, and `SubprocessResult`. The only place in
  kproj that calls `subprocess.run`.
- `services/change_journal.py`: `ChangeJournal` context manager with
  `will_create` / `will_modify` / `mark_committed` / `mark_pushed` /
  `rollback` per ADR 0005; dry-run mode registers intent without
  writes.
- `services/zip_archiver.py`: domain-agnostic `ZipArchiver.archive`
  returning `ExportResult`.
- `application/publish_workflow.py`: walking-skeleton `PublishWorkflow`
  performing pre-flight (project resolution + kicad-cli discovery +
  major-version check) and returning
  `PublishResult(outcome="failed", exit_code=2)` for downstream steps
  that remain stubbed in this slice.
- Stubs for the remaining services (`MetadataAnalyzer`, `DesignAnalyzer`,
  `PcbExporter`, `SchematicExporter`, `IbomGenerator`, `FabPackager`,
  `SourcePackager`, `SitePublisher`) and formatters
  (`StderrFormatter`, `MarkdownTableFormatter`,
  `FrontMatterSummaryFormatter`) that raise `NotImplementedError`.
- pytest + Behave + ruff + mypy configured; pre-commit hooks for
  ruff / mypy / pytest.
- Unit tests for every foundation module plus contract test for the
  KiCad install locator (`@pytest.mark.skipif` on local KiCad).
