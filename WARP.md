# WARP.md - Agent Guide

This file provides actionable guidance to WARP (warp.dev) agents when working in this repository.

## What this repo is

`kproj` — KiCad project publisher for the SPCoast site. One invocation publishes a point-in-time snapshot of a KiCad project (renders, schematics, iBOM, fab/source archives) as a version entry.

## Toolchain

- Python ≥3.11; `uv` for environment + dependency management (`uv sync`, `uv run`)
- `pytest` + `behave` for testing; `ruff` + `mypy` for lint/type-check; `pre-commit` hooks configured
- Run tests before committing: `uv run python -m pytest tests/ -q`

## Local dev testing vs. a release install

A released `kproj` (PyPI/Homebrew/pip) and a dev/editable checkout (`uv run kproj` from this repo) can both be present on the same machine, and both write into the *same* shared external state: the SPCoast site repo's git history, and the globally-installed iBOM plugin's `web/` customization directory (see `kproj.services.ibom_generator`). Nothing warns you if a command resolved to a different install than you expected.

- `pyenv`'s per-directory `.python-version` pinning plus its shell-init `PATH` prepending (`~/.pyenv/shims`) can silently change which `kproj` a bare `kproj` invocation resolves to, depending on the current working directory - with no visible indication which one ran.
- To reliably exercise dev changes, always invoke `uv run kproj ...` from this repo's checkout. Never rely on a bare `kproj` on `PATH` resolving predictably across directories.
- When testing a dev build against the real SPCoast site repo, pass `--watermark <unique-tag>` (e.g. a session id or short description). It gets stamped into the generated iBOM page, the front-matter `kproj_publish_context`, and the site-repo commit message, alongside the auto-detected kproj version/install type (`kproj.common.install_info`) - so that run's output is unmistakably a dev/test publish, not a normal production one. A subsequent normal production publish naturally supersedes it; no cleanup step is needed.

## Vocabulary

Use the operational definitions in `CONTEXT.md` (terminology-only; imports document-library terms from SPCoast-inventory and jBOM by reference). Don't drift to the synonyms it explicitly avoids.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for this repository (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the default canonical label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Domain docs are single-context: root `CONTEXT.md`, ADRs in `docs/adr/`, implementation specs in `docs/DESIGN.md`, requirements in `docs/PRD.md`. See `docs/agents/domain.md`.
