# Changelog

All notable changes to **kproj** are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); semantic
versioning per [SemVer](https://semver.org).

## [Unreleased]

### Added — issue #1 (Phase 6 foundation)

- Walking-skeleton package layout under `src/kproj/` matching
  `docs/DESIGN.md` § Source layout — `model/`, `services/`, `common/`,
  `application/`, `formatters/`.
- Frozen domain dataclasses: `Severity`, `Finding`, `ProjectInfo`,
  `AnalysisInfo`, `Publication`, `ResolvedProject`, `ExportResult`.
- Configuration layer: `ConfigOverrides`, `KprojConfig`,
  `load_config()` with precedence CLI flag > env > `~/.kproj.yaml` >
  default per `docs/DESIGN.md` § Configuration layer.
- CLI surface: `kproj [<project-or-dir-or-file>] [--site-repo PATH] [--dry-run] [--no-push] [-v] [-d]`
  with argparse confined to `cli.py` (ADR 0006) and exit-code mapping
  0 / 1 / 2 per § Exit code mapping.
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
