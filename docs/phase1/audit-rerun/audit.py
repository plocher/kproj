#!/usr/bin/env python3
"""Phase 1 audit re-run.

Walks the (hand-edited) KiCad project corpus and emits a quality-lint report
that the kproj `--dry-run` will eventually mirror.

Read-only on the source tree; outputs go to /tmp/kproj-phase1/audit-rerun/.

Heuristics applied:
  - file presence (.kicad_sch and .kicad_pcb both required)
  - title_block presence (warn if absent in either side)
  - sch vs pcb non-equality per field (warn)
  - date in `YYYY.MM` (warn otherwise; placeholders flagged separately)
  - designer (comment1) in `FirstName LastName` form (warn otherwise)
  - placeholder values (`${...}` literals, KiCad template defaults like
    `DATE`/`Fab Date`/`Designer Name`/`Sheet Title Line N`, French-locale
    auto-populated dates)
"""
from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

CORPUS_ROOT = Path("/Users/jplocher/Dropbox/KiCad/projects")
WORKSPACE = Path("/tmp/kproj-phase1/audit-rerun")

# ---------------- title_block parser ----------------

_SIMPLE_FIELD_RE = re.compile(r'\((title|date|rev|company)\s+"((?:[^"\\]|\\.)*)"\s*\)')
_COMMENT_RE = re.compile(r'\(comment\s+([1-9])\s+"((?:[^"\\]|\\.)*)"\s*\)')


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace('\\\\', '\\')


