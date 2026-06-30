"""The :class:`DesignAnalyzer` service.

Per ``docs/DESIGN.md`` § *DesignAnalyzer*, this service invokes
``kicad-cli pcb drc`` and ``kicad-cli sch erc`` on the resolved project,
parses the produced JSON into :class:`Finding` objects, and returns
them in an :class:`AnalysisInfo`.

Subprocess invocations route through
:func:`kproj.common.subprocess_runner.run` (the sole subprocess entry
point in kproj) and write to a tempfile that is deleted before
:meth:`analyze` returns; no DRC/ERC JSON persists on disk.

KiCad's per-violation severity is preserved verbatim - including
``exclusion``, which by ADR 0004's locked policy does NOT contribute
to the ``exit_code=1`` "findings present" rule.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..common.subprocess_runner import SubprocessResult
from ..common.subprocess_runner import run as default_run
from ..model.analysis_info import AnalysisInfo
from ..model.finding import Finding
from ..model.resolved_project import ResolvedProject
from ..model.severity import Severity

SubprocessCallable = Callable[..., SubprocessResult]
"""Type alias for the injectable subprocess runner.

The default is :func:`kproj.common.subprocess_runner.run`; tests pass a
fake that returns a canned :class:`SubprocessResult` so the JSON parser
can be exercised without a real ``kicad-cli`` install.
"""

_SEVERITY_BY_TOKEN: Mapping[str, Severity] = {
    "error": Severity.ERROR,
    "warning": Severity.WARNING,
    "exclusion": Severity.EXCLUSION,
}
"""KiCad-CLI severity tokens mapped to kproj :class:`Severity`."""

_VIOLATION_ARRAYS: tuple[str, ...] = (
    "violations",
    "unconnected_items",
    "schematic_parity",
)
"""Top-level JSON arrays emitted by ``kicad-cli sch erc`` / ``pcb drc``.

DRC only emits ``violations``; ERC emits all three.  Iterating the full
set on every parse keeps the implementation tolerant of future shape
extensions and lets one parser serve both subcommands.
"""


class DesignAnalyzer:
    """Run DRC + ERC against a resolved KiCad project.

    Methods:
        analyze: Invoke ``kicad-cli pcb drc`` and ``kicad-cli sch erc``,
            parse the produced JSON, and return the merged findings.
    """

    def __init__(
        self,
        kicad_cli: Path,
        *,
        runner: SubprocessCallable | None = None,
    ) -> None:
        """Construct a DRC + ERC analyzer.

        Args:
            kicad_cli: Path to the discovered ``kicad-cli`` executable.
            runner: Optional subprocess runner override; defaults to
                :func:`kproj.common.subprocess_runner.run`.  Tests pass
                a fake to short-circuit the real subprocess.
        """
        self._kicad_cli = kicad_cli
        self._run = runner or default_run

    def analyze(self, resolved: ResolvedProject) -> AnalysisInfo:
        """Run DRC + ERC against *resolved* and return merged findings.

        Args:
            resolved: A :class:`ResolvedProject` whose ``pcb_file`` and
                ``root_schematic`` are passed to ``kicad-cli``.

        Returns:
            An :class:`AnalysisInfo` whose ``findings`` carry DRC + ERC
            results in that order.  Per-violation severities are
            preserved verbatim.
        """
        drc_findings = self._run_kicad_subcommand(
            subcommand=("pcb", "drc"),
            target_file=resolved.pcb_file,
            project=resolved.basename,
            origin="drc",
        )
        erc_findings = self._run_kicad_subcommand(
            subcommand=("sch", "erc"),
            target_file=resolved.root_schematic,
            project=resolved.basename,
            origin="erc",
        )
        return AnalysisInfo(findings=tuple(drc_findings) + tuple(erc_findings))

    def _run_kicad_subcommand(
        self,
        *,
        subcommand: tuple[str, ...],
        target_file: Path,
        project: str,
        origin: str,
    ) -> Sequence[Finding]:
        """Execute one ``kicad-cli`` subcommand and parse its JSON output.

        Args:
            subcommand: e.g. ``("pcb", "drc")`` or ``("sch", "erc")``.
            target_file: The ``.kicad_pcb`` / ``.kicad_sch`` to analyse.
            project: Project basename used to stamp Findings.
            origin: ``"drc"`` or ``"erc"`` - surfaces in the Finding's
                ``location_hint`` so downstream formatters can group by
                source.

        Returns:
            The parsed sequence of :class:`Finding` objects; empty when
            no violations are reported.
        """
        with tempfile.TemporaryDirectory(prefix=f"kproj-{origin}-") as tmpdir:
            output_path = Path(tmpdir) / f"{origin}.json"
            command = (
                str(self._kicad_cli),
                *subcommand,
                "--format",
                "json",
                "--severity-all",
                "--output",
                str(output_path),
                str(target_file),
            )
            # check=False because KiCad's DRC/ERC return non-zero when
            # violations exist; that's a finding to surface, not a kproj
            # mechanical failure.
            self._run(command, check=False)
            if not output_path.exists():
                return ()
            try:
                payload = json.loads(output_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                return (
                    Finding(
                        severity=Severity.WARNING,
                        field=f"{origin}_json_unreadable",
                        value=str(output_path),
                        reason=f"could not parse {origin.upper()} JSON: {exc}",
                        project=project,
                        location_hint=origin,
                    ),
                )
        return tuple(_findings_from_payload(payload, origin=origin, project=project))


def _findings_from_payload(payload: Any, *, origin: str, project: str) -> Sequence[Finding]:
    """Walk a parsed DRC/ERC JSON payload and yield kproj :class:`Finding`s.

    The function is intentionally tolerant of slight shape variations
    between kicad-cli minor versions: any of the keys in
    :data:`_VIOLATION_ARRAYS` may carry a violations list, and each
    violation may carry an ``items`` list.  When ``items`` is empty or
    absent, a single :class:`Finding` is emitted at the violation
    granularity.
    """
    if not isinstance(payload, dict):
        return ()
    findings: list[Finding] = []
    for key in _VIOLATION_ARRAYS:
        violations = payload.get(key)
        if not isinstance(violations, list):
            continue
        for violation in violations:
            findings.extend(_findings_from_violation(violation, origin=origin, project=project))
    return findings


def _findings_from_violation(violation: Any, *, origin: str, project: str) -> Sequence[Finding]:
    """Convert one violation dict into one or more :class:`Finding` objects."""
    if not isinstance(violation, dict):
        return ()
    severity = _SEVERITY_BY_TOKEN.get(str(violation.get("severity", "")).lower(), Severity.WARNING)
    rule = str(violation.get("type", "unknown"))
    base_reason = str(violation.get("description", "")) or rule
    items = violation.get("items")
    if isinstance(items, list) and items:
        return tuple(
            Finding(
                severity=severity,
                field=rule,
                value=_item_location(item),
                reason=_item_reason(item, base_reason),
                project=project,
                location_hint=origin,
            )
            for item in items
        )
    return (
        Finding(
            severity=severity,
            field=rule,
            value="",
            reason=base_reason,
            project=project,
            location_hint=origin,
        ),
    )


def _item_location(item: Any) -> str:
    """Extract a printable location string from an item dict."""
    if not isinstance(item, dict):
        return ""
    # kicad-cli emits various location keys depending on subcommand.
    for key in ("pos", "uuid", "description", "sheet"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _item_reason(item: Any, fallback: str) -> str:
    """Return a per-item explanation, falling back to the violation description."""
    if isinstance(item, dict):
        text = item.get("description")
        if text:
            return str(text)
    return fallback
