# CHANGELOG


## v0.4.0 (2026-07-15)

### Features

* feat: humanize console output and flush no-push site commits (#43, #44) ([`4acb4b8`](https://github.com/plocher/kproj/commit/4acb4b8c2e8986ed95bc541cc0a116d8e296740a))


## v0.3.2 (2026-07-14)

### Bug Fixes

* fix(datasheet): pass -q to the jbom invocation to silence guidance diagnostics (#41)

jBOM emits guidance diagnostics (e.g. 'Warning: Missing important
generic fields: ...') on stderr during bom generation, which leaked
into kproj's terminal/captured stderr during publish runs.

Adds the global -q flag unconditionally to both jbom invocation forms
in _default_jbom_command (PATH jbom and the python -m jbom fallback),
preceding the bom subcommand as required for a global jBOM flag:
jbom -q bom <project_dir> --inventory <path> -f ... -o -

No version detection or backwards-compat gating, per owner ruling:
latest jBOM and latest kproj are always used together. Updated the
unit test asserting the invocation argv, and ADR 0010 + DESIGN.md.

Closes #41.

Co-Authored-By: Oz <oz-agent@warp.dev> ([`74a7a39`](https://github.com/plocher/kproj/commit/74a7a392112709617e9f85d0c107aca7c5386328))


## v0.3.1 (2026-07-14)

### Bug Fixes

* fix(datasheet): invoke jbom from PATH with correct field tokens (#36)

Fixes the broken `jbom bom` datasheet-name lookup:

- `-f` now passes normalized snake_case field tokens
  (reference,datasheet,datasheet_name) via the single extensible
  DATASHEET_BOM_FIELDS constant, instead of the display header
  'Datasheet Name' (a jBOM CLI syntax error that silently degraded
  every publish to the advisory finding).
- jbom is invoked from PATH (shutil.which), falling back to
  [sys.executable, -m, jbom] only when not found on PATH.
- When inventory is unconfigured, kproj no longer invokes jbom at
  all (no subprocess, no advisory finding) - there is no
  datasheet_name data to fetch without one.
- read_datasheet_rows returns structured per-reference DatasheetRow
  rows (reference, datasheet, datasheet_name); distinct_datasheet_names
  derives the deduped name list the Documentation section uses.
  read_datasheet_names is now a thin convenience wrapper over both.
- New real-jBOM integration test asserts the production field list
  against the actual jbom CLI (jbom is a declared kproj dependency,
  so .venv/bin/jbom exists after uv sync), closing the seam gap that
  let this ship broken.
- Updates ADR 0010, the datasheet_library module docstring, and
  DESIGN.md to match.

Closes #36.

Co-Authored-By: Oz <oz-agent@warp.dev> ([`97ee497`](https://github.com/plocher/kproj/commit/97ee4976d530425b6d7a30eb6b019ed168ac76f0))


## v0.3.0 (2026-07-14)

### Bug Fixes

* fix(publish): structurally enforce advisory-only datasheet guard; fix review findings

Addresses PR #35 adversarial review blockings #2 and #3, plus cheap advisories.

1. Structural enforcement (BLOCKING #2): PublishWorkflow.run no longer
   calls the datasheet-name lookup + check_datasheet_links guard
   unwrapped. New _lookup_datasheet_links() wraps both in a single
   try/except Exception, degrading to a datasheet_lookup_failed
   warning Finding instead of propagating - the 'advisory-only, never
   a publish blocker' guarantee no longer rests solely on
   read_datasheet_names/check_datasheet_links being individually
   exhaustive. Also fixes the unguarded candidate.is_file() call
   inside check_datasheet_links (new _is_file_safe() helper catches
   OSError - e.g. ELOOP on a symlink cycle). New regression test
   mutation-proves a raising lookup callable cannot fail a publish.

2. KprojConfig.inventory test coverage (BLOCKING #3): added the
   standard per-tier precedence tests (CLI > KPROJ_INVENTORY env >
   yaml > None default) mirroring the existing site_repo/no_push/
   kicad_cli pattern in tests/unit/test_config.py.

3. Advisories addressed:
   - Fixed stale 'read from production/jbom.csv, per ADR 0003'
     docstrings in model/datasheet_link.py and model/publication.py
     (both now correctly describe the live jbom-bom lookup, ADR 0010).
   - Fixed wrong ADR-0011 citation in datasheet_links.feature's
     comment (kproj's ADR is 0010; 0011 is jBOM's unrelated ADR).
   - build_datasheet_link() now percent-encodes the name segment
     (urllib.parse.quote) so a curated name with a space/reserved
     character still produces a well-formed URL.
   - read_datasheet_names() now dedups case-insensitively (casefold),
     matching the library's stated case-insensitive uniqueness
     invariant; previously a casing-differing duplicate from an
     upstream curation slip would survive as two separate links.

BLOCKING #1 (site-template mismatch) is being addressed via a
companion PR against SPCoast.github.io, tracked separately.

Validation: 453 pytest passed (+8 new), 12 features / 23 scenarios /
142 steps behave passed, ruff + ruff-format + mypy clean.

Co-Authored-By: Oz <oz-agent@warp.dev> ([`212bfad`](https://github.com/plocher/kproj/commit/212bfad85e7dfae0274301f5983b1ecb13e6aa88))

### Features

* feat(publish): datasheet deep-links from live jbom Datasheet Name lookup

Closes #29. Publishes per-component datasheet view + download links
into the public plocher/SPCoast-inventory library repo, sourced from
the BOM's curated 'Datasheet Name' column - no PDF copies, ever (per
jBOM#350's publish-mechanics resolution).

- kproj.common.datasheet_library: build_datasheet_link() constructs
  the deterministic view (GitHub blob) + download (raw.githubusercontent)
  URLs from a curated name (main-branch, no commit pinning - the
  library's Never-Rename invariant guarantees they cannot rot).
  read_datasheet_names() invokes `jbom bom <project> -f "Datasheet
  Name" -o -` live at publish time (not the stale production/jbom.csv
  fab snapshot - ADR 0010 amends ADR 0003's read-not-invoke for this
  one narrow, read-only case). check_datasheet_links() is the
  advisory-only, never-blocking publish guard: read-only against the
  conventional local SPCoast-inventory clone, warning on an
  unresolvable name or an unpushed library clone.
- Every failure mode (jbom missing/old/crashed, absent column,
  unresolvable/unpushed library) degrades to an advisory Finding
  rather than raising or blocking the publish.
- KprojConfig.inventory: Path | None (CLI/KPROJ_INVENTORY env/yaml
  precedence, no hardcoded fallback) forwards to `jbom bom
  --inventory` when configured.
- Publication.datasheets is now tuple[DatasheetLink, ...]; SitePublisher
  renders a datasheets: front-matter YAML list of {name, view,
  download} entries on the project section index.
- Retires the per-project *.pdf disk-walk (project_docs.discover_datasheets
  / discover_datasheet_files) and its site-copy sibling
  (_copy_datasheets in publish_workflow's artifact generator).
- New ADR 0010 documents the ADR 0003 amendment + the CLI-vs-services-API
  mechanism choice; CONTEXT.md and ADR 0003 updated to match (single-context
  docs rule).
- New behave feature (datasheet_links.feature) covering curated/uncurated
  components and jbom-too-old graceful degradation, driven through an
  injected datasheet_name_lookup seam so no scenario execs a real jbom
  subprocess.

Validation: 445 pytest passed, 12 features / 23 scenarios / 142 steps
behave passed, ruff + ruff-format + mypy clean.

Co-Authored-By: Oz <oz-agent@warp.dev> ([`2edd007`](https://github.com/plocher/kproj/commit/2edd00738519836f646d73310acfadd3fbc62c16))


## v0.2.0 (2026-07-13)

### Bug Fixes

* fix(publish): single-evaluate GitHub-link detection; complete AUDIT_FIELDS

Both adversarial-review advisories, upgraded to required fixes by
the human:

1. Single-source detection result. common.github_link.detect_github_link
   (renamed from the private _detect) is now the ONLY function that
   touches git for this feature; PublishWorkflow.run calls it exactly
   once per publish and threads the single GithubLinkDetection to both
   consumers - finding_for_detection (pure, no I/O) for the audit
   finding, and detection.url passed explicitly as
   build_publication's new github_url parameter for the front-matter
   field. The front-matter URL and the advisory finding can no longer
   be computed from two independent (and potentially disagreeing)
   detection passes. derive_github_link / derive_github_link_finding
   remain as detect-and-return convenience wrappers for standalone
   callers only; the pipeline itself never calls them.

2. markdown_table_formatter.AUDIT_FIELDS now includes
   github_link_missing / github_link_unpushed, matching its own doc
   comment and docs/DESIGN.md's Audit heuristic table (source="audit"
   routing remains the primary mechanism; this makes the documented
   fallback truthful).

Added regression tests pinning the single-evaluation guarantee: one
asserting exactly one git rev-parse --is-inside-work-tree probe fires
across a private-skip run, and a full-pipeline test asserting the
same for a complete publish (through build_publication) while also
confirming the front-matter github_url and the absence of a
github_link_* finding agree for a pushed-GitHub-repo project.

Co-Authored-By: Oz <oz-agent@warp.dev> ([`aba3349`](https://github.com/plocher/kproj/commit/aba334937015d01d81fa8af8744e404638f2cbb0))

* fix(publish): never raise from derive_github_link on subprocess timeout/OSError

subprocess_runner.run(..., check=False) only suppresses non-zero
exits; a git subprocess timeout still raised SubprocessTimeoutError
(and a missing/unusable git binary could raise OSError) straight
through PublishWorkflow.build_publication, violating the 'publish
never fails because of this optional enrichment' contract.

Every git invocation in github_link.py now catches
(SubprocessTimeoutError, OSError) and treats it the same as a
mechanical git failure - the link is omitted, publish proceeds.
Adds regression tests covering timeout and missing-binary cases at
both the derive_github_link and build_publication seams.

Co-Authored-By: Oz <oz-agent@warp.dev> ([`2497610`](https://github.com/plocher/kproj/commit/2497610a8ffe65a9570e06e14aee25f42e361c52))

### Features

* feat(publish): highlight missing/unpushed GitHub repo backing as a finding

Per the human's clarified requirement on kproj#30: the old EAGLE-era
site linked every project to its GitHub repo, so kproj should
actively surface a KiCad project's missing GitHub-repo backing
rather than silently omitting the see/fork link. New KiCad projects
don't yet consistently have git repo backing.

- github_link.py: extract shared _detect(project_dir) -> _Detection
  status taxonomy (pushed / not_a_repo / no_origin_remote /
  non_github_remote / not_pushed), reused by derive_github_link (URL)
  and the new derive_github_link_finding (advisory Finding | None).
- The advisory finding is non-fatal (severity=warning, source="audit"
  so it renders in the existing Metadata Audit table with no new
  rendering work), and distinguishes wording for 'no GitHub repo
  backing at all' (github_link_missing) vs 'backing exists but not
  confirmed pushed' (github_link_unpushed, covering no-upstream,
  ahead/diverged, and detached HEAD alike).
- PublishWorkflow.run merges the finding into the analysis right
  after read+analyze, so it surfaces on every outcome including
  private-skip.
- docs/DESIGN.md: document the two new audit rules, the
  absence-highlighting rationale, and add 'render github_url as a
  visible see/fork-on-GitHub link' to the Site-setup PR scope list
  (human ruling: front-matter-only emission accepted for this PR,
  matching the audit/drc/erc precedent; visible rendering deferred).
- BDD: every github_link.feature scenario now also asserts the
  correct advisory finding is present/absent and publish still
  succeeds.

Co-Authored-By: Oz <oz-agent@warp.dev> ([`083592a`](https://github.com/plocher/kproj/commit/083592ac8c183b157ccbdf546e2fc704225fa351))

* feat(publish): surface a see/fork-on-GitHub link when the project repo is pushed

Detects, using local git metadata only (no network calls), whether a
KiCad project directory is itself a git repo with a pushed GitHub
origin remote, and threads the derived repo-root URL onto
Publication.github_url. FrontMatterSummaryFormatter emits an optional
github_url: field alongside the existing artifact downloads when
present; non-repo / non-GitHub / unpushed projects are unaffected
(publish behavior is unchanged and never fails because of this
best-effort enrichment).

Closes #30

Co-Authored-By: Oz <oz-agent@warp.dev> ([`830154a`](https://github.com/plocher/kproj/commit/830154a6e999ccb122dce5dcf5f3d27cd68fb3c2))


## v0.1.1 (2026-07-04)

### Bug Fixes

* fix(python): drop declared floor to 3.10 to align with sibling projects

kproj previously declared ``requires-python = ">=3.11"``, out of step
with the sibling jBOM repo which declares ``>=3.10``. Per the
shared-process principle codified in
https://github.com/plocher/jBOM/blob/main/release-management/README.md,
kproj and jBOM should not evolve arbitrarily different release
processes; the declared Python floor is one of the generic pieces
that must stay coherent across the family.

Aligns kproj's declared floor and every coupled config knob:

- ``pyproject.toml``: ``requires-python`` bumped down to ``>=3.10``;
  classifiers gain 3.10 and 3.12 (in addition to 3.11); ``[tool.ruff]
  target-version`` bumped down to ``py310``; ``[tool.mypy]
  python_version`` bumped down to ``"3.10"``.
- ``.python-version``: bumped down to ``3.10`` so ``uv sync``
  resolves against the declared floor.

Two 3.11-only stdlib APIs surfaced by mypy under
``python_version = "3.10"`` are corrected in-place:

- ``src/kproj/services/change_journal.py``: switch
  ``from typing import Self`` to
  ``from typing_extensions import Self``. ``typing.Self`` was added
  in 3.11; ``typing_extensions`` provides the 3.10-compat backport
  and is already in the dep tree (transitive via pydantic).
- ``src/kproj/application/publish_workflow.py``: switch
  ``from datetime import UTC, datetime`` +
  ``datetime.now(UTC)`` to
  ``from datetime import datetime, timezone`` +
  ``datetime.now(timezone.utc)``. ``datetime.UTC`` was added in 3.11;
  ``timezone.utc`` is the equivalent that has existed since 3.2.

Lockfile regenerated by ``uv sync`` against the new floor.

Validation on the fresh 3.10 venv:

- ``ruff check`` and ``ruff format --check``: clean.
- ``mypy src``: 42 files, 0 errors.
- ``pytest``: 407 passed.
- ``behave --format progress tests/features``: 10 features / 14
  scenarios / 82 steps passed.

Refs #27

Co-Authored-By: Oz <oz-agent@warp.dev> ([`96ef01e`](https://github.com/plocher/kproj/commit/96ef01e9d217a41a6961cfc4735b6cd6ca9e5135))


## v0.1.0 (2026-07-04)

### Bug Fixes

* fix(fab): remove duplicate production_stale check; analyzer owns the policy

FabPackager carried an independent strict-comparison staleness check
(youngest production/ file vs PCB mtime, no tolerance), so real
publishes still warned even after the analyzer gained the 5-minute
happy-path tolerance - a 12-second Save/fab delta tripped the
duplicate on the first real-world publish (cpNode-Xiao-68x90).

MetadataAnalyzer._production_rules is now the single policy
implementation. The packager block is removed, FabPackager.package()
no longer takes pcb_path, and a regression test pins the packager to
emitting no production_stale finding. DESIGN audit-heuristic table and
CHANGELOG updated.

Co-Authored-By: Oz <oz-agent@warp.dev> ([`4a11180`](https://github.com/plocher/kproj/commit/4a11180ea302451d7651d95fdbc7a3402c43823f))

* fix(analyzer): loosen production_stale tolerance to 5 minutes

Empirical testing corrected the premise of the original 5-second tolerance: the PCB mtime tracks the users [Save] event, not any jbom activity. The delta between PCB and fab outputs is therefore bounded only by how long between Save and running jbom fab: seconds in the happy path (done -> jbom fab -> Save+close), minutes-to-hours in the antipattern (Save -> jbom fab -> edit -> Save, forget to re-run jbom fab).

5 minutes is wide enough to cover the happy-path Save/fab timing without alarming, tight enough to catch the antipattern. Because kproj cannot confirm freshness from mtimes alone, the finding is a warning that delegates the final call to the user (reason string unchanged). Suppressed cases still log at INFO under -v so the user sees the delta and threshold kproj is trusting.

Also add threshold-boundary unit tests (290s suppressed; 310s triggers) and correct the happy-path test framing. Gate: ruff + mypy clean, 407 pytest (+2), 14 Behave. ([`d5f3626`](https://github.com/plocher/kproj/commit/d5f3626a35a319a6d42a654d1a25687bcc4797e1))

* fix(analyzer): tolerate jbom PCB mtime touch in production_stale check

jbom fab opens the PCB via KiCad Python API, which touches the PCB file mtime as a side effect. A strict zip_mtime < pcb_mtime check therefore flagged every legitimate jbom fab output as stale (the API-touched PCB is always newer than the zip jbom just wrote in the same run). Adds a 5s tolerance via _PRODUCTION_STALE_TOLERANCE_SECONDS; also absorbs filesystem mtime rounding on SMB/Dropbox/HFS+. New unit test locks the behaviour. Gate: 394 pytest, 14 Behave, ruff + mypy clean. ([`539ee3e`](https://github.com/plocher/kproj/commit/539ee3e0514bf603ada9bd48b5bbb8133f5a8ce2))

* fix(front-matter): Hugo-safe version date; move YYYY.MM to issue_date (Phase G)

kproj emitted date: '2026.05' but Hugo reserves 'date' as a parseable date, which failed the whole hugo build (and would have failed the GitHub Pages deploy; caught by a local build). Emit Hugo's 'date' as the kproj publish timestamp (RFC3339, parseable) and the SPCoast YYYY.MM title-block value under a new custom 'issue_date' key (Hugo ignores it). Publication gains published_at (workflow computes once per run). The publish date is a volatile key in new-release detection so a content-identical re-run still resolves to noop (no-op detection is a perf optimization, not correctness). Verified: hugo --gc --minify now builds cleanly. ([`3667a96`](https://github.com/plocher/kproj/commit/3667a96d52dd0e431ca6600d6f6c3b3850ef2f79))

* fix(publisher): write Hugo assets under static/ so they are served (kproj#10)

Assets were written to a repo-root versions/ dir, but Hugo serves only static/ at the site root, so front-matter /versions/... URLs 404'd on the built site. Add a required SiteProfile.assets_dir (GENERIC=versions, HUGO=static/versions) plus asset_disk_path() mapping the fixed public /versions/ URL to the physical dir. Thread site_profile through the artifact generator; route detect_outcome and _assets_are_stale through the same mapping so writer and readers agree. Public AssetRef URLs are unchanged. Verified end-to-end: cpNode-Xiao-68x90 assets now land under static/versions/. ([`39349f2`](https://github.com/plocher/kproj/commit/39349f271d8ab4f25c605ac3ab98377c03801dc0))

* fix(publisher): classify site commits by real outcome (add/publish/republish/refresh)

The site commit prefix was chosen from file existence only, so a full re-publish of an existing version (SCH/PCB source changed -> artifacts regenerated) was mislabelled 'refresh: (metadata updated)' while the run reported 'published'. Classify four site-publish states from project_is_new/version_is_new plus the resolved outcome: add (first project publish), publish (new version), republish (existing version regenerated), refresh (metadata-only). Add a regression test for the republish case; update DESIGN and CHANGELOG. These site publish-log verbs are informational, not source-repo semver drivers. ([`da7d032`](https://github.com/plocher/kproj/commit/da7d032d86de7baa4a7b68e1f05390d3ba2df02a))

* fix(reader): populate front-matter tags from company (kproj#10)

KicadProjectReader hardcoded tags=(), emitting tags: [] against the DESIGN contract tags: [<company>, kicad]. Add _derive_tags() splitting company on '/' (multi-org boards) and appending the kicad discriminator tag; blank company yields ('kicad',). Surfaced by the first real Phase G publish (cpNode-Xiao-68x90). ([`4d0d3de`](https://github.com/plocher/kproj/commit/4d0d3deebf3f32d5af3deafe56531bd528e4f39e))

* fix(ibom): run iBOM under KiCad's bundled Python (kproj#10)

The PCM iBOM script imports pcbnew, which resolves only in KiCad's bundled interpreter, so invoking it with sys.executable failed with ModuleNotFoundError and blocked Phase G. Add find_kicad_python() (derived from the same install anchor as kicad-cli; KPROJ_KICAD_PYTHON override; macOS now, Linux/Windows follow-ups). IbomGenerator takes a required python_exe; the workflow resolves it in pre-flight (exit 2 on miss) and threads it through the artifact generator. Amend ADR 0008; de-skip the iBOM contract test; update DESIGN and CHANGELOG. ([`a98e2d0`](https://github.com/plocher/kproj/commit/a98e2d018fda9584e708b8419c75f13c58f5d6b5))

* fix(analyzer): suppress ignored DRC/ERC violations by default

KiCad-excluded ('ignored tests') violations were surfaced as findings because only the severity token was mapped. DesignAnalyzer now filters violations flagged excluded/ignored/suppressed (and the exclusion severity token) at both violation and item level, so they no longer appear in stderr or the version-page tables and do not affect the exit code. Applies to pcb drc and sch erc. ([`cf774e6`](https://github.com/plocher/kproj/commit/cf774e61a529dde9b169ef8128bba20db252c4e3))

* fix(round2): M4 DesignAnalysisError channel + M11 title-block-only refresh

Both fixes are driven by the failing tests in the preceding commit.

M4 (mechanical-vs-findings split per ADR 0004):
- src/kproj/services/design_analyzer.py: new DesignAnalysisError
  carrying origin (drc/erc) and returncode.  _raise_if_mechanical_
  failure replaces _mechanical_failure_findings: rc==0 with no JSON
  is still treated as "nothing actionable" and returns empty
  findings, but rc!=0 with no JSON raises the exception so the
  workflow can catch it on a separate channel from findings.
- src/kproj/application/publish_workflow.py: catch
  DesignAnalysisError immediately after design_analyzer.analyze()
  and return PublishResult(outcome=failed, exit_code=2).  This is
  before the change journal opens, so no site writes can leak.
  Parseable DRC/ERC violations still flow as findings unchanged.

M11 (Option B chosen: title-block-stripped content hash):
- src/kproj/common/content_hash.py (new): walks the KiCad
  S-expression paren tree (quoted-string aware) to strip every
  (title_block ...) subtree, then SHA-256s the remainder.  Handles
  nested parens inside quoted comment values.
- src/kproj/model/publication.py: new sch_content_hash /
  pcb_content_hash fields on Publication (empty-string default).
- src/kproj/formatters/front_matter_summary_formatter.py: persist
  the hashes under 'kproj_source_hashes: {sch, pcb}' when either
  is non-empty.  Included in the YAML text so detect_outcome's
  content-equality check also picks up hash changes.
- src/kproj/application/publish_workflow.py: compute both hashes
  before build_publication.  Thread onto both the preliminary
  publication (so detect_outcome sees them) and the final
  publication (so they persist on disk).  New helper
  _title_block_only_change_since_publish reads back the previously
  persisted hashes from _versions/<P>/<R>.md front-matter; when
  both match the current hashes, the M1 stale-asset escalation is
  skipped and preliminary_outcome stays at refresh/noop.  Real
  content edits still flip the hash and the M1 escalation fires
  exactly as before.

Why Option B over A/C: Option A (full-file content hash) would
regress on any legitimate whitespace-only edit; Option C (--refresh
flag) makes cheap metadata updates a manual gesture.  Option B
matches PRD Story 6's user vocabulary ("a status change is cheap")
and preserves M1's genuine-stale-asset safety net for real design
edits.  It also avoids a data-model breaking change: legacy version
files without kproj_source_hashes fall back to the M1 mtime-only
behavior (return False from _title_block_only_change_since_publish
means the caller escalates as usual).

Ruff + mypy clean; all 354 unit tests + 21 Behave scenarios pass. ([`3f0d789`](https://github.com/plocher/kproj/commit/3f0d789e972cfc7ddc0348e4afca08ddae4f870e))

* fix(workflow): merge artifact-generator diagnostics into final analysis (M6)

Pre-fix `_default_artifact_generator()` inspected only `fab_result.
skipped` and discarded every `ExportResult.diagnostics` collection.
The workflow's final `Publication` was built from the pre-artifact
`analysis` (built before generation), so artifact-stage warnings
(production_incomplete, fab_gerber_ambiguous, production_stale, and
any future producer-side warnings) never reached stderr, the
Markdown body tables, the front-matter audit/drc/erc counts, or the
exit-code calculation \u2014 violating ADR 0004's "show what is
provided" contract for producer-side diagnostics.

Contract change:
- `ArtifactGeneratorCallable` signature grows a third tuple element:
  `(images, artifacts, diagnostics)`.  `diagnostics` is the union of
  every ExportResult.diagnostics from the producers that ran.
- `_default_artifact_generator` accumulates diagnostics from all
  seven producer invocations (top/bottom render, step, sch svg/pdf,
  ibom, fab, source).
- `PublishWorkflow.run` merges producer diagnostics into a new
  `final_analysis = AnalysisInfo(findings=analysis.findings +
  producer_diagnostics)`, rebuilds the body markdown from that
  merged set, and passes it to build_publication so front-matter
  counts + Markdown tables + PublishResult.findings + stderr + exit
  code all reflect the artifact-stage warnings.

Regression test: `test_artifact_generator_diagnostics_flow_into_result`
injects a generator that returns a single production_stale finding
and asserts it appears in `PublishResult.findings`.

Test stubs updated for the new 3-tuple contract; the added tests for
BLOCKER 1 (recording generator), BLOCKER 5 (exploding generator),
and the M6 test itself all use the new signature.

Refs: docs/wave3-review.md MAJOR M6; ADR 0004. ([`5f648c9`](https://github.com/plocher/kproj/commit/5f648c90e3725f56d4dcb833f6da2cce8c15520f))

* fix(workflow): compare asset mtimes vs source to escalate stale noop to publish (M1)

docs/DESIGN.md \u00a7 New-release detection specifies that each release
asset's mtime must be compared against its source: PCB for
renders/STEP/iBOM, root schematic for SVG/PDF, project source set
for source.zip, production/ for fab.zip.  Pre-fix
`SitePublisher.detect_outcome` only checked asset EXISTENCE and
markdown content equality, so a PCB edited after the previous
publish but with a stable title-block returned 'noop', leaving
stale renders/STEP/iBOM/source/fab on the site forever.

Fix (workflow-level, per reviewer's suggested placement since
ResolvedProject is only available here):
- New `_assets_are_stale(images, artifacts, resolved, site_repo)`
  helper compares each ref's tag against a per-tag source mapping
  and returns True as soon as one asset is older than its source.
- New `_source_paths_by_tag(resolved)` returns the deterministic
  source Path per DESIGN's tag-to-source mapping.
- New `_newest_source_file(directory)` scans a directory tree,
  skipping production/ and .git so jBOM outputs and VCS metadata
  don't fool the source-archive freshness check.
- Workflow calls the helper immediately after `SitePublisher.
  detect_outcome` and escalates outcome to 'publish' when any
  asset is stale.

Also fixes a related short-circuit: `SitePublisher.publish` used
to run its own `detect_outcome` at entry.  After the M1 workflow
escalation regenerates artifacts, their fresh mtimes would let
that internal detect_outcome return 'noop' \u2014 undoing the
escalation.  Added `force_outcome` keyword to `publish()` so the
workflow's pre-computed outcome bypasses the internal detection.

Regression test: `test_stale_pcb_forces_publish_outcome` primes
the site with a first publish + commit, verifies a re-run is a
noop, bumps the PCB mtime, and asserts the third run escalates
to 'published'.

Refs: docs/wave3-review.md MAJOR M1; docs/DESIGN.md \u00a7 New-release detection. ([`97b0916`](https://github.com/plocher/kproj/commit/97b0916e991a38f5dab2e9ca9f048b7be2cbab0b))

* fix(analysis): partition findings by source for audit/drc/erc counts (M2+M3+M4)

Three coupled wave-3 review findings fixed together because they share
the same Finding.source data shape:

M2: Front-matter audit/drc/erc counts were not source-specific
    Pre-fix `_count_design_findings(ai, kind)` ignored `kind` and
    `render_audit` counted every finding, so a single DRC error
    appeared as audit.errors=1, drc.errors=1, and erc.errors=1.

M3: DRC/ERC Markdown table dropped the actual KiCad location
    DesignAnalyzer stashed the source token ("drc"/"erc") in
    `Finding.location_hint` and the KiCad location string in
    `Finding.value`.  MarkdownTableFormatter rendered the Location
    column from `location_hint`, showing "drc"/"erc" in every
    Location cell instead of the coordinate / uuid / sheet.

M4: DesignAnalyzer treated missing DRC/ERC JSON as "no findings"
    `_run_kicad_subcommand` called kicad-cli with `check=False`
    and ignored the SubprocessResult; if kicad-cli crashed and
    wrote no JSON, the analyzer silently returned () \u2014 letting a
    real mechanical failure slip through as a clean run.

Changes:
- model/finding.py: add `source: str = ""` field.  Closed taxonomy:
  "audit" (MetadataAnalyzer), "drc"/"erc" (DesignAnalyzer), "read"
  (KicadProjectReader), or empty for legacy callers.
- model/analysis_info.py: add `count_by_source(severity, sources)`
  helper for source-partitioned counting.
- services/design_analyzer.py:
  * Set `source=origin` on every emitted Finding (replacing the
    location_hint=origin overload).
  * Capture SubprocessResult; on missing JSON, dispatch through
    new `_mechanical_failure_findings()` which emits an error
    `<origin>_mechanical_failure` Finding when rc!=0 or stderr is
    non-empty, and () otherwise.
- services/metadata_analyzer.py: `dataclasses.replace(f, source="audit")`
  stamping on every audit finding before returning AnalysisInfo.
- services/kicad_project_reader.py: read-time diagnostics get
  `source="read"`.
- formatters/front_matter_summary_formatter.py:
  * audit block counts findings whose source is in {"audit", "read", ""}.
  * drc block counts only `source=="drc"`; erc only `source=="erc"`.
- formatters/markdown_table_formatter.py:
  * Section discriminator: `source` in (drc, erc) \u2192 design table;
    audit/read \u2192 audit table; legacy empty source falls back to the
    AUDIT_FIELDS heuristic.
  * DRC/ERC table: new Source column; Location column renders
    `Finding.value` (falling back to location_hint when value is
    empty) so the cell shows the real KiCad coordinate.

Regression tests:
- design_analyzer: `test_no_output_file_with_failure_emits_mechanical_finding`
- design_analyzer: existing drc/erc tests switched from
  `location_hint == origin` to `source == origin`.
- markdown formatter: `test_location_column_renders_finding_value_for_drc`,
  `test_drc_table_has_source_column_after_m3_fix`.
- front_matter formatter:
  `test_drc_error_does_not_inflate_audit_or_erc_counts`,
  `test_audit_drc_erc_counts_each_from_own_source`.

Refs: docs/wave3-review.md MAJOR M2 / M3 / M4. ([`8a6314d`](https://github.com/plocher/kproj/commit/8a6314dc4bbe59be922e39c4bf70f763db778af1))

* fix(workflow): catch SchematicExportError and iBOM FileNotFoundError (BLOCKER 5)

`SchematicExporter.export_svg` raises `SchematicExportError` when
kicad-cli produces zero SVGs or multiple root-only SVGs.  The pre-fix
workflow caught only `SubprocessFailedError`, `SubprocessTimeoutError`,
and `OSError`, so a real output-shape mismatch rolled back via
`ChangeJournal.__exit__` but then escaped `PublishWorkflow.run` and
the CLI as a Python traceback instead of becoming
`PublishResult(outcome="failed", exit_code=2)` per the DESIGN
error-handling contract.

A second class of escape: `IbomGenerator.generate` raises
`FileNotFoundError` when iBOM exits 0 but produces no HTML \u2014 also
unhandled.

Fix:
- Import `SchematicExportError` in publish_workflow.
- Catch `SchematicExportError` first (specific message:
  "schematic export failed").
- Catch bare `FileNotFoundError` second (generic artifact-stage
  message; this is the iBOM no-output path).
- Fall through to the existing `SubprocessFailedError` /
  `SubprocessTimeoutError` / `OSError` clause for everything else.

Regression test: `test_schematic_export_error_converts_to_failed_outcome`
uses an artifact-generator stub that journals one file then raises
SchematicExportError, asserts the workflow returns outcome=failed,
exit_code=2, with schematic-context in the message.

Refs: docs/wave3-review.md BLOCKER 5; docs/DESIGN.md \u00a7 SchematicExporter. ([`af1a8b8`](https://github.com/plocher/kproj/commit/af1a8b807b88f8eceb652b71a6ddef3c85efee28))

* fix(cli): render findings to stderr via StderrFormatter (BLOCKER 4)

ADR 0004 and PRD Story 5 lock that every audit/DRC/ERC finding must
surface on the user's terminal at default verbosity.  The pre-fix CLI
emitted only `result.message`; findings could set `exit_code=1` and
render into the version file while remaining invisible to the user.

Fix:
- Import `StderrFormatter` in cli.py.
- New private helper `_render_result_to_stderr(result, verbose_level)`
  formats every Finding as one stderr line (per the formatter's
  existing one-liner shape), then prints `result.message` after.
  Empty findings tuple emits no extra noise.
- `main()` calls the helper after `workflow.run()` and before
  `resolve_exit_code()`.
- `verbose_level` from the parsed request is threaded into the
  formatter for future -v wiring (tracked as a follow-up issue).

Regression tests:
- `test_main_prints_findings_to_stderr` injects a result with two
  findings and asserts both field names + reasons are in stderr.
- `test_main_emits_nothing_extra_when_findings_empty` asserts no
  added noise on stderr when findings is empty.

Refs: docs/wave3-review.md BLOCKER 4; ADR 0004; PRD Story 5. ([`35183fd`](https://github.com/plocher/kproj/commit/35183fd5b91f7f8b89bc298e22c9f127c7d460c7))

* fix(producers): journal pre-existing outputs as modify, not create (BLOCKER 3)

Every artifact producer (PcbExporter, SchematicExporter, IbomGenerator,
FabPackager, SourcePackager) called `ChangeJournal.will_create(output)`
without checking whether `output` already existed.  On re-publish of a
stale existing version, the first producer overwrote a committed asset
and a later producer could fail; rollback then unlinked the
"created" path instead of restoring the prior tracked version,
leaving the site repo missing previously published assets and
violating ADR 0005's contract that modified files are restored to the
pre-kproj state.

Fix:
- Add `ChangeJournal.register_output(path)` helper that dispatches to
  `will_modify` when `path.exists()` and `will_create` otherwise.  The
  existence check runs BEFORE the producer's atomic tempfile +
  os.replace sequence, so the original on-disk file is still observable
  at decision time.
- Route every producer's journal registration through
  `register_output`.

Regression tests:
- `test_register_output_dispatches_create_when_path_absent`
- `test_register_output_dispatches_modify_when_path_exists`
- `test_export_render_journals_as_modify_when_output_exists`
  (PcbExporter end-to-end \u2014 stand-in for the producer family since
  they all share the same register_output seam).

Refs: docs/wave3-review.md BLOCKER 3; ADR 0005. ([`61fb1a9`](https://github.com/plocher/kproj/commit/61fb1a9a401f4e315d074098b356189d690af48f))

* fix(site-publisher): stage every journaled path, not just markdown (BLOCKER 2)

`SitePublisher.publish` staged only the version-page and project-page
markdown via `git add _versions/<P>/<R>.md pages/<P>.md`.  Producers
(PcbExporter, SchematicExporter, IbomGenerator, FabPackager,
SourcePackager) register their generated assets with ChangeJournal,
but those paths never reached `git add`.  Result: kproj committed
markdown that linked to asset files left untracked in the site repo,
poisoning batch runs and violating PRD Story 1's "standard asset set"
commit/push expectation + ADR 0005's contract that
`journal.all_paths()` is the tracked publish set.

Fix:
- New `SitePublisher._collect_paths_to_stage()` deduplicates the union
  of `journal.all_paths()` plus the two markdown files (defensive
  fallback) and returns repo-relative path strings.
- `publish()` stages the full set instead of the markdown-only pair.
- Pre-existing unused-local lint warnings in tests/features/steps
  cleaned up incidentally.

Regression test: `test_publish_stages_every_journaled_path` simulates
producer side-effects (asset files on disk plus journal registration),
captures the `git add` argv, and asserts every journaled path appears.

Refs: docs/wave3-review.md BLOCKER 2; ADR 0005. ([`6f02ea5`](https://github.com/plocher/kproj/commit/6f02ea53633c789ca0abf76727591d8b61e7bc22))

* fix(workflow): thread ProjectInfo into artifact generator (BLOCKER 1)

The default artifact generator derived board_rev from
`resolved.project_file.stem` (the project basename), so a project
`demo` whose PCB rev was `1.0B` produced assets under
`versions/demo/demo/` named `demo-demo.*` \u2014 breaking the locked
<site_repo>/versions/<P>/<R>/<P>-<R>.* contract from docs/DESIGN.md
\u00a7 Release asset set and feeding the wrong rev token into FabPackager
canonical-gerber discovery.

Refactor:
- Extend `ArtifactGeneratorCallable` to take `ProjectInfo` as its
  second positional argument.
- `_default_artifact_generator` now reads `project_info.project` and
  `project_info.board_rev` and uses those for the asset directory,
  filenames, and AssetRef paths.
- Workflow call site passes the canonical `project_info` into the
  generator.
- Test stub generator updated to honor the new contract.

Add regression test: `test_artifact_generator_receives_project_info_
with_canonical_board_rev` constructs a project where the PCB rev
(`1.0B`) differs from the project basename (`demo`) and asserts the
generator is invoked with the canonical board_rev.

Refs: docs/wave3-review.md BLOCKER 1. ([`3de481b`](https://github.com/plocher/kproj/commit/3de481b267d371fc0103c385d097945c464a5c67))

* fix(kicad-install): probe KiCad 10 paths + loosen version gate to {9, 10}

The foundation's probe tables hardcoded KiCad 9 paths, so iBOM PCM
plugins installed under KiCad 10 weren't found and the iBOM contract
test was unconditionally skipped on hosts running KiCad 10 (the
current shipping major as of this commit).

- find_plugins_dir: probe KICAD10_3RD_PARTY env + KiCad 10
  macOS/Linux/Windows defaults BEFORE the v9 equivalents (newest-first).
  KICAD10 env wins over KICAD9 when both are set; a set-but-missing
  KICAD10 raises before falling through to KICAD9.
- find_kicad_cli: macOS and Linux probe paths are stable across
  major versions; Windows gains a v10 entry first.
- New SUPPORTED_KICAD_MAJORS = frozenset({9, 10}) module-level
  constant. PublishWorkflow imports it for the version-gate check
  (was: hardcoded == 9; now: in SUPPORTED_KICAD_MAJORS) so the
  locator + workflow share the same source of truth.
- ADR 0009 amended with a 'Version support' addendum documenting
  the probe order + the policy for adding future KiCad majors.

Bundled with this locator fix: a second defect the contract test
surfaced once the locator started actually finding the v10 script.

- services/ibom_generator.py: pass
  INTERACTIVE_HTML_BOM_NO_DISPLAY=1 in the subprocess env. The PCM
  iBOM script imports wxPython unconditionally otherwise, and kproj
  is non-interactive (Makefile / CI use case per ADR 0007 + ADR
  0008). New unit test pins the env var so a future refactor can't
  silently drop it.

The iBOM contract test itself remains skipped on this host because
the PCM iBOM script imports the 'pcbnew' Python module, which only
exists in KiCad's bundled Python interpreter (not kproj's vanilla
uv venv).  The skip reason was 'iBOM plugin not installed locally'
before this commit (wrong, misleading); it's now 'pcbnew module
not importable in this Python interpreter; PCM iBOM requires
KiCad's bundled Python (ADR 0008 follow-up)' (honest about why).

ADR 0008 may want to revisit using sys.executable vs locating
KiCad's bundled Python interpreter; tracked as a follow-up.

Refs: docs/adr/0009-kicad-install-locator.md Version support
addendum; docs/adr/0008-ibom-direct-script-invocation.md (existing,
referenced); docs/CHANGELOG.md Fixed - issue #3 (wave-3 follow-up).

Test counts on the rebased branch: 246 passed (up from 239), 1
skipped (down from 2 - the locator-iBOM check now runs).  The one
remaining skip is the iBOM end-to-end test, which awaits the
pcbnew-via-bundled-Python follow-up. ([`f865db4`](https://github.com/plocher/kproj/commit/f865db456ab4bcd63d9e6356e12425466e47c0d1))

### Build System

* build(foundation): package layout, dev tooling, pyproject + CHANGELOG

- Add tests/{unit,contract,features} + src/kproj/{model,services,common,application,formatters} skeleton dirs with placeholder __init__.py.
- Configure pytest, ruff, mypy in pyproject.toml; pin runtime PyYAML + types-PyYAML.
- Add .pre-commit-config.yaml (ruff + ruff-format + basic hygiene hooks).
- Seed docs/CHANGELOG.md with the issue-#1 entry under [Unreleased].

Refs #1 (slice a). ([`ff52663`](https://github.com/plocher/kproj/commit/ff52663b5b779f20af6308a4f82513efdaee6b42))

* build: track uv.lock for application/dev reproducibility

Earlier .gitignore mistakenly excluded uv.lock. kproj is an application
(distributed as a Python package, but used via its CLI not as an imported
library by downstream code), so committing uv.lock locks the dev/CI
toolchain. The published wheel still doesn't ship uv.lock so downstream
package consumers aren't affected. ([`c81447b`](https://github.com/plocher/kproj/commit/c81447b8e8180de024992daca2286f40c4478dd8))

### Features

* feat: expose package version ([`4434084`](https://github.com/plocher/kproj/commit/443408418229e99cc513381a160db566231e86f8))

* feat(cli,fab): BOM/POS discovery + verbose/debug logging plumbing

Closes #16.

CLI verbose/debug plumbing (issue #16): cli.main now calls common.logging_setup.configure(...) before workflow.run. -v -> INFO (subprocess argv via subprocess_runner, per-artifact regen decisions, BOM/POS candidate selection, production_stale tolerance suppression with mtime delta); -d -> DEBUG (INFO + subprocess return codes and captured stdout/stderr). Scoped to the kproj-namespaced logger; third-party loggers keep their pre-configure levels so -d does not turn into a firehose. Handler attachment is idempotent.

BOM/POS discovery in FabPackager: accepts modern jbom.csv/cpl.csv in addition to legacy bom.csv/pos.csv (preferred vs fallback per file kind). When both variants coexist, the closest-mtime-to-gerber-zip candidate wins (same-tool batch tie-break). Chosen file is written into fab.zip under its source basename so consumers see which toolchain produced the batch. production_incomplete diagnostic names both accepted forms.

Fixes commit 539ee3e (5s production_stale tolerance) to actually log the suppression at INFO so -v reveals why the finding was not emitted.

New tests: tests/unit/common/test_logging_setup.py (level mapping, handler isolation, idempotency, third-party guard); tests/unit/services/test_fab_packager.py (BOM/POS discovery matrix - modern, legacy, both-present tie-break either direction, missing-both diagnostic); tests/unit/services/test_metadata_analyzer.py caplog assertion for the suppression INFO log.

Gate: ruff + mypy clean; 405 pytest (was 394, +11); 14 Behave. See docs/CHANGELOG.md and docs/DESIGN.md Verbosity section. ([`e6cd3e9`](https://github.com/plocher/kproj/commit/e6cd3e9656b9b643e37fe1bb78a4468c792c1aa4))

* feat(publish): copy datasheet PDFs into the site for linking

Copy each discovered datasheet PDF to <assets_dir>/<P>/datasheets/<name> (served at /versions/<P>/datasheets/<name>), Make-style (copy if missing or source newer, mtime preserved) and journaled. New discover_datasheet_files returns source paths. 393 pytest green; ruff + mypy clean. ([`8bec227`](https://github.com/plocher/kproj/commit/8bec22702bc599b01341a1b48f2f4153c066351c))

* feat(publish): emit datasheets as _index.md front-matter data

Move discovered datasheet filenames from a Datasheets body list into a datasheets: YAML front-matter list on the project section index (README/DESCRIPTION-only body) so the Hugo site layer controls presentation. Updates _build_project_index_content unit tests. 391 pytest green; ruff + mypy clean. ([`5268741`](https://github.com/plocher/kproj/commit/526874189ff4990d9103569dcadb36551e3f2cae))

* feat: discover project-global datasheets and DESCRIPTION for section index

Recursively scan the project tree for datasheet PDFs (pruning hidden, *-backups, and production/ subtrees) and read an optional DESCRIPTION file, threading both onto Publication via build_publication. Render the DESCRIPTION prose and a '## Datasheets' name-list below the README on the project section index (content/versions/<P>/_index.md). README-only output is unchanged after normalization, so no-op detection is unaffected.

Add unit tests for project_docs and the index rendering; document the project-global docs model in DESIGN and CHANGELOG. ([`799acc0`](https://github.com/plocher/kproj/commit/799acc0f80afeba1dff9c99b162c99c7bcd1db2b))

* feat(site): emit project overview as Hugo section index (content/versions/<P>/_index.md)

Per the EAGLE model (one project page + version tabs), the per-project overview moves from a flat content/pages/<P>.md to the project section index content/versions/<P>/_index.md, so a project is a Hugo section and each version a page in it. One index per project, rewritten each publish to reflect the most-recent-publish project-global state; kproj no longer writes content/pages/<P>.md. Remove SiteProfile.pages_dir; add version_page_path() + project_index_path() helpers. SitePublisher (write/detect_outcome/staging/commit classification) and _assets_are_stale route through them. Update DESIGN, CHANGELOG, and tests. ([`7489dd9`](https://github.com/plocher/kproj/commit/7489dd99fa6e73eb0d065afd6cb24597baa76c51))

* feat(thumbnail): generate version thumbnail.png so image_path resolves (Phase G)

The version front-matter advertised image_path -> <P>-<R>.thumbnail.png but kproj never emitted it (marked Phase 6 TBD), so the URL 404'd on the built site. New ThumbnailGenerator produces <P>-<R>.thumbnail.png as part of the standard asset set, written under the profile's assets_dir and journaled for rollback. v1 grey-scale recipe is a deterministic copy of the top render (no image library); a real scaled crop (Pillow / kicad-cli pcb render --width/--height) is a tracked follow-up. Verified: cpNode-Xiao-68x90-3.0B.thumbnail.png now lands under static/versions/. ([`9f6318f`](https://github.com/plocher/kproj/commit/9f6318f263c72a082df3b89369a9abe7d6432c7d))

* feat(workflow): wire PublishWorkflow steps 5-11 end-to-end

- Step 5a: iBOM pre-flight (find_ibom_script via injectable ibom_script_locator)
- Step 5b: site-repo cleanliness check (git status --porcelain; skip on dry_run)
- Step 6: new-release detection via SitePublisher.detect_outcome()
- Step 7: open ChangeJournal (dry_run-aware)
- Step 8: artifact generation via injectable artifact_generator (default: _default_artifact_generator calling all real exporters+packagers)
- Step 9: build_publication updated with readme_md param; reads README.md from project_dir
- Step 10: SitePublisher.publish(final_pub, site_repo, no_push, dry_run)
- Step 11: ChangeJournal closed via context-manager __exit__

Injectable factories: ibom_script_locator, artifact_generator, site_publisher_factory
Pipeline exception handling: SubprocessFailedError/TimeoutError/OSError → failed
Helper functions: _read_readme, _compute_standard_asset_refs, _default_artifact_generator

Tests updated: walking-skeleton test → iBOM preflight test
Tests added: 3 new full-pipeline tests (publish, dry_run, dirty site_repo)
Total: 319 unit tests passing

Closes partial kproj#4 ([`c79a6fc`](https://github.com/plocher/kproj/commit/c79a6fc61866d139aca2c0478d85d70b16efe456))

* feat(site-publisher): full SitePublisher implementation

- detect_outcome() static method: noop/refresh/publish discrimination
  via version file existence, asset manifest presence, and content comparison
- publish() method: atomic writes (_atomic_write via tempfile+os.replace),
  ChangeJournal registration, git add/commit/push with mark_committed/pushed
- Commit message patterns: add:/publish:/refresh: prefixes per DESIGN
- dry_run=True skips all writes and git ops; no_push=True skips push
- findings threaded through into PublishResult
- Replaces NotImplementedError stub; 20 new unit tests + stubs test updated

Closes partial kproj#4 ([`4b0b531`](https://github.com/plocher/kproj/commit/4b0b531a97ed2676c3d5649fd057b35df85f0dfd))

* feat(formatters): implement StderrFormatter, MarkdownTableFormatter, FrontMatterSummaryFormatter

- StderrFormatter.format_findings renders findings as '<sev> [<field>] <subject>: <reason> (value: <val>)'
- MarkdownTableFormatter.render produces two adjacent Markdown tables (Metadata Audit + DRC/ERC Findings) using AUDIT_FIELDS discriminator set
- FrontMatterSummaryFormatter.render produces full YAML front-matter per DESIGN § Front-matter shape, including libraries: three-bucket (internal/external/ambiguous) rendering from Publication.libraries (kproj#4 wave-3)
- Publication gains readme_md: str = '' field for pages/<P>.md body content
- Replaces NotImplementedError stubs; 62 new unit tests covering all three formatters

Closes partial kproj#4 ([`2c3eb22`](https://github.com/plocher/kproj/commit/2c3eb22c76fbf6d5eaff66b58cedf103e74b8008))

* feat(libraries): restore library enumeration with internal/external/ambiguous classification

Adds src/kproj/model/library_ref.py + src/kproj/common/kicad_libraries.py
restoring the per-project library scan that landed with the original
SOURCE_README and got over-rolled-back when the manifest was dropped.

The project's version page on the SPCoast site still wants a 'this
project uses the following libraries' rendering. The scan is restored
as a standalone utility (NOT in SourcePackager, which remains pure
walk+zip), and extended with per-entry classification per user feedback
during PR#9 amendment:

- internal:   lib-table entry with ${KIPRJMOD} URI that does not escape
              the project root - the library ships inside source.zip.
- external:   any other lib-table URI (absolute path, ${KISYSMOD},
              ${KIPRJMOD}/.., URL) - consumer needs to install
              separately.
- ambiguous:  referenced by a (lib_id 'lib:name') or (footprint
              'lib:name') somewhere in the design but no matching
              lib-table entry. Surfaced as a distinct bucket so the
              site can callout 'something the design references isn't
              declared anywhere' rather than silently collapsing into
              external.

Classification precedence: lib-table entries win over bare lib_id refs
for the same library name. Output is stable-sorted by (name, source)
and reproducible for a given project_dir.

The data layer is wired today:
- model.library_ref.LibraryRef(name, source) - frozen, orderable.
- common.kicad_libraries.enumerate_libraries(project_dir) ->
  tuple[LibraryRef, ...].
- Publication.libraries: tuple[LibraryRef, ...] (new field,
  default_factory=tuple).
- PublishWorkflow.build_publication(resolved, project_info,
  analysis_info) populates the field as DESIGN step 8.

SitePublisher rendering of Publication.libraries is wave 3 (kproj#4)
territory; not modified in this PR (partial-now / complete-later split).

Docs reconciled to match: PRD Story 17 mentions the version-page
companion list + classification; DESIGN gains a new section 'Library
enumeration' documenting the utility + LibraryRef + four classification
rules + Publication.libraries; phase4-resolutions.md M7 'second
follow-up' notes the classification extension; CHANGELOG bullet
describes the restoration shape.

Refs: docs/DESIGN.md § Library enumeration; PRD Story 17;
docs/phase4-resolutions.md M7 second follow-up. ([`65c1db7`](https://github.com/plocher/kproj/commit/65c1db75623088f44bd2b1018df494f0d19bfdbb))

* feat(producers): SourcePackager (project walk + zip assembly)

Implements the fifth and final producer-pattern service for kproj#3.

- SourcePackager.package(project_dir, output, *, title, rev) walks
  project_dir per the locked Include/Exclude rules in
  docs/DESIGN.md § SourcePackager (kicad_pro/sch/pcb/sym + pretty
  contents + dru + wks + lib-tables + README/LICENSE/CHANGELOG; never
  *.kicad_prl, *.step, *.ibom.html, production/, .git/, render PNGs).
- Atomic write via sibling-tempfile + os.replace; optional
  ChangeJournal injection registers the produced source.zip for
  ADR-0005 rollback.

v1 does NOT emit a SOURCE_README.md manifest. User pushback on the
original design: KiCad's own UI surfaces missing libraries when the
project is opened, and the generic 'how to install KiCad and open a
.kicad_pro' content is bureaucratic noise. The external-library list
was the only project-specific bit and didn't justify a separate file
in the zip. PRD Story 17, DESIGN § SourcePackager, and the M7 row in
docs/phase4-resolutions.md updated to remove the SOURCE_README.md
promise; SourcePackager just packages project artifacts.

Refs: docs/DESIGN.md § SourcePackager / Release asset set;
PRD Story 17 (Replicate the design in KiCad); ADR 0005;
docs/phase4-resolutions.md M7 follow-up. ([`10dd7c1`](https://github.com/plocher/kproj/commit/10dd7c1f6de7c3028f8a2e28fd97a26623533a47))

* feat(producers): FabPackager (jBOM gerber pack discovery + assembly)

Implements the fourth producer-pattern service for kproj#3.

- FabPackager.package(production_dir, output, *, title, rev, pcb_path)
  reads jBOM's production/ outputs (per ADR 0003 - we read, don't
  invoke) and assembles <P>-<R>.fab.zip with three entries: bom.csv,
  pos.csv, gerbers.zip.
- Gerber-zip discovery prefers <production_dir>/<title>_<rev>.zip
  (jBOM's canonical naming convention). Falls back to the single *.zip
  in production_dir when the canonical name is absent; warns
  fab_gerber_ambiguous and skips when multiple non-canonical zips
  exist (refusing to guess).
- The discovered gerber zip is renamed to the normalized entry name
  'gerbers.zip' inside the fab.zip regardless of source filename, so
  the visitor-facing artifact name is stable across fabricator naming
  variations.
- Skipped semantics: ExportResult(skipped=True, path=None) returned
  when production/ is missing/empty, when bom.csv or pos.csv is
  absent, or when gerber discovery is ambiguous. Per Story 1 + ADR
  0003, the publish proceeds without the fab artifact and a warning
  Finding surfaces in the audit table.
- Staleness check: when the youngest file in production/ is older than
  the .kicad_pcb mtime, emits a production_stale warning (the fab.zip
  is still assembled - user may have forgotten 'jbom fab' after a board
  bump).
- Atomic write via sibling tempfile + os.replace; optional
  ChangeJournal injection registers the output for ADR-0005 rollback.

Refs: docs/DESIGN.md § FabPackager / Release asset set;
docs/adr/0003-jbom-separation-read-not-invoke.md;
ADR 0005 (transactional writes). ([`dee418b`](https://github.com/plocher/kproj/commit/dee418b4f53c41331d0a3231efebe6227963d118))

* feat(producers): IbomGenerator (direct script invocation per ADR 0008)

Implements the third producer-pattern service for kproj#3.

- IbomGenerator.generate(pcb_path, output_file, name_format) invokes
  generate_interactive_bom.py directly via common.subprocess_runner per
  ADR 0008: '<sys.executable> <ibom_script> --no-browser
  --no-compression --dest-dir <staging> --name-format <P>-<R>.ibom
  --extra-data-file <pcb> --dnp-field kicad_dnp --extra-fields
  MPN,Manufacturer --include-tracks <pcb>'. The kicad-cli jobset runner
  is intentionally avoided because it requires a live KiCad GUI
  process, breaking the Makefile/CI use case (ADR 0007 / ADR 0008).
- iBOM is allowed to write into a private tempfile.TemporaryDirectory;
  the produced '<staging>/<name_format>.html' file is then atomically
  moved into the caller's output_file via os.replace. This decouples
  the release-asset filename from iBOM's staging convention.
- Signature evolved from the foundation stub's (output_dir,
  name_format) to (output_file, name_format) — caller-friendly, since
  the workflow already knows the final release-asset path.
- Raises FileNotFoundError when iBOM exits 0 but produces no HTML
  (defensive against a future iBOM script regression).
- Contract test against the locally-installed iBOM PCM plugin;
  skipif-gated on find_ibom_script() succeeding.

Refs: docs/adr/0008-ibom-direct-script-invocation.md;
docs/DESIGN.md § IbomGenerator / Release asset set;
ADR 0005 (transactional writes); ADR 0009 (kicad-install locator). ([`e9db9f2`](https://github.com/plocher/kproj/commit/e9db9f2aba4609711a1ccf42080faa77994db1d1))

* feat(producers): SchematicExporter (SVG dir-discover + PDF direct)

Implements the second producer-pattern service for kproj#3.

- export_svg(root_only=True) opens a private tempfile.TemporaryDirectory
  and invokes '<cli> sch export svg --output <tempdir> --pages 1 <sch>'.
  After kicad-cli completes, discovers exactly one *.svg in the tempdir
  and atomically moves it to the final output via os.replace. The local
  kicad-cli (KiCad 10.0.1) confirms --output for 'sch export svg' is an
  OUTPUT_DIR per its --help output, so this dir-discover-and-move
  pattern is the documented design.
- export_pdf(all_sheets=True) targets --output as an OUTPUT_FILE (kicad-
  cli's 'sch export pdf' --help confirms this on the local build); the
  service uses a sibling-tempfile + os.replace pattern identical to
  PcbExporter. The all_sheets=True kwarg is wired into the signature
  but currently always emits the multi-sheet PDF per DESIGN; the kwarg
  is reserved for Phase 6+ refinement.
- SchematicExportError signals an unexpected output shape (zero SVGs,
  or >1 SVG when root_only=True). Workflow converts to Finding+rollback
  per DESIGN § SchematicExporter.
- Contract tests assert the produced SVG starts with '<?xml' or '<svg'
  and the produced PDF starts with '%PDF-'. Skipif-gated on the local
  kicad-cli.

Refs: docs/DESIGN.md § SchematicExporter / Release asset set;
ADR 0005 (transactional writes); ADR 0009 (kicad-cli locator). ([`2065425`](https://github.com/plocher/kproj/commit/206542594b4a8722c31027281dcadaf07d26229e))

* feat(producers): PcbExporter (top/bottom render + STEP)

Implements the first of five producer-pattern services for kproj#3.

- export_render(side='top'|'bottom') invokes
  '<kicad_cli> pcb render --side <side> --output <file> <pcb>' per
  docs/DESIGN.md § Release asset set.
- export_step() invokes '<kicad_cli> pcb export step --force --output
  <file> <pcb>'. The '--force' is required because we direct kicad-cli
  at a staging tempfile path before atomic replace; without it kicad-cli
  refuses to overwrite an existing path on rerun.
- Both methods write atomically: kicad-cli targets a sibling tempfile
  whose extension preserves the final output's suffix (so format
  inference still works), then os.replace lifts it into place.
- ChangeJournal injection is optional and via method parameter so each
  call site decides whether the service is rollback-scoped; pre-flight
  registration of the output (will_create before kicad-cli runs) means
  even a kicad-cli failure leaves the journal coherent.
- Tiny hand-written tests/fixtures/minimal/minimal.kicad_{pcb,sch}
  files bootstrap contract tests against the local kicad-cli; the .pcb
  ships one rectangle on Edge.Cuts, the .sch is title-block-only.
- Contract tests verify the produced PNG magic bytes + STEP
  ISO-10303-21 header; skipif-gated on a real kicad-cli.

Refs: docs/DESIGN.md § PcbExporter / Release asset set;
ADR 0005 (transactional writes); ADR 0009 (kicad-cli locator). ([`baa01af`](https://github.com/plocher/kproj/commit/baa01afc59793b4312db87f88d7956775e5527dc))

* feat(workflow): wire DESIGN steps 2-4 (read + analyze + status detection)

PublishWorkflow.run() now executes the full wave-2 pipeline boundary:

1. (wave-1) Resolve via KicadProjectReader.
2. (wave-1) Discover kicad-cli + verify major version 9.x.
3. (NEW) KicadProjectReader.read(resolved) populates ProjectInfo with
   per-field metadata precedence applied.
4. (NEW) MetadataAnalyzer + DesignAnalyzer findings merge into a
   single AnalysisInfo whose findings flow into PublishResult.
5. (NEW) Status detection short-circuits a `${COMMENT9} = private`
   project with `outcome="private-skip"` BEFORE the iBOM /
   site-cleanliness pre-flight that wave-3 will add - satisfying
   PRD Story 7's mandate that a private project never fails preflight
   on either condition.

Steps 5-11 remain stubbed and surface as `outcome="failed"` with a
clear "walking-skeleton" message until wave-3 wires the remaining
producer services + SitePublisher.

The workflow constructor now accepts a `DesignAnalyzerFactory` callable
so tests inject a fake (no real kicad-cli) and `MetadataAnalyzer` so
tests inject a no-op analyzer.  Existing wave-1 workflow tests are
rewritten to use the shared `_kicad_fixtures` builder + the silent
DesignAnalyzer factory.

`tests/unit/services/test_stubs.py` retires the MetadataAnalyzer +
DesignAnalyzer NotImplementedError assertions (they are now
implemented); the exporters / packagers / iBOM generator / site
publisher stubs remain wave-1 contracts for wave-3 to honour.

Behave: adds `private_status.feature` + step definitions exercising
PRD Story 7 end-to-end against a tmp-path-rooted fixture project, with
the workflow's kicad_version probe stubbed and a silent
DesignAnalyzer factory injected.

Tests: 9 workflow unit tests (pre-flight failures, version rejection,
private short-circuit, finding propagation, factory injection,
PublishResult instance check) + 1 new Behave scenario (private-skip).
All 179 unit + contract tests pass.

Refs: plocher/kproj#2 ([`c075c90`](https://github.com/plocher/kproj/commit/c075c90057ffc78f0f0af11e2ef7775cac8ad663))

* feat(drc-erc): DesignAnalyzer wraps kicad-cli pcb drc + sch erc

Per docs/DESIGN.md § DesignAnalyzer:

* Invokes `<kicad_cli> pcb drc --format json --severity-all --output
  <tmpfile> <pcb>` via the shared `kproj.common.subprocess_runner.run`
  (the sole subprocess entry point), parses the produced JSON, and
  deletes the tempfile before returning - no DRC/ERC JSON persists
  on disk.
* Same shape for `<kicad_cli> sch erc --format json --severity-all`.
* Returns one Finding per violation item (preserving locations) and
  one Finding per item-less violation; the rule type becomes
  `Finding.field`, the description becomes `reason`, and the location
  string becomes `value`.
* Preserves KiCad's per-violation `severity`, including `exclusion` -
  which by ADR 0004's locked policy does NOT contribute to the
  exit_code=1 findings-present rule (AnalysisInfo.has_findings stays
  False for exclusion-only sets).
* `check=False` on the subprocess call: KiCad returns non-zero when
  violations exist; that is a finding, not a mechanical failure.
* Constructor accepts an injectable runner so tests cover the JSON
  parser without touching a real kicad-cli (canned payload written by
  the fake runner).
* Tolerates ERC's `violations` / `unconnected_items` / `schematic_parity`
  top-level arrays + future shape extensions.
* Malformed JSON surfaces as a single warning Finding (not raised).

Tests: 8 unit tests covering per-item Finding emission, exclusion
preservation, argv shape (severity-all + json), empty output, missing
items array, unconnected_items array, malformed JSON, tempfile cleanup.

Refs: plocher/kproj#2 ([`0c253d0`](https://github.com/plocher/kproj/commit/0c253d05fa1b1bdf5716e25f33f135873a8c0ede))

* feat(audit): MetadataAnalyzer with 14-rule audit table

Implements the audit heuristic list from docs/DESIGN.md exactly:

1.  kicad_sch_missing (error) - adjacent .kicad_sch missing.
2.  kicad_pcb_missing (error) - adjacent .kicad_pcb missing.
3.  placeholder_value (error) - field carries a KiCad/SPCoast default
    placeholder (`${VAR}` interpolation, `DATE`, `Fab Date`,
    `Designer Name`, `Sheet Title Line N`).
4.  comment9_missing (warning) - ${COMMENT9} empty/absent on both
    sides; v1 defaults the published status to `active`.
5.  comment9_taxonomy (error) - ${COMMENT9} value outside the locked
    set {experimental, active, retired, broken, replaced-by:<X>,
    private}.
6.  sch_titleblock_empty (warning).
7.  pcb_titleblock_empty (warning).
8.  sch_pcb_disagree (warning) - non-legitimate mismatch on title,
    company, or COMMENT1 (designer).  rev/date divergence is handled
    by rev_relation + intentionally skipped here.
9.  date_format (warning) - populated date not matching YYYY.MM.
10. designer_format (warning) - populated COMMENT1 not matching the
    `[A-Z]Word [A-Z]Word` SPCoast pattern.
11. rev_relation (warning) - board_rev must extend design_rev with one
    or more uppercase letters (e.g. 3.0 -> 3.0B).
12. replaced_by_target_missing (warning) - replaced-by:<X> target dir
    absent under `~/Dropbox/KiCad/projects/` (configurable).
13. production_missing (warning) - production/ dir missing or empty.
14. production_stale (warning) - production zip older than the PCB
    mtime; user probably forgot to re-run `jbom fab`.

Per ADR 0004 ("show what is provided"), the audit never blocks; all
14 outputs flow into AnalysisInfo for stderr + Markdown-table emission.

Tests: 31 parameterised tests covering each rule's trigger + happy
paths.

Refs: plocher/kproj#2 ([`eb503e8`](https://github.com/plocher/kproj/commit/eb503e81883a0a51768cf445fc7841a4b2e6feb2))

* feat(read-services): KicadProjectReader thin-wraps jBOM + per-field precedence

Rewrites the wave-1 self-contained walking-skeleton resolver as a thin
wrapper over `jbom.application.pcb_project_loader.resolve_pcb_input`
per docs/DESIGN.md § Project resolution + ADR 0003.  Preserves the
SPCoast-specific `<basename>` fallback against
`~/Dropbox/KiCad/projects/` for inputs jBOM's CWD-relative basename
lookup cannot resolve.

Implements `read(resolved) -> (ProjectInfo, findings)` using jBOM's
`DefaultKiCadReaderService` + `SchematicReader` (jBOM 7.3.0 added
`TitleBlockMetadata.comments` mapping per plocher/jBOM#333) and
applies the locked per-field metadata precedence:

* title / company - PCB-canonical, SCH fallback.
* rev - PCB-canonical board_rev; SCH retained as design_rev.
* date - PCB-canonical when populated; SCH fallback.
* COMMENT1 (designer) - first non-empty side wins.
* COMMENT2 / COMMENT3 / COMMENT9 - SCH-canonical, PCB fallback.
* COMMENT9 `status` - empty defaults to `Status.ACTIVE` (the
  `comment9_missing` audit warning surfaces the missing value).

Exposes jBOM's `ResolvedPcbProject.text_variables` mapping on the
kproj-side `ResolvedProject` for forward compatibility.  Reader
errors come back as a single `ProjectResolutionError` carrying a
stderr-ready message.

Adds the `tests/_kicad_fixtures.py` builder that renders minimal
parseable .kicad_sch / .kicad_pcb / .kicad_pro files from a
`TitleBlockSpec` so tests can exercise the readers without shipping
multi-MB sample projects.

Pins `jbom>=7.3.0` in pyproject.toml (PR plocher/jBOM#333 merged).
Adds `tool.uv.sources` pointing at the local jBOM checkout during
development and a mypy override ignoring jBOM's missing library stubs.

Tests: 19 unit tests covering resolve + read + per-field precedence +
basename-fallback + text_variables + read-time diagnostic envelope.

Refs: plocher/kproj#2 ([`76f2e88`](https://github.com/plocher/kproj/commit/76f2e88836c183d6aa278104fe880c4e44c49797))

* feat(application): walking-skeleton PublishWorkflow + 9-service decomposition stubs

Complete the foundation walking-skeleton per docs/DESIGN.md §
Pipeline orchestration sequence (step 1) and the issue #1 scope:

- KicadProjectReader: implement resolve(.|<dir>|<basename>|<file>);
  basename lookup under projects_root (~/Dropbox/KiCad/projects by
  default). Read stub raises NotImplementedError per acceptance
  criteria — full sexp-walking metadata reader lands in a later slice.
  Surfaces ProjectResolutionError on missing/ambiguous .kicad_pro and
  on missing adjacent .kicad_pcb / root .kicad_sch.
- PublishWorkflow.run(): real pre-flight (resolve + kicad-cli
  discovery via config override OR find_kicad_cli + major-version 9.x
  enforcement). Prints 'kproj: kicad-cli <v.v.v> at <path>' to stderr
  on success, returns failed/2 with a clear message indicating the
  downstream pipeline is not yet implemented.
- Service stubs (raise NotImplementedError): MetadataAnalyzer,
  DesignAnalyzer, PcbExporter, SchematicExporter, IbomGenerator,
  FabPackager, SourcePackager, SitePublisher.
- Formatter stubs: StderrFormatter, MarkdownTableFormatter,
  FrontMatterSummaryFormatter.
- services/__init__.py and formatters/__init__.py expose stable
  symbols; SitePublisher uses TYPE_CHECKING to avoid a circular
  import with application.publish_workflow.

Tests:
- tests/unit/services/test_kicad_project_reader.py: 12 cases covering
  all four resolve() inputs, the four error paths, hierarchical
  schematic discovery, and read() stub behaviour.
- tests/unit/application/test_publish_workflow.py: 5 cases covering
  pre-flight outcomes (project miss, kicad-cli miss, wrong major
  version, success-but-downstream-stub, configured-but-missing).
- tests/unit/services/test_stubs.py + tests/unit/formatters/test_stubs.py:
  pin the NotImplementedError contract for every downstream service +
  formatter.
- tests/features/preflight.feature + steps: minimal Behave coverage
  for the walking-skeleton preflight (docs/DESIGN.md § Testing
  strategy 'Behave Gherkin features').

131 unit tests + 1 contract test (3 KiCad-locator checks pass on a
machine with KiCad installed; iBOM contract is skipped when not
present) + 1 Behave scenario.

Refs #1 (slice i; completes acceptance for issue #1). ([`9f9851a`](https://github.com/plocher/kproj/commit/9f9851a063ff13ba55ce35f025e3d697c4f0eca3))

* feat(services): domain-agnostic ZipArchiver returning ExportResult

Add src/kproj/services/zip_archiver.py per docs/GLOSSARY.md §
ZipArchiver and docs/DESIGN.md § Per-service contracts > ZipArchiver:

- ZipArchiver().archive(source_paths, output, *, root) -> ExportResult.
- Directories in source_paths are walked recursively; entries are
  named relative to root for stable, reproducible zips.
- Validates every source is at or beneath root at intake.
- Creates the output's parent dir if missing; uses ZIP_DEFLATED for
  size.
- command=None on the returned ExportResult since no subprocess is
  invoked. elapsed_seconds is wall-clock for the write.

6 unit tests under tests/unit/services/test_zip_archiver.py cover
the success path, content preservation, parent-dir creation,
outside-root rejection, and the empty-source edge case.

Refs #1 (slice h). ([`8e2fca8`](https://github.com/plocher/kproj/commit/8e2fca88ffe5088a78727b57c26df755011479c0))

* feat(services): ChangeJournal transactional write tracker

Add src/kproj/services/change_journal.py per ADR 0005:

- ChangeJournal(site_repo, *, dry_run=False) context manager.
- will_create(path) / will_modify(path) record intent; reject paths
  outside the site repo at intake (validation at the boundary).
- mark_committed() / mark_pushed() track git progress so rollback can
  reset HEAD^ only when the commit lands but the push fails.
- rollback(): unlink created files, restore modified files via
  'git -C site_repo checkout -- <relative paths>', reset HEAD^ when
  committed but not pushed.
- dry_run=True records intent but skips all git invocations.
- Routes git through the shared subprocess_runner so timeouts and
  error translation are uniform.

10 unit tests under tests/unit/services/test_change_journal.py cover
the context-manager protocol, intake validation, rollback paths
(unlink / checkout / reset HEAD^), the dry-run no-git contract, and
all_paths() deduplication.

Refs #1 (slice g). ([`eee19f5`](https://github.com/plocher/kproj/commit/eee19f515ea8fc9dbfac66784e8b4b376dfb2ceb))

* feat(common): shared subprocess_runner with timeout + error translation

Add src/kproj/common/subprocess_runner.py per docs/DESIGN.md §
Subprocess runner — the single sanctioned subprocess.run wrapper:

- run(command, *, timeout, check, cwd, env) -> SubprocessResult.
- SubprocessResult (frozen): command + returncode + stdout + stderr
  + elapsed_seconds.
- SubprocessTimeoutError: carries command + timeout for surfacing.
- SubprocessFailedError: carries command + returncode + stdout +
  stderr; raised on non-zero return when check=True (default).
- DEFAULT_KICAD_TIMEOUT = 120s, DEFAULT_GIT_TIMEOUT = 30s constants.
- KeyboardInterrupt propagates unchanged.

7 unit tests under tests/unit/common/test_subprocess_runner.py
cover the success / failure / timeout / check=False / cwd+env
forwarding paths via monkeypatched subprocess.run.

Refs #1 (slice f). ([`bb245d4`](https://github.com/plocher/kproj/commit/bb245d4af98443011f38a821348c1af4f4c84844))

* feat(common): kicad_install locator with platform probes + contract test

Add src/kproj/common/kicad_install.py per ADR 0009:

- find_kicad_cli(): KPROJ_KICAD_CLI > platform default tuple
  (macOS / Linux / Windows) > shutil.which fallback.
- find_plugins_dir(): KICAD9_3RD_PARTY > per-platform default.
- find_ibom_script(): plugins_dir/plugins/org_openscope.../
  generate_interactive_bom.py with an iBOM-specific clear error
  message per ADR 0008.
- kicad_version(kicad_cli): parses (major, minor, patch) from
  --version stdout. Tolerates 'KiCad 9.1.0' / 'kicad-cli version
  8.0.2' prefixes.
- KicadNotFoundError: domain error type for any miss.

Platform default tables exposed as module-level tuples so unit tests
can monkeypatch them without touching real KiCad install state.

16 unit tests under tests/unit/common/test_kicad_install.py cover
all four locator functions + the error paths.

Add tests/contract/test_kicad_install_locator.py: real-tool contract
test gated on @pytest.mark.skipif when local KiCad is missing
(docs/DESIGN.md § Contract tests).

Refs #1 (slice e). ([`36f32de`](https://github.com/plocher/kproj/commit/36f32de63a4df393fc8f32be73354ae6d7bacab0))

* feat(cli): argparse surface + exit-code mapping + PublishWorkflow stub

Wire up the v1 CLI per docs/DESIGN.md § CLI surface mechanics and
§ Exit code mapping; argparse + sys.exit confined to cli.py per
ADR 0006.

- parse_args(): kproj [<project>] [--site-repo PATH] [--dry-run]
  [--no-push] [-v] [-d]. -v is a count flag, defaults all set.
- build_request(): Namespace + env + yaml_path -> PublishRequest,
  with ConfigOverrides populated only for explicitly-provided flags
  so the config-layer precedence still falls through correctly.
- resolve_exit_code(): outcome+findings -> 0/1/2 per DESIGN's table
  (exclusion findings intentionally do NOT trigger code 1).
- main(): glue; prints PublishResult.message to stderr and returns
  the resolved exit code.
- application/publish_workflow.py: PublishRequest / PublishResult /
  Outcome Literal + a walking-skeleton PublishWorkflow that returns
  failed/2 with a clear message (full pre-flight lands in slice i).
- application/__init__.py exports the new symbols.

17 new unit tests in tests/unit/test_cli.py cover the argparse
surface, override-propagation semantics, the parametrised exit-code
mapping, and the main() delegation path via a stubbed workflow.

Refs #1 (slice d). ([`2d2aa51`](https://github.com/plocher/kproj/commit/2d2aa5128700f2c7771dc051569424559849698f))

* feat(config): config layer with CLI > env > yaml > default precedence

Add src/kproj/config.py per docs/DESIGN.md § Configuration layer:

- ConfigOverrides (frozen): the CLI-derived shape carrying optional
  --site-repo / --no-push / --kicad-cli overrides. argparse stays
  out of this module per ADR 0006.
- KprojConfig (frozen): the resolved runtime config (site_repo,
  no_push, kicad_cli).
- load_config(overrides, env, yaml_path) -> KprojConfig: applies the
  documented four-tier precedence and forward-compatibly ignores
  unknown yaml keys. Rejects non-mapping yaml documents.
- Module-level DEFAULT_SITE_REPO / DEFAULT_NO_PUSH constants matching
  ADR 0007's locked fallback.

16 unit tests under tests/unit/test_config.py cover the precedence
chain (including parametrised KPROJ_NO_PUSH boolean parsing) and
the error case for malformed yaml.

Refs #1 (slice c). ([`d5344d1`](https://github.com/plocher/kproj/commit/d5344d1e5fa8b082d9b9e4f27b19f4e67f7979b8))

* feat(model): frozen domain dataclasses (Severity, Finding, ProjectInfo, ...)

Add the seven foundation value objects per docs/GLOSSARY.md and
docs/DESIGN.md:

- Severity (error/warning/exclusion enum, totally ordered).
- Finding (immutable; severity, field, value, reason, project,
  location_hint).
- ProjectInfo + Status (closed v1 taxonomy + replaced_by_target).
- AnalysisInfo (helpers: count, has_findings, merged_with).
- Publication + AssetRef (frozen, asset_refs split into images/artifacts).
- ResolvedProject (kproj-owned wrapper around jBOM's resolution).
- ExportResult (uniform return for side-effecting services).

All dataclasses are frozen per the user hygiene rule. Tests cover
each module with 28 unit tests under tests/unit/model/.

Refs #1 (slice b). ([`69e3d2a`](https://github.com/plocher/kproj/commit/69e3d2acdd661cac37e9d685ffb3d29911a56785))

### Refactoring

* refactor(publish): delegate change-detection to git; Make-style artifact regen

Remove the bespoke content-comparison no-op machinery (SitePublisher.detect_outcome, _strip_volatile, force_outcome). The workflow now regenerates artifacts only when a KiCad source is newer than its on-disk artifact (Make-style via _needs_regeneration), preserves the version page Hugo date so unchanged runs are byte-identical, and lets git diff --cached decide whether to commit (empty means no-op). Commit-prefix verbs are derived from the staged path set.

Git-dependent behaviour is validated interactively; obsolete detect_outcome/outcome/commit-message unit tests and the Story 13 no-op Behave scenario are removed; the Behave harness stubs _git_staged_names so pipeline scenarios still exercise the commit path.

Docs: PRD Stories 6 + 13, DESIGN New-release detection, CHANGELOG. Gate: ruff + mypy clean; 391 pytest; 14 Behave scenarios. ([`f9ebf01`](https://github.com/plocher/kproj/commit/f9ebf018a172be82f2729c461f9e24021b9b731e))

* refactor(config): introduce SiteProfile abstraction; split GENERIC (test anchor) from HUGO (backend)

Phase F of the SPCoast site Jekyll -> Hugo migration.  The production
site was cut over to Hugo in the companion PR on SPCoast/SPCoast.github.io
(orphan branch main, archive at tag archive/jekyll-final).  This PR
updates kproj to emit content for the new backend while keeping tests
decoupled from any specific site shape - mirroring jBOM's ADR 0008
generic-vs-named-profile pattern.

New abstraction (src/kproj/config.py):

- SiteProfile dataclass captures the backend-specific decisions:
  versions_dir, pages_dir, layout_field (None omits front-matter
  layout: key entirely; string emits it).

Two built-in profiles ship:

- GENERIC_SITE_PROFILE - abstract test anchor.  Values are backend-
  neutral: versions_dir='versions', pages_dir='pages', layout_field=None.
  No 'content/' prefix (Hugo), no '_' prefix (Jekyll), no layout.  It is
  NOT intended for deployment against a live site; it exists so Behave
  scenarios and unit-test fixtures can validate the abstraction contract
  without pinning to any real backend's layout.
- HUGO_SITE_PROFILE - concrete Hugo backend.  Fills in the structural
  bones a Hugo GitHub Pages deployment expects: content/versions/,
  content/pages/, layout_field=None (Hugo picks by section).  Selected
  by load_config for production.

Default resolution:

- KprojConfig.site_profile dataclass default = GENERIC_SITE_PROFILE.
  Test fixtures that build KprojConfig directly (bypassing load_config)
  inherit the safe test anchor without needing to know about backends.
- load_config (the production entry point) selects HUGO_SITE_PROFILE
  in v1 via a new _resolve_site_profile().  A future --profile /
  --type / --theme CLI flag + env + yaml precedence will grow that
  resolver, matching the existing site_repo / no_push / kicad_cli
  resolvers.  The --site-repo flag remains reserved for the on-disk
  repo path; the two concerns (repo location, backend shape) are
  orthogonal.

Consumer surface:

- SitePublisher.publish + .detect_outcome accept an optional
  site_profile keyword (default: GENERIC_SITE_PROFILE).  Target paths
  become <site_repo>/<profile.versions_dir>/<P>/<R>.md and
  <site_repo>/<profile.pages_dir>/<P>.md.  PublishWorkflow threads
  request.config.site_profile through to both call sites.
- FrontMatterSummaryFormatter.render takes a site_profile and emits
  layout: <value> only when profile.layout_field is not None.

Tests:

- Behave scenarios and unit-test fixtures reference
  GENERIC_SITE_PROFILE.versions_dir / .pages_dir instead of literal
  string paths - so scenarios validate the abstraction contract, not
  a specific backend's layout.
- New TestLayoutFieldProfileSensitivity covers the layout: emission
  matrix (GENERIC omits, Jekyll-shaped profile emits).
- New TestSiteProfileContract + TestSiteProfileResolution assert the
  two-profile split: GENERIC is backend-neutral, HUGO carries Hugo's
  content/ prefix, load_config selects HUGO in v1.

Docs:

- docs/DESIGN.md: new SS SiteProfile abstraction (with two-profile
  rationale + default-resolution + consumer contract).  Pipeline +
  new-release sections use <profile.versions_dir> / <profile.pages_dir>
  placeholders instead of literal paths.  Front-matter shape example
  comments out Jekyll's layout: eagle.
- docs/PRD.md Stories 1 + 13: path placeholders with Hugo defaults
  called out.
- docs/GLOSSARY.md version entry: references profile-driven path.
- docs/CHANGELOG.md entry.

Validation: 364 pytest passed / 1 skipped (iBOM/pcbnew, kproj#10);
15 Behave scenarios / 87 steps; ruff + mypy strict clean. ([`9941c66`](https://github.com/plocher/kproj/commit/9941c66bf68e988195a48f3090eae589e84d6153))

* refactor(config): single canonical site-repo default; generic $SITE_REPO in docs

Site-repo path was duplicated across ~9 places (config.py, DESIGN, ADR 0007,
Makefile template, docstrings). Moving the checkout to a new location surfaced
the DRY violation.

Changes:
- src/kproj/config.py: DEFAULT_SITE_REPO now points at the new
  ~/Dropbox/workspace/SPCoast.github.io location (was ~/Dropbox/eagle/...);
  docstring calls it out as the single source of truth.
- docs/DESIGN.md: replaced literal path with $SITE_REPO in the ~/.kproj.yaml
  example + the Front-matter shape prose; fallback reference in the
  Configuration layer code sample points at kproj.config.DEFAULT_SITE_REPO.
- docs/adr/0007-local-cli-v1-ci-deferred.md: hardcoded-fallback wording now
  cites src/kproj/config.py::DEFAULT_SITE_REPO instead of literalizing.
- templates/Makefile.kicad: removed SPCoast-specific default (template is
  useless for non-SPCoast users with a fixed default). Kept KPROJ_SITE_REPO
  fallback + commented-out placeholder line users can uncomment + edit.
  Genericized the header comment + help output.

Not touched (historical review artifacts, preserved verbatim):
- docs/phase4-review.md
- docs/phase1/site-platform-assessment.md

The 'SPCoast' name itself stays in prose where it references the domain
(kproj is a SPCoast tool per Phase 0 scope contract) — the DRY concern was
about the filesystem path literal, not the domain name.

Test suite: 354 passed / 1 skipped (iBOM/pcbnew) / 15 Behave scenarios /
87 steps. ruff + mypy strict clean. ([`a5d12c3`](https://github.com/plocher/kproj/commit/a5d12c3de1d84d4ea77ece1cd5d64d3a26963174))

* refactor(model): relocate PublishRequest/PublishResult + compute_exit_code

Move `PublishRequest` and `PublishResult` from
`application/publish_workflow.py` to dedicated modules under
`src/kproj/model/` so services and the workflow can share them without
the `TYPE_CHECKING` gymnastics `services/site_publisher.py` relied on
in wave-1.

Add `compute_exit_code(outcome, findings)` + `PublishResult.build(...)`
in the new model layer.  The workflow now populates
`PublishResult.exit_code` authoritatively, addressing the wave-1
carry-forward about the previously-dead field; `cli.py` delegates to
the same helper so the two sources of truth agree by construction.

Also adds the `RawTitleBlock` snapshot dataclass + new `raw_sch` /
`raw_pcb` fields on `ProjectInfo` so the upcoming
`MetadataAnalyzer` audit can compare SCH vs PCB without re-reading
the files.

Refs: plocher/kproj#2 ([`16c0f57`](https://github.com/plocher/kproj/commit/16c0f57145e34daa3be91bc789b69ff8bc2a09f4))

### Unknown

* Merge pull request #25 from plocher/feat/kproj-packaging-normalization

Normalize kproj packaging layout ([`89c7b56`](https://github.com/plocher/kproj/commit/89c7b56d0fcb2dc090a4958304f375f4e29825a4))

* Merge pull request #24 from plocher/fix/production-stale-tolerance

fix(analyzer,fab): production_stale tolerance + BOM/POS discovery + verbose/debug logging ([`28959b6`](https://github.com/plocher/kproj/commit/28959b6958ba5078fecdf4962c63add8fa341cb0))

* Merge pull request #23 from plocher/docs/jbom-license-erratum

docs: erratum — jBOM license is MIT, not AGPL ([`21f56ba`](https://github.com/plocher/kproj/commit/21f56ba40fc3be7b28705167fda05f4f5e6b45e0))

* Merge branch 'review/wave-3' ([`4347df7`](https://github.com/plocher/kproj/commit/4347df72850cb56548b186ec4a2ace43b98d33c7))

* Merge pull request #22 from plocher/fix/phase-g-validation

Phase G: git-detected publishing, datasheets, and Hugo site validation ([`b5a99b9`](https://github.com/plocher/kproj/commit/b5a99b9edd4d49acc19791b14b514642f00f5cca))

* Merge pull request #21 from plocher/refactor/site-profile-abstraction

refactor(config): introduce SiteProfile abstraction; Hugo path defaults ([`874cb10`](https://github.com/plocher/kproj/commit/874cb10386e092fcf3d3a21a3942d94069a50959))

* Merge pull request #19 from plocher/chore/site-repo-canonical

refactor(config): single canonical site-repo default; generic $SITE_REPO in docs ([`8eb73de`](https://github.com/plocher/kproj/commit/8eb73defde0513bc2127b56d9d2dd8057a6657ec))

* Merge pull request #11 from plocher/feat/issue-4-publishing

feat(publishing): SitePublisher + workflow orchestration + Behave features (#4) ([`619e635`](https://github.com/plocher/kproj/commit/619e635bc6ebb1ed43cbc43990782de547fbb01b))

* revert(m11): rip out content-hash machinery (premature optimization)

The Wave-3 M11 round-2 title-block-stripped content-hash caching was
implemented to deliver PRD Story 6's "cheap refresh" promise. Post-round-2
architecture review surfaced two cascading concerns:

1. Site-repo YAML as public API surface. Persisting kproj_source_hashes:
   into _versions/<P>/<R>.md front-matter turned the site repo into a
   bidirectional interface between past-kproj-runs and future-kproj-runs,
   coupling kproj's correctness to a repo it doesn't own. Breaks under
   hand-edits, cross-repo migrations (e.g. Jekyll -> Flutter), backups.
   Violates ADR 0002's publisher-boundary framing.

2. Premature optimization without baseline data. "Cheap" and
   "metadata" were unmeasured qualitative claims. We don't know how long
   a full publish takes, don't know where time is spent, and don't know
   how frequent metadata-only edits will be in the SPCoast workflow.
   Building state-persistence machinery to skip a specific artifact-regen
   path is unjustified without profile data.

Concrete changes:
- Delete src/kproj/common/content_hash.py.
- Remove Publication.sch_content_hash + pcb_content_hash fields.
- Remove kproj_source_hashes: YAML emission from FrontMatterSummaryFormatter.
- Remove _title_block_only_change_since_publish + _read_stored_source_hashes
  helpers + their invocation in PublishWorkflow.run step 6. Asset staleness
  now unconditionally escalates to full publish (M1 behavior).
- Remove sch_content_hash / pcb_content_hash parameters from
  PublishWorkflow.build_publication.
- Delete tests/features/metadata_refresh.feature (6 scenarios; active->private
  covered by private_status.feature).
- Remove M11-specific step definitions from publish_steps.py (change_comment9,
  change_comment9_empty, change_status_active alias, frontmatter_status_matches,
  assets_not_regenerated, git_commit_prefix, no_commit_invoked_second_run) +
  the baseline_asset_mtimes snapshot in step_given_previously_published.
- Amend PRD Story 6 to document v1's honest behavior: any SCH edit triggers
  a full publish; smart-refresh deferred pending profile data.
- Append post-round-2 rip-out section to docs/phase4-resolutions.md.
- Update docs/CHANGELOG.md M11 entry.

Follow-up issues to be filed on plocher/kproj:
- Profile hooks: per-step wall-clock instrumentation. Produces baseline data.
- Smart refresh: gated on profile evidence that metadata edits are a real
  hotspot.

Test suite post-rip-out: 354 unit passed / 1 skipped (iBOM/pcbnew, tracked by
kproj#10). 10 Behave features / 15 scenarios / 87 steps pass. ruff + mypy
strict clean.

Lesson recorded in phase4-resolutions.md: any v1 code that exists to make
things faster (versus correct/safe) should have a measurement anchor before
landing. State kproj needs for its own correctness should live in storage
kproj owns, not storage kproj writes to as a side effect. ([`aa6c6b8`](https://github.com/plocher/kproj/commit/aa6c6b85703796f100a1d55c46b2aa7dfc18fc6b))

* Merge pull request #9 from plocher/feat/issue-3-producers

feat(producers): PcbExporter + SchematicExporter + IbomGenerator + FabPackager + SourcePackager (#3) ([`a44222e`](https://github.com/plocher/kproj/commit/a44222e532d19c70ccb33c56f8dbc4582f783889))

* Merge pull request #8 from plocher/feat/issue-2-read-services

feat(read-services): KicadProjectReader + MetadataAnalyzer + DesignAnalyzer (#2) ([`58aa65f`](https://github.com/plocher/kproj/commit/58aa65fd9a8fe42dc3d8f3fd193b27ce7a92096e))

* Merge pull request #7 from plocher/feat/issue-1-foundation

feat(foundation): bootstrap kproj v1 (#1) ([`da628d3`](https://github.com/plocher/kproj/commit/da628d31da4ee432de0227e6cad25f34d7c969a0))

* Merge pull request #6 from plocher/feat/phase-3-prd

docs: Phase 3 + Phase 4 deliverables (PRD + DESIGN + ADRs + GLOSSARY + review + resolutions) ([`47cbc1c`](https://github.com/plocher/kproj/commit/47cbc1ce5d2e8c2e93a226a1c2691e9c51fdb3d3))
