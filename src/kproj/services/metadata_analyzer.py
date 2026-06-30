"""The :class:`MetadataAnalyzer` service.

Implements the 14-rule metadata audit table from ``docs/DESIGN.md`` §
*Audit heuristic list*.  Each rule produces zero or one
:class:`Finding`; the union is returned in an :class:`AnalysisInfo`.

Per ADR 0004 ("show what is provided"), the audit never blocks - every
finding is surface-only.  Severities reflect KiCad-style intent
(``error`` = mechanical wrongness, ``warning`` = quality concern) and
are consumed by the exit-code mapping in
:mod:`kproj.model.publish_result`.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable
from pathlib import Path

from ..model.analysis_info import AnalysisInfo
from ..model.finding import Finding
from ..model.project_info import ProjectInfo, Status
from ..model.severity import Severity

_DEFAULT_PROJECTS_ROOT = Path.home() / "Dropbox" / "KiCad" / "projects"
"""SPCoast convention used for ``replaced-by:<X>`` target resolution."""

_VALID_STATUS_TOKENS = frozenset({"experimental", "active", "retired", "broken", "private"})
"""Non-parameterised tokens accepted by the ``${COMMENT9}`` taxonomy."""

_REPLACED_BY_RE = re.compile(r"^replaced-by:\S+$")
"""Pattern locking the parameterised ``${COMMENT9}`` form."""

_DATE_RE = re.compile(r"^\d{4}\.\d{2}$")
"""Locked SPCoast date format: ``YYYY.MM``."""

_DESIGNER_RE = re.compile(r"^[A-Z][\w'\-]+(\s+[A-Z][\w'\-]+)+$")
"""SPCoast designer format: two or more capitalised words."""

_PLACEHOLDER_LITERALS = frozenset({"DATE", "Fab Date", "Designer Name"})
"""Closed set of KiCad / SPCoast-default placeholder strings.

The ``Sheet Title Line N`` pattern is matched separately via regex
because ``N`` is variable.  Locale-default dates are dropped from v1's
detection set; KiCad does not insert one automatically.
"""

_SHEET_TITLE_RE = re.compile(r"^Sheet Title Line \d+$")
"""KiCad's default placeholder for an unpopulated sheet title line."""

_INTERPOLATION_RE = re.compile(r"^\$\{[^}]+\}$")
"""A bare KiCad text-variable reference left unsubstituted, e.g. ``${TITLE}``."""

_COMPARABLE_FIELDS: tuple[tuple[str, str], ...] = (
    ("title", "title"),
    ("company", "company"),
)
"""SCH-vs-PCB scalar fields whose disagreement is always non-legitimate.

``revision`` and ``date`` divergence are intentionally NOT compared here:
- ``revision`` divergence is handled by the dedicated ``rev_relation``
  rule (legitimate divergence is ``pcb_rev = sch_rev + uppercase``).
- ``date`` divergence is legitimate when the PCB date trails the SCH
  date (fab date vs design date); cross-comparison is out-of-scope.
"""


