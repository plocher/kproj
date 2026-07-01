# Changelog

All notable changes to **kproj** are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); semantic
versioning per [SemVer](https://semver.org).

## [Unreleased]

### Fixed - issue #4 wave-3 review fix-up round-2 (post re-review)

The gpt-5-5-xhigh re-review of the round-1 fix-up (see the `## Re-review
(post-fix-up)` appendix in `docs/wave3-review.md` on branch
`review/wave-3` commit `58e0d55`) found 2 MAJOR partials and 1 MINOR.
Both MAJORs are addressed here on the same `feat/issue-4-publishing`
branch, driven by failing tests first per the user-locked TDD workflow.

- **M4 (round-2)** — DRC/ERC mechanical-failure channel. Round-1 modelled
  a `kicad-cli` crash (nonzero rc + no JSON) as an ordinary error
  `Finding`, but `compute_exit_code` then mapped a mechanical failure to
  `exit=1` ("findings present, publish succeeded") instead of the
  contracted `exit=2`. Round-2 gives mechanical failures a distinct
  channel: `DesignAnalyzer` raises the new `DesignAnalysisError`
  (carrying `origin` and `returncode`) and `PublishWorkflow.run()`
  catches it *before* opening the change journal, returning
  `PublishResult(outcome="failed", exit_code=2)` with no site writes.
  Parseable DRC/ERC violations continue to flow as non-blocking
  findings per ADR 0004. New Behave feature
  `tests/features/drc_erc_mechanical_failure.feature` locks the
  contract for both DRC and ERC crash paths.
- **M11 (round-2)** — Story 6 metadata-refresh is now a real functional
  gate. Round-1's Behave step artificially bumped every published
  asset's mtime into the future to defeat the M1 stale-asset rule;
  that hid the real behavior. Round-2 removes the workaround and
  drives the code fix from failing tests per the user's GIVEN/WHEN/
  THEN framing ("kproj-published baseline; edit COMMENT9 in SCH;
  outcome=refreshed; no artifact regen; commit uses `refresh:` prefix").
  Six scenarios cover experimental→active, active→{broken, retired,
  replaced-by:<other>, private, empty (defaults to active)}.

  **Code fix (Option B: title-block-only refresh detection)** chosen
  over Option A (full content hash) and Option C (explicit
  `--refresh` flag). New `kproj/common/content_hash.py` walks the
  KiCad S-expression paren tree (quoted-string aware) and computes
  `sha256(sch_content_minus_title_block)` and the same for the PCB.
  Both hashes are threaded onto `Publication` and persisted in the
  version-page YAML front-matter under `kproj_source_hashes: {sch,
  pcb}`. On a subsequent run the workflow reads back the persisted
  hashes; when they match the current hashes the M1 stale-asset
  escalation is skipped (title-block-only edits stay `refresh` /
  `noop`). Real content edits still flip the hash and the M1
  escalation fires exactly as before. `test_stale_pcb_forces_publish_
  outcome` updated to modify PCB content (not just mtime) so the M1
  guarantee is exercised against a genuine content change; pure
  mtime touches no longer cause spurious publishes.
- **MINOR (CHANGELOG accuracy)** — the round-1 CHANGELOG entry
  characterised M4 and M11 as fully fixed; the re-review found both
  were only partial. The round-1 wording below has been corrected to
  say "round-1 partial" and point at the round-2 completion above.

All unit tests (355) + contract tests + Behave scenarios (16) pass;
ruff + mypy clean.

### Fixed - issue #4 wave-3 review fix-up (PR #11 re-review response, round-1)

Adversarial cross-family review of PR #11 (see `docs/wave3-review.md` on
branch `review/wave-3` commit `e5d7483`) surfaced 5 BLOCKERs + 12 MAJORs.
All 5 BLOCKERs plus the correctness MAJORs are fixed here on the same
`feat/issue-4-publishing` branch; the remaining MAJORs are filed as
follow-up issues (see below).

**BLOCKERs (all 5 fixed):**
- **BLOCKER 1** — production artifact paths used the project name as the board
  revision (`_default_artifact_generator` read `resolved.project_file.stem`).
  Fix threads `ProjectInfo` (carrying canonical PCB-derived `board_rev`) into
  `ArtifactGeneratorCallable`; generator now uses `project_info.project` and
  `project_info.board_rev` for on-disk layout, filenames, and AssetRef paths.
- **BLOCKER 2** — `SitePublisher.publish` staged only the version-page and
  project-page markdown, leaving producer-generated assets untracked while the
  committed markdown linked to them. Fix stages every path from
  `ChangeJournal.all_paths()` per ADR 0005.
- **BLOCKER 3** — every artifact producer called `journal.will_create` without
  checking existence; a re-publish's rollback would unlink already-committed
  assets. Fix adds `ChangeJournal.register_output(path)` helper that dispatches
  to `will_modify` when the path exists and `will_create` otherwise; every
  producer routes through it.
- **BLOCKER 4** — findings never reached the user's terminal (ADR 0004 violation).
  Fix wires `StderrFormatter` into `cli.main()` so every audit/DRC/ERC finding
  is printed on stderr as a one-liner before the result message.
- **BLOCKER 5** — `SchematicExportError` and iBOM's `FileNotFoundError` escaped
  the workflow as tracebacks instead of becoming `outcome="failed"`/exit 2. Fix
  extends the exception ladder in `PublishWorkflow.run`.

**Correctness MAJORs fixed in this PR:**
- **M1** — asset freshness detection: `_assets_are_stale(images, artifacts,
  resolved, site_repo)` compares each asset's mtime against its source (PCB /
  SCH / project source set / production/). Workflow escalates `noop`/`refresh`
  to `publish` when any asset is stale. `SitePublisher.publish` grows a
  `force_outcome=` keyword so post-generation asset mtimes cannot re-decide
  the outcome inside the publisher.
