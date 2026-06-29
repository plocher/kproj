# ADR 0005: WriteTracker for Transactional Site-Repo Writes
Date: 2026-06-29
Status: Accepted

## Context

kproj's publish step writes multiple files to the local SPCoast site repo checkout:
- `_versions/<P>/<R>.md` — the version markdown.
- `versions/<P>/<R>/<P>-<R>.*` — multiple asset files (renders, sch.svg, sch.pdf, ibom.html, fab.zip, source.zip, step, thumbnail).
- `pages/<P>.md` — the per-project aggregator (always rewritten).

After all writes, kproj runs `git add` / `git commit` / `git push` against the site repo.

Failure modes possible mid-pipeline:
- A `kicad-cli` subprocess errors after a successful render of one side.
- The iBOM plugin fails to load.
- jBOM `production/` is missing (caught by audit, but a misconfiguration could still trigger mid-pipeline).
- A file write fails (disk full, permissions).
- `git push` is rejected (e.g. someone else pushed first).

Without cleanup, mid-pipeline failure leaves the site repo with stray uncommitted files and possibly partial commits. For **corpus-wide batch runs** (`for project in projects/*/; do kproj $project; done`), a single mid-pipeline failure poisons every subsequent kproj invocation — `git status` is dirty before the next kproj even starts. Resolving this requires the user to `git checkout` / `git clean` between projects, which defeats the point of a batch loop.

## Decision

kproj v1 uses a **WriteTracker** Python context manager that records every file kproj creates or modifies in the site repo. On any exception during the publish step, the tracker rolls back:

```python path=null start=null
class WriteTracker:
    def __init__(self, site_repo: Path): ...
    def will_create(self, path: Path) -> None: ...
    def will_modify(self, path: Path) -> None: ...
    def rollback(self) -> None:
        # Delete created files
        for path in self.created:
            path.unlink(missing_ok=True)
        # Restore modified files from HEAD
        if self.modified:
            paths = [str(p.relative_to(self.site_repo)) for p in self.modified]
            subprocess.run(["git", "-C", str(self.site_repo), "checkout", "--", *paths],
                           check=True)
        # If commit happened but push failed, undo the commit
        if self.committed_but_not_pushed:
            subprocess.run(["git", "-C", str(self.site_repo), "reset", "--hard", "HEAD^"],
                           check=True)
```

Usage:

```python path=null start=null
tracker = WriteTracker(site_repo)
try:
    write_version_md(tracker, ...)
    write_assets(tracker, ...)
    write_aggregator(tracker, ...)
    git_add_all(site_repo, tracker.all_paths())
    git_commit(site_repo, commit_message)
    tracker.mark_committed()
    git_push(site_repo)
    tracker.mark_pushed()
except Exception:
    tracker.rollback()
    raise
```

### Guarantees

- Any exception during the publish step → the site repo working tree is restored to its pre-kproj state.
- If `git commit` succeeded but `git push` failed, the commit is undone (`git reset --hard HEAD^`).
- If rollback itself fails (e.g. `git checkout` errors), kproj logs to stderr with manual-recovery instructions and exits with code 2.

### Atomic per-file writes

Each individual file write uses `tempfile` + `os.replace()`, so partial writes never appear in `git status` even during normal (non-failing) operation. The tracker handles cross-file atomicity (rollback on group failure); per-file atomicity is handled by `os.replace`.

### Out of scope for the tracker

- The kicad-cli subprocesses that produce render PNGs, schematic SVG/PDF, STEP — these write directly to `<site_repo>/versions/<P>/<R>/` via their own `--output` flags. The tracker records each output path it requests, so if the subprocess succeeds the path is in `tracker.created`; if it errors mid-write, the file may exist partially. Acceptable because the subsequent git checkout will resolve it.
- jBOM's intermediate (we don't invoke jBOM; see ADR 0003).
- Project-repo writes — kproj v1 never writes to project repos (ADR 0002).

## Consequences

### Positive

- Batch usage is safe. One failed project doesn't pollute subsequent projects in the loop.
- The site repo working tree is either "fully kproj-committed" or "fully clean" — no third state to clean up by hand.
- Implementation complexity is concentrated in one helper class; per-step modules just call `tracker.will_create(path)` before writing.

### Tradeoffs

- Every write must go through the tracker. Forgetting to register a write means it survives rollback (leaving a stray file). Mitigation: code review + the tracker's `all_paths()` method is what gets passed to `git add`, so an unregistered file is also un-added and shows up as a stray in `git status` (visible).
- Rollback latency on failure (negligible — a few `os.unlink` + one `git checkout` call).

### Reversibility

The tracker is an implementation detail of the publish step. Replacing it with a different strategy (e.g. git worktree per kproj run + atomic merge) is mechanical. The decision here is "v1 must have transactional writes"; the WriteTracker class shape is the simplest implementation that satisfies that.
