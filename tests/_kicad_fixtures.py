"""Minimal in-memory KiCad project fixtures for kproj unit + Behave tests.

A real KiCad project on disk is a heavyweight thing (lib_symbols stanzas,
embedded fonts, footprints).  kproj's read pipeline only cares about
``(title_block ...)`` content plus the file existing as a parsable
S-expression, so these helpers build just enough wrapper bytes around a
caller-supplied title-block to exercise the jBOM readers.

The fixtures are deliberately not "valid for KiCad to open" - they're
"valid enough for the readers we use" - which keeps tests fast and
avoids shipping multi-megabyte sample projects in the repo.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class TitleBlockSpec:
    """Title-block contents to render into a fixture KiCad file.

    All fields default to empty / absent so callers only need to set the
    ones a given test cares about.  ``comments`` keys are the 1-based
    KiCad COMMENT indices (1..9); omitting an index produces a fixture
    with that comment field absent (as opposed to present-but-empty,
    which is ``""``).
    """

    title: str = ""
    company: str = ""
    revision: str = ""
    date: str = ""
    comments: Mapping[int, str] = field(default_factory=dict)


def _render_title_block(spec: TitleBlockSpec | None) -> str:
    """Render a ``(title_block ...)`` stanza string from *spec*.

    Returns the empty string when *spec* is ``None`` (the file omits
    the stanza entirely so the audit's ``*_titleblock_empty`` rule can
    fire).
    """
    if spec is None:
        return ""
    lines = ["\t(title_block"]
    if spec.title:
        lines.append(f'\t\t(title "{_escape(spec.title)}")')
    if spec.date:
        lines.append(f'\t\t(date "{_escape(spec.date)}")')
    if spec.revision:
        lines.append(f'\t\t(rev "{_escape(spec.revision)}")')
    if spec.company:
        lines.append(f'\t\t(company "{_escape(spec.company)}")')
    for idx in sorted(spec.comments):
        lines.append(f'\t\t(comment {idx} "{_escape(spec.comments[idx])}")')
    lines.append("\t)")
    return "\n".join(lines)


def _escape(value: str) -> str:
    """Quote a value for embedding in a KiCad S-expression string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def write_kicad_sch(path: Path, title_block: TitleBlockSpec | None) -> None:
    """Write a minimal ``.kicad_sch`` to *path* embedding *title_block*."""
    body = _render_title_block(title_block)
    content = "(kicad_sch\n" + (body + "\n" if body else "") + ")\n"
    path.write_text(content, encoding="utf-8")


def write_kicad_pcb(path: Path, title_block: TitleBlockSpec | None) -> None:
    """Write a minimal ``.kicad_pcb`` to *path* embedding *title_block*."""
    body = _render_title_block(title_block)
    content = "(kicad_pcb\n" + (body + "\n" if body else "") + ")\n"
    path.write_text(content, encoding="utf-8")


def make_minimal_project(
    project_dir: Path,
    name: str = "demo",
    *,
    sch_title_block: TitleBlockSpec | None = None,
    pcb_title_block: TitleBlockSpec | None = None,
    project_json: str = "{}\n",
) -> Path:
    """Materialise a minimal KiCad project tree under *project_dir*.

    Args:
        project_dir: Directory to create / use.  Created if absent.
        name: Project basename - drives ``<name>.kicad_pro`` /
            ``.kicad_sch`` / ``.kicad_pcb`` filenames.
        sch_title_block: Title-block content for the schematic.  Pass
            ``None`` to omit the stanza entirely.
        pcb_title_block: Title-block content for the PCB.  Pass ``None``
            to omit the stanza entirely.
        project_json: Raw text written to ``<name>.kicad_pro``.
            Defaults to an empty JSON object; pass a populated string to
            exercise ``text_variables`` reads.

    Returns:
        The ``project_dir`` :class:`Path`.
    """
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / f"{name}.kicad_pro").write_text(project_json, encoding="utf-8")
    write_kicad_sch(project_dir / f"{name}.kicad_sch", sch_title_block)
    write_kicad_pcb(project_dir / f"{name}.kicad_pcb", pcb_title_block)
    return project_dir