- **M2** — front-matter counts partitioned by `Finding.source`. New `source:
  str = ""` field on `Finding` (closed taxonomy: `audit` / `drc` / `erc` /
  `read` / empty). `MetadataAnalyzer` stamps `source="audit"` on every emitted
  finding via `dataclasses.replace`. `KicadProjectReader` stamps `source="read"`.
  `AnalysisInfo` gains `count_by_source(severity, sources)`.
  `FrontMatterSummaryFormatter` counts audit / drc / erc from their own
  sources so a DRC error no longer inflates all three blocks.
- **M3** — DRC/ERC Markdown table Location column now renders `Finding.value`
  (the actual KiCad coordinate / uuid / sheet); new Source column surfaces
  the origin (`drc` / `erc`). Section discriminator uses `source` first,
  falls back to `AUDIT_FIELDS` for legacy findings.
- **M4 (round-1 partial)** — DesignAnalyzer captured the
  `SubprocessResult` and emitted a `<origin>_mechanical_failure`
  error `Finding` instead of silently returning `()`. The re-review
  flagged that this still resolved to `exit=1` rather than the
  contracted `exit=2`; **round-2 completes the fix** by giving
  mechanical failures a distinct exception channel
  (`DesignAnalysisError`) that the workflow catches before opening
  the journal. See the round-2 entry above.
- **M6** — artifact-generator diagnostics flow into the final analysis. New
  3-tuple contract: `(images, artifacts, diagnostics)`. Workflow merges the
  diagnostics into a fresh `AnalysisInfo`, rebuilds the body markdown, and
  passes the merged findings to `build_publication` so producer warnings reach
  the front-matter counts, Markdown tables, stderr, and exit code.
- **M11 (round-1 partial)** — Behave scenarios were rewritten as real
  functional gates: Story 9 now injects a failing producer instead
  of running `--dry-run`; `verbose.feature` actually passes `-v`.
  However, the re-review flagged that Story 6 still masked the
  workflow behavior by artificially bumping asset mtimes to defeat
  the M1 stale-asset rule. **Round-2 completes the fix** by
  removing the mtime workaround, driving six status-transition
  scenarios, and adding title-block-stripped source-hash comparison
  to distinguish metadata-only from content edits. See the round-2
  entry above. Shared `_stub_artifact_generator` was updated in
  round-1 for the new 3-tuple signature and remains correct.
- **M12** — new contract tests `tests/contract/test_kicad_cli_drc.py` and
  `test_kicad_cli_erc.py` run the real local kicad-cli 10 and assert the JSON
  shapes kproj depends on. The tests caught a real drift: KiCad 10 ERC nests
  findings under `sheets[<n>].violations` instead of a top-level `violations`
  array, and pre-fix `DesignAnalyzer` silently produced zero findings from
  KiCad 10 ERC output. `_findings_from_payload` now walks both shapes.

**Follow-up issues filed (unfixed MAJORs):**
- kproj#12 (M5): dry-run should render a full path/would-be-write preview.
- kproj#13 (M7): project page front-matter contract (layout/sidebar/tags/etc.).
- kproj#14 (M8): production emission drops tags and `replaced-by:<target>`.
- kproj#15 (M9): implement thumbnail generation (long-deferred).
- kproj#16 (M10): wire `-v` through subprocess + git command logging.