class MetadataAnalyzer:
    """Apply the 14-rule audit table to a :class:`ProjectInfo`.

    Methods:
        analyze: Run every rule against the given project and return an
            :class:`AnalysisInfo` collecting the produced
            :class:`Finding` objects.
    """

    def __init__(self, *, projects_root: Path | None = None) -> None:
        """Construct an analyzer.

        Args:
            projects_root: Optional override for the ``replaced-by:<X>``
                target-resolution root.  Defaults to
                ``~/Dropbox/KiCad/projects/`` per the SPCoast convention.
        """
        self._projects_root = projects_root or _DEFAULT_PROJECTS_ROOT

    def analyze(self, project_info: ProjectInfo, project_path: Path) -> AnalysisInfo:
        """Run the 14-rule metadata audit.

        Args:
            project_info: The project's title-block-derived facts.
            project_path: Path to the project directory.  Used for
                file-existence checks (``kicad_*_missing``) and the
                ``production/`` rules.

        Returns:
            An :class:`AnalysisInfo` collecting every produced finding
            in insertion order.  Every emitted finding carries
            ``source="audit"`` (wave-3 M2 fix-up) so downstream
            consumers can split audit/drc/erc counts by origin.
        """
        findings: list[Finding] = []
        findings.extend(self._file_existence_rules(project_info, project_path))
        findings.extend(self._title_block_presence_rules(project_info))
        findings.extend(self._sch_pcb_disagree_rules(project_info))
        findings.extend(self._placeholder_value_rules(project_info))
        findings.extend(self._comment9_rules(project_info))
        findings.extend(self._format_rules(project_info))
        findings.extend(self._rev_relation_rule(project_info))
        findings.extend(self._replaced_by_target_rule(project_info))
        findings.extend(self._production_rules(project_info, project_path))
        # Stamp source="audit" on every emitted finding so
        # FrontMatterSummaryFormatter can render source-specific counts
        # without the per-rule constructors having to repeat the kwarg.
        stamped = tuple(dataclasses.replace(f, source="audit") for f in findings)
        return AnalysisInfo(findings=stamped)

    # ----- rule implementations -----
    def _file_existence_rules(self, info: ProjectInfo, project_path: Path) -> Iterable[Finding]:
        sch_path = project_path / f"{info.project}.kicad_sch"
        pcb_path = project_path / f"{info.project}.kicad_pcb"
        if not sch_path.exists():
            yield Finding(
                severity=Severity.ERROR,
                field="kicad_sch_missing",
                value=str(sch_path),
                reason=f"expected schematic file {sch_path.name} not found",
                project=info.project,
            )
        if not pcb_path.exists():
            yield Finding(
                severity=Severity.ERROR,
                field="kicad_pcb_missing",
                value=str(pcb_path),
                reason=f"expected PCB file {pcb_path.name} not found",
                project=info.project,
            )

    def _title_block_presence_rules(self, info: ProjectInfo) -> Iterable[Finding]:
        if info.raw_sch.is_empty:
            yield Finding(
                severity=Severity.WARNING,
                field="sch_titleblock_empty",
                value="",
                reason="schematic has an empty or missing (title_block ...) stanza",
                project=info.project,
            )
        if info.raw_pcb.is_empty:
            yield Finding(
                severity=Severity.WARNING,
                field="pcb_titleblock_empty",
                value="",
                reason="PCB has an empty or missing (title_block ...) stanza",
                project=info.project,
            )

    def _sch_pcb_disagree_rules(self, info: ProjectInfo) -> Iterable[Finding]:
        for sch_attr, pcb_attr in _COMPARABLE_FIELDS:
            sch_value = getattr(info.raw_sch, sch_attr)
            pcb_value = getattr(info.raw_pcb, pcb_attr)
            if sch_value and pcb_value and sch_value != pcb_value:
                yield Finding(
                    severity=Severity.WARNING,
                    field="sch_pcb_disagree",
                    value=f"sch={sch_value!r} pcb={pcb_value!r}",
                    reason=(
                        f"SCH and PCB disagree on {sch_attr}: sch={sch_value!r}, pcb={pcb_value!r}"
                    ),
                    project=info.project,
                    location_hint=sch_attr,
                )
        # comment1 (designer) - either non-empty side wins, but both populated
        # with non-matching values is a finding.
        sch_designer = info.raw_sch.comments.get(1, "")
        pcb_designer = info.raw_pcb.comments.get(1, "")
        if sch_designer and pcb_designer and sch_designer != pcb_designer:
            yield Finding(
                severity=Severity.WARNING,
                field="sch_pcb_disagree",
                value=f"sch={sch_designer!r} pcb={pcb_designer!r}",
                reason=(
                    "SCH and PCB disagree on designer (comment1): "
                    f"sch={sch_designer!r}, pcb={pcb_designer!r}"
                ),
                project=info.project,
                location_hint="comment1",
            )

    def _placeholder_value_rules(self, info: ProjectInfo) -> Iterable[Finding]:
        targets: tuple[tuple[str, str], ...] = (
            ("title", info.title),
            ("company", info.company),
            ("design_rev", info.design_rev),
            ("board_rev", info.board_rev),
            ("date", info.date),
            ("designer", info.designer),
            ("tagline", info.tagline),
            ("overview", info.overview),
        )
        for field_name, value in targets:
            if not value:
                continue
            if _is_placeholder(value):
                yield Finding(
                    severity=Severity.ERROR,
                    field="placeholder_value",
                    value=value,
                    reason=(f"{field_name} carries the unedited KiCad placeholder {value!r}"),
                    project=info.project,
                    location_hint=field_name,
                )

    def _comment9_rules(self, info: ProjectInfo) -> Iterable[Finding]:
        sch_status = info.raw_sch.comments.get(9, "")
        pcb_status = info.raw_pcb.comments.get(9, "")
        any_present = bool(sch_status or pcb_status)
        if not any_present:
            yield Finding(
                severity=Severity.WARNING,
                field="comment9_missing",
                value="",
                reason=(
                    "${COMMENT9} (status) is empty or absent on both SCH and PCB; "
                    "defaulting to status=active for this publish"
                ),
                project=info.project,
            )
            return
        # Prefer SCH per the locked precedence; otherwise use PCB.
        raw = sch_status or pcb_status
        if raw in _VALID_STATUS_TOKENS or _REPLACED_BY_RE.match(raw):
            return
        yield Finding(
            severity=Severity.ERROR,
            field="comment9_taxonomy",
            value=raw,
            reason=(
                f"${{COMMENT9}} value {raw!r} is outside the accepted taxonomy "
                "{experimental, active, retired, broken, replaced-by:<X>, private}"
            ),
            project=info.project,
        )

    def _format_rules(self, info: ProjectInfo) -> Iterable[Finding]:
        if info.date and not _DATE_RE.match(info.date):
            yield Finding(
                severity=Severity.WARNING,
                field="date_format",
                value=info.date,
                reason=(f"date {info.date!r} does not match the locked YYYY.MM format"),
                project=info.project,
            )
        if info.designer and not _DESIGNER_RE.match(info.designer):
            yield Finding(
                severity=Severity.WARNING,
                field="designer_format",
                value=info.designer,
                reason=(
                    f"designer {info.designer!r} does not match the 'FirstName LastName' format"
                ),
                project=info.project,
            )

    def _rev_relation_rule(self, info: ProjectInfo) -> Iterable[Finding]:
        if not info.design_rev or not info.board_rev:
            return
        if info.design_rev == info.board_rev:
            return
        expected_re = re.compile(rf"^{re.escape(info.design_rev)}[A-Z]+$")
        if expected_re.match(info.board_rev):
            return
        yield Finding(
            severity=Severity.WARNING,
            field="rev_relation",
            value=f"sch={info.design_rev!r} pcb={info.board_rev!r}",
            reason=(
                f"board_rev {info.board_rev!r} should extend "
                f"design_rev {info.design_rev!r} with one or more uppercase letters "
                "(e.g. 3.0 -> 3.0B)"
            ),
            project=info.project,
        )

    def _replaced_by_target_rule(self, info: ProjectInfo) -> Iterable[Finding]:
        if info.status is not Status.REPLACED_BY:
            return
        target = info.replaced_by_target
        if not target:
            return
        target_dir = self._projects_root / target
        if target_dir.is_dir():
            return
        yield Finding(
            severity=Severity.WARNING,
            field="replaced_by_target_missing",
            value=target,
            reason=(
                f"replaced-by:{target} references a project directory "
                f"that does not exist at {target_dir}"
            ),
            project=info.project,
        )

    def _production_rules(self, info: ProjectInfo, project_path: Path) -> Iterable[Finding]:
        production_dir = project_path / "production"
        if not production_dir.is_dir() or not any(production_dir.iterdir()):
            yield Finding(
                severity=Severity.WARNING,
                field="production_missing",
                value=str(production_dir),
                reason=(
                    f"{production_dir} is missing or empty; "
                    "fab.zip artifact will be omitted from the publish"
                ),
                project=info.project,
            )
            return
        pcb_path = project_path / f"{info.project}.kicad_pcb"
        if not pcb_path.exists():
            return
        pcb_mtime = pcb_path.stat().st_mtime
        for zip_path in sorted(production_dir.glob("*.zip")):
            if zip_path.stat().st_mtime < pcb_mtime:
                yield Finding(
                    severity=Severity.WARNING,
                    field="production_stale",
                    value=str(zip_path),
                    reason=(
                        f"{zip_path.name} is older than {pcb_path.name}; "
                        "re-run `jbom fab` to regenerate fab artifacts"
                    ),
                    project=info.project,
                )


def _is_placeholder(value: str) -> bool:
    """Return ``True`` when *value* matches one of the KiCad placeholder forms.

    The check is intentionally narrow: only verbatim placeholder
    strings + bare ``${VAR}`` substitutions trigger this.  Substring
    matches against legitimate field content (e.g. a project literally
    titled ``"Sheet Title Line: ..."``) are deliberately not flagged.
    """
    if value in _PLACEHOLDER_LITERALS:
        return True
    if _SHEET_TITLE_RE.match(value):
        return True
    return bool(_INTERPOLATION_RE.match(value))
