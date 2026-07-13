# WARP.md - Agent Guide

This file provides actionable guidance to WARP (warp.dev) agents when working in this repository.

## What this repo is

`kproj` — KiCad project publisher for the SPCoast site. One invocation publishes a point-in-time snapshot of a KiCad project (renders, schematics, iBOM, fab/source archives) as a version entry.

## Toolchain

- Python ≥3.11; `uv` for environment + dependency management (`uv sync`, `uv run`)
- `pytest` + `behave` for testing; `ruff` + `mypy` for lint/type-check; `pre-commit` hooks configured
- Run tests before committing: `uv run python -m pytest tests/ -q`

## Vocabulary

Use the operational definitions in `CONTEXT.md` (terminology-only; imports document-library terms from SPCoast-inventory and jBOM by reference). Don't drift to the synonyms it explicitly avoids.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues for this repository (via `gh`). See `docs/agents/issue-tracker.md`.

### Triage labels

Triage uses the default canonical label vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Domain docs are single-context: root `CONTEXT.md`, ADRs in `docs/adr/`, implementation specs in `docs/DESIGN.md`, requirements in `docs/PRD.md`. See `docs/agents/domain.md`.