Round-1 baseline: unit tests + contract tests + Behave scenarios all
passed; ruff + mypy clean. Post-round-2 totals appear in the round-2
entry above.

### Added - issue #4 (Phase 6 wave-4: publishing + formatters + Behave)

- `src/kproj/formatters/stderr_formatter.py`: `StderrFormatter.format_findings()`
  renders each `Finding` as a one-liner on stderr in the format
  `<severity> [<field>] <project>:<field>: <reason> (value: <value>)` per
  ADR 0004 § *What "surfaced" means*. `(value: …)` suppressed when empty;
  `<project>:` suppressed when project is empty.
- `src/kproj/formatters/markdown_table_formatter.py`: `MarkdownTableFormatter.render()`
  produces two adjacent Markdown tables — *Metadata Audit* (findings whose `field`
  is in the closed `AUDIT_FIELDS` set) and *DRC / ERC Findings* — matching the
  version-page body contract in `docs/DESIGN.md` § *Front-matter shape*. Both
  sections always present; empty sections show an italicised no-findings row.
- `src/kproj/formatters/front_matter_summary_formatter.py`:
  `FrontMatterSummaryFormatter.render(publication)` produces the full YAML front-
  matter for `_versions/<P>/<R>.md` per the authoritative contract in `docs/DESIGN.md`
  § *Front-matter shape*. Includes `iskicad: true` / `'obsolete'` (retired/replaced-by),
  all Jekyll-required fields, `images:` + `artifacts:` lists, `audit:`/`drc:`/`erc:`
  count summaries, and the `libraries:` three-bucket YAML section
  (`internal:`/`external:`/`ambiguous:`) introduced by kproj#4 wave-3 scope.
  Also exposes `render_audit(analysis_info) -> dict` for backward compatibility.
- `src/kproj/model/publication.py`: added `readme_md: str = ""` field carrying the
  project's README.md content for writing `pages/<P>.md` + new-release detection.
- `src/kproj/services/site_publisher.py`: full `SitePublisher` implementation replacing
  the foundation stub. `detect_outcome(publication, site_repo)` static method computes
  `"noop"` / `"refresh"` / `"publish"` by (1) checking version file existence, (2)
  checking asset presence in the site repo, (3) comparing rendered version content to
  on-disk content, (4) comparing `pages/<P>.md` body to `publication.readme_md`.
  `publish(publication, site_repo, no_push, dry_run)` writes `_versions/<P>/<R>.md` +
  `pages/<P>.md` atomically via tempfile + `os.replace`, registers both with the
  `ChangeJournal` (ADR 0005), runs `git add` + `git commit` + (unless `no_push`)
  `git push`, marks the journal `committed`/`pushed`. Commit message patterns:
  `add: <P> <R>` (first-ever publish), `publish: <P>-<R>` (new version), `refresh:
  <P>-<R> (metadata updated)` (refresh). Dry-run skips all writes and git ops.
- `src/kproj/application/publish_workflow.py`: wires all 11 DESIGN pipeline steps.
  Steps 5–11 added: iBOM pre-flight (`ibom_script_locator` injectable), site-repo
  cleanliness check (`git status --porcelain`, skipped on `dry_run`), new-release
  detection via `SitePublisher.detect_outcome`, `ChangeJournal` scope, artifact
  generation (`artifact_generator` injectable, default calls all real exporters +
  packagers), `build_publication` (now accepts `readme_md` and reads `README.md`
  via `_read_readme`), `SitePublisher.publish`. New injectable factories:
  `ibom_script_locator`, `artifact_generator`, `site_publisher_factory`. Helper
  functions: `_read_readme`, `_compute_standard_asset_refs`, `_default_artifact_generator`.
  Pipeline exceptions (`SubprocessFailedError`, `SubprocessTimeoutError`, `OSError`)
  are caught and returned as `outcome="failed"`.
- **Test coverage (unit + Behave)**: 319 unit tests, 14 Behave scenarios covering
  PRD Stories 1-13. Feature files: `publish.feature` (Stories 1, 13), `dry_run.feature`
  (Story 2), `project_resolution.feature` (Story 3), `findings_surfaced.feature`
  (Stories 4, 5), `metadata_refresh.feature` (Story 6), `private_status.feature`
  (Story 7 - pre-existing), `batch_safety.feature` (Stories 8, 9), `site_repo_cleanliness.feature`
  (Story 10), `verbose.feature` (Story 12). Stories 14-18 documented as Phase 7
  manual-validation in `publish.feature` comments (cross the Jekyll build).