def extract_title_block(text: str) -> Optional[dict]:
    idx = text.find("(title_block")
    if idx < 0:
        return None
    depth = 0
    for i in range(idx, len(text)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                body = text[idx:i + 1]
                return _parse_title_block_body(body)
    return None


def _parse_title_block_body(body: str) -> dict:
    out: dict = {}
    for m in _SIMPLE_FIELD_RE.finditer(body):
        out[m.group(1)] = _unescape(m.group(2))
    for m in _COMMENT_RE.finditer(body):
        out[f"comment{m.group(1)}"] = _unescape(m.group(2))
    return out


# ---------------- heuristics ----------------

DATE_OK_RE = re.compile(r"^\d{4}\.\d{2}$")
# FirstName LastName: two (or more) capitalised tokens separated by single spaces.
# Allows hyphenated last names, numerals (rare), and accented capitals.
DESIGNER_OK_RE = re.compile(r"^[A-Z][\w'-]+(?:\s+[A-Z][\w'-]+)+$")

PLACEHOLDER_STRINGS = {
    "DATE",
    "Fab Date",
    "Designer Name",
    "Title",
    "REVISION",
    "Sheet Title Line 1",
    "Sheet Title Line 2",
    "Sheet Title Line 3",
    "Sheet Title Line 4",
    "Sheet Title Line 5",
    "Sheet Title Line 6",
    "Sheet Title Line 7",
    "Sheet Title Line 8",
    "Sheet Title Line 9",
}
# Localized auto-populated default dates ("sam. 04 avril 2015", etc.) — flag prefix.
LOCALE_DEFAULT_RE = re.compile(
    r"^(lun\.|mar\.|mer\.|jeu\.|ven\.|sam\.|dim\.|"
    r"Mon |Tue |Wed |Thu |Fri |Sat |Sun )",
    re.IGNORECASE,
)
UNRESOLVED_VAR_RE = re.compile(r"^\$\{[^}]+\}$")


def is_placeholder(value: str) -> bool:
    if not value:
        return False
    if UNRESOLVED_VAR_RE.match(value):
        return True
    if value in PLACEHOLDER_STRINGS:
        return True
    if LOCALE_DEFAULT_RE.match(value):
        return True
    return False


# ---------------- audit one project ----------------

def find_projects() -> list[Path]:
    return sorted(CORPUS_ROOT.rglob("*.kicad_pro"))


def audit_one(pro_path: Path) -> dict:
    findings: list[tuple[str, str, str, str, str, str]] = []
    # (severity, project, side, field, value, reason)
    proj_dir = pro_path.parent
    basename = pro_path.stem
    is_mrcs = str(proj_dir).startswith(str(CORPUS_ROOT / "MRCS"))

    sch_path = pro_path.with_suffix(".kicad_sch")
    pcb_path = pro_path.with_suffix(".kicad_pcb")
    sch_exists = sch_path.exists()
    pcb_exists = pcb_path.exists()

    if not sch_exists:
        findings.append(("error", basename, "(file)", ".kicad_sch", "(missing)",
                         "schematic file missing"))
    if not pcb_exists:
        findings.append(("error", basename, "(file)", ".kicad_pcb", "(missing)",
                         "PCB file missing"))

    sch_tb = extract_title_block(sch_path.read_text(errors="replace")) if sch_exists else None
    pcb_tb = extract_title_block(pcb_path.read_text(errors="replace")) if pcb_exists else None

    if sch_exists and not sch_tb:
        findings.append(("warning", basename, "sch", "title_block", "(empty)",
                         "schematic metadata incomplete (title_block empty)"))
    if pcb_exists and not pcb_tb:
        findings.append(("warning", basename, "pcb", "title_block", "(empty)",
                         "PCB metadata incomplete (title_block empty)"))

    sch_tb = sch_tb or {}
    pcb_tb = pcb_tb or {}
    all_fields = set(sch_tb) | set(pcb_tb)

    for fld in sorted(all_fields):
        sch_v = sch_tb.get(fld, "")
        pcb_v = pcb_tb.get(fld, "")
        if is_placeholder(sch_v):
            findings.append(("error", basename, "sch", fld, sch_v,
                             "placeholder / template-default value"))
        if is_placeholder(pcb_v):
            findings.append(("error", basename, "pcb", fld, pcb_v,
                             "placeholder / template-default value"))
        if sch_v and pcb_v and sch_v != pcb_v:
            findings.append(("warning", basename, "sch≠pcb", fld,
                             f"sch='{sch_v}' / pcb='{pcb_v}'",
                             "SCH and PCB disagree on this field"))

    # Convention heuristics — only emit when value is present AND not a placeholder
    for side, tb in (("sch", sch_tb), ("pcb", pcb_tb)):
        d = tb.get("date", "")
        if d and not is_placeholder(d) and not DATE_OK_RE.match(d):
            findings.append(("warning", basename, side, "date", d,
                             "date not in YYYY.MM convention"))
        designer = tb.get("comment1", "")
        if designer and not is_placeholder(designer) and not DESIGNER_OK_RE.match(designer):
            findings.append(("warning", basename, side, "comment1", designer,
                             "designer not in 'FirstName LastName' convention"))

    return {
        "project": basename,
        "project_dir": str(proj_dir),
        "kicad_pro": str(pro_path),
        "is_mrcs": is_mrcs,
        "sch_exists": sch_exists,
        "pcb_exists": pcb_exists,
        "sch_tb": sch_tb,
        "pcb_tb": pcb_tb,
        "findings": findings,
    }


# ---------------- output ----------------

def write_outputs(results: list[dict]) -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    (WORKSPACE / "audit.json").write_text(
        json.dumps(results, indent=2, sort_keys=True))

    with (WORKSPACE / "findings.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["severity", "project", "side", "field", "value", "reason"])
        for r in results:
            for f in r["findings"]:
                w.writerow(f)


def summarize(results: list[dict]) -> str:
    total = len(results)
    clean = [r for r in results if not r["findings"]]
    by_sev: dict[str, int] = {}
    by_reason: dict[str, int] = {}
    for r in results:
        for sev, _proj, _side, _field, _value, reason in r["findings"]:
            by_sev[sev] = by_sev.get(sev, 0) + 1
            by_reason[reason] = by_reason.get(reason, 0) + 1
    lines = [
        f"Projects walked: {total}",
        f"Clean (no findings): {len(clean)}",
        f"Total findings: {sum(len(r['findings']) for r in results)}",
        f"  by severity: {by_sev}",
        "",
        "Findings by reason:",
    ]
    for reason, n in sorted(by_reason.items(), key=lambda x: -x[1]):
        lines.append(f"  {n:3d}  {reason}")
    if clean:
        lines.extend(["", "Clean projects:"])
        for r in clean:
            lines.append(f"  - {r['project']}  ({r['project_dir']})")
    return "\n".join(lines)


def main() -> None:
    results = [audit_one(p) for p in find_projects()]
    write_outputs(results)
    print(summarize(results))


if __name__ == "__main__":
    main()