- **iBOM stub choice** (`publish_steps.py`): the Behave artifact generator writes
  placeholder `.ibom.html` files without invoking real iBOM (gated on kproj#10
  spike). The pipeline orchestration is fully tested; iBOM integration is contract-
  tested separately in `tests/contract/test_ibom_generator.py`.

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
- `services/source_packager.py`: `SourcePackager.package(project_dir,
  output, *, title, rev)` per `docs/DESIGN.md` § SourcePackager. Walks
  `project_dir` applying the documented include/exclude rules and
  assembles the matching project files into `<P>-<R>.source.zip` via
  an atomic sibling-tempfile + `os.replace`. Optional ChangeJournal
  injection registers the produced zip for ADR-0005 rollback.
- Drop `SOURCE_README.md` from `source.zip` output; `SourcePackager`
  just packages project files. The generic "how to install KiCad and
  open a .kicad_pro" content was bureaucratic noise, and KiCad's own
  UI surfaces missing libraries on project open - so no per-archive
  manifest is needed. PRD Story 17 + DESIGN § SourcePackager +
  `docs/phase4-resolutions.md` M7 row updated to match.
- Restore the library-enumeration logic that was over-rolled-back
  with the SOURCE_README drop, and extend it with per-entry
  classification per user feedback during PR#9 amendment.  New
  `src/kproj/model/library_ref.py` introduces `LibraryRef(name,
  source)` (frozen, orderable) where `source` is
  `Literal["internal", "external", "ambiguous"]`.  New utility
  `src/kproj/common/kicad_libraries.py::enumerate_libraries(
  project_dir) -> tuple[LibraryRef, ...]` scans `fp-lib-table` +
  `sym-lib-table` + every `(lib_id "lib:name")` / `(footprint
  "lib:name")` reference in `.kicad_sch` / `.kicad_pcb` /
  `.kicad_sym` files; classifies each library as `internal`
  (`${KIPRJMOD}` URI that does not escape), `external` (any other
  URI), or `ambiguous` (referenced but no lib-table entry).
  Lib-table entries win over bare lib_id refs for the same name.
  Output is stable-sorted by `(name, source)` and reproducible.
  New `Publication.libraries: tuple[LibraryRef, ...]` field carries
  the result; `PublishWorkflow.build_publication(resolved,
  project_info, analysis_info)` (DESIGN step 8) populates it today.
  `SitePublisher` rendering of the field is tracked by kproj#4.
  PRD Story 17 + DESIGN § Library enumeration +
  `docs/phase4-resolutions.md` M7 second follow-up capture the
  design.

### Fixed - issue #3 (wave-3 follow-up)

- `common/kicad_install.py`: probe KiCad 10 install paths in
  addition to KiCad 9 (`KICAD10_3RD_PARTY` env var,
  `~/Documents/KiCad/10.0/3rdparty/` on macOS,
  `~/.local/share/kicad/10.0/3rdparty/` on Linux,
  `%APPDATA%\kicad\10.0\3rdparty\` and
  `C:\Program Files\KiCad\10.0\bin\kicad-cli.exe` on Windows) -
  KiCad 10 first, KiCad 9 fallback.  The `iBOM` contract test
  was silently skipping on KiCad 10 hosts because the v9-only
  probe tables couldn't see the v10 plugins.  The workflow's
  major-version gate now reads from a new
  `SUPPORTED_KICAD_MAJORS = frozenset({9, 10})` module-level
  constant so the locator + workflow agree on which majors get
  probed AND accepted. ADR 0009 amended with a "Version support"
  addendum capturing the probe order and the policy for future
  KiCad majors.
- `services/ibom_generator.py`: pass
  `INTERACTIVE_HTML_BOM_NO_DISPLAY=1` in the subprocess env when
  invoking the PCM iBOM script. The script imports wxPython
  unconditionally otherwise, and kproj runs headless per ADR 0007
  + ADR 0008 (Makefile / CI use case).  Defect surfaced by the
  iBOM contract test once the locator started actually finding
  the v10 script.

### Design decisions (Wave 2 architect-review carry-forwards)

- **ChangeJournal injection pattern**: producers accept the journal
  as an optional method parameter, not a constructor argument.
  Services are reusable across publish runs; the journal is
  per-publish-run. The journal is registered with
  `will_create(output)` *before* the subprocess invocation so that
  even mid-step kicad-cli failure leaves the journal coherent for
  ADR-0005 rollback.
- **Atomic write pattern**: all five producers use a hidden
  sibling-tempfile (`.<stem>.<8hex>.part<suffix>`) + `os.replace`.
  Keeping the original suffix on the tempfile means kicad-cli /
  iBOM scripts that infer output format from extension still see
  the expected suffix.

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
