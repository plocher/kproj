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

Mechanical failures vs findings (ADR 0004, wave-3 M4 round-2):

- A ``kicad-cli`` mechanical crash (nonzero return AND no JSON
  produced) is a **mechanical failure**, not a finding.  The analyzer
  raises :class:`DesignAnalysisError` so
  :class:`~kproj.application.publish_workflow.PublishWorkflow` can
  catch it before opening the change journal and return
  ``PublishResult(outcome="failed", exit_code=2)``.
- Parseable DRC/ERC violations remain non-blocking findings emitted
  through the normal :class:`AnalysisInfo` channel.
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


class DesignAnalysisError(RuntimeError):
    """Raised on a ``kicad-cli`` DRC/ERC mechanical failure.

    A mechanical failure is defined as ``returncode != 0`` combined
    with no JSON output produced (per ADR 0004's mechanical-vs-findings
    split).  The workflow catches this exception at step 3 (before the
    change journal is opened) and converts it into
    ``PublishResult(outcome="failed", exit_code=2)`` with a stderr-ready
    message.  Parseable DRC/ERC violations remain non-blocking findings
    that flow through the normal :class:`AnalysisInfo` return channel.

    Attributes:
        origin: ``"drc"`` or ``"erc"`` — which subcommand failed.
        returncode: The subprocess return code from ``kicad-cli``.
    """

    def __init__(self, message: str, *, origin: str, returncode: int) -> None:
        """Construct a :class:`DesignAnalysisError`.

        Args:
            message: Stderr-ready failure summary (include ``origin`` +
                ``returncode`` for user diagnosis).
            origin: ``"drc"`` or ``"erc"``.
            returncode: The subprocess return code.
        """
        super().__init__(message)
        self.origin = origin
        self.returncode = returncode


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

        Wave-3 fix-up (M2 + M4 round-2):

        - Each emitted :class:`Finding` carries ``source=origin`` so
          the front-matter formatter can split audit/drc/erc counts.
        - When kicad-cli exits non-zero AND produces no JSON, we now
          raise :class:`DesignAnalysisError` (round-2).  Round-1
          modelled the crash as an ordinary error finding, but
          ``compute_exit_code`` mapped it to ``exit=1`` ("findings
          present") instead of the mechanical ``exit=2``.  Raising
          keeps mechanical failures on a separate channel from
          findings per ADR 0004.

        Args:
            subcommand: e.g. ``("pcb", "drc")`` or ``("sch", "erc")``.
            target_file: The ``.kicad_pcb`` / ``.kicad_sch`` to analyse.
            project: Project basename used to stamp Findings.
            origin: ``"drc"`` or ``"erc"`` - drives ``Finding.source``
                on every emitted finding.

        Returns:
            The parsed sequence of :class:`Finding` objects.

        Raises:
            DesignAnalysisError: When kicad-cli exits non-zero AND
                produces no JSON output (mechanical failure).
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
            result = self._run(command, check=False)
            if not output_path.exists():
                _raise_if_mechanical_failure(result=result, origin=origin)
                # rc==0 with no JSON = kicad-cli produced nothing actionable.
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
                        source=origin,
                    ),
                )
        return tuple(_findings_from_payload(payload, origin=origin, project=project))


def _findings_from_payload(payload: Any, *, origin: str, project: str) -> Sequence[Finding]:
    """Walk a parsed DRC/ERC JSON payload and yield kproj :class:`Finding`s.

    The function is tolerant of shape variations between kicad-cli
    minor versions.  Two shapes are supported:

    1. **Top-level arrays** (KiCad 9.x DRC + 9.x ERC; KiCad 10.x DRC).
       Any of the keys in :data:`_VIOLATION_ARRAYS` may carry a
       violations list at the payload root.
    2. **Per-sheet arrays** (KiCad 10.x ERC).  The payload root has a
       ``sheets`` array; each sheet is an object containing a
       ``violations`` list (and optionally ``unconnected_items`` /
       ``schematic_parity`` for forward-compat).  Wave-3 M12 contract
       test caught this shape drift; pre-fix kproj silently produced
       zero findings from KiCad 10 ERC output.

    Each violation may carry an ``items`` list.  When ``items`` is
    empty or absent, a single :class:`Finding` is emitted at the
    violation granularity.
    """
    if not isinstance(payload, dict):
        return ()
    findings: list[Finding] = []
    # Shape 1: top-level violation arrays.
    for key in _VIOLATION_ARRAYS:
        violations = payload.get(key)
        if not isinstance(violations, list):
            continue
        for violation in violations:
            findings.extend(_findings_from_violation(violation, origin=origin, project=project))
    # Shape 2: KiCad 10 ERC per-sheet nesting.
    sheets = payload.get("sheets")
    if isinstance(sheets, list):
        for sheet in sheets:
            if not isinstance(sheet, dict):
                continue
            for key in _VIOLATION_ARRAYS:
                sheet_violations = sheet.get(key)
                if not isinstance(sheet_violations, list):
                    continue
                for violation in sheet_violations:
                    findings.extend(
                        _findings_from_violation(violation, origin=origin, project=project)
                    )
    return findings


def _findings_from_violation(violation: Any, *, origin: str, project: str) -> Sequence[Finding]:
    """Convert one violation dict into one or more :class:`Finding` objects.

    Wave-3 fix-up (M2 + M3): the KiCad-side location goes in
    :attr:`Finding.value` and ``origin`` (``"drc"`` or ``"erc"``)
    goes in :attr:`Finding.source` so the markdown formatter renders
    the Location column from ``value`` and front-matter counts use
    ``source`` rather than overloading ``location_hint``.
    """
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
                source=origin,
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
            source=origin,
        ),
    )


def _raise_if_mechanical_failure(*, result: SubprocessResult, origin: str) -> None:
    """Raise :class:`DesignAnalysisError` when kicad-cli failed mechanically.

    Wave-3 M4 round-2: the ``kicad-cli`` subcommand may write no JSON
    for two very different reasons:

    1. ``returncode == 0`` and no stderr: kicad-cli genuinely produced
       nothing actionable (e.g. a project with zero violations that
       still emits no ``violations`` array).  Return silently — the
       caller then returns ``()`` findings.
    2. ``returncode != 0`` (or stderr non-empty with a non-zero rc):
       kicad-cli crashed.  Raise :class:`DesignAnalysisError` so the
       workflow can convert it into ``outcome=failed / exit=2``
       (mechanical-vs-findings split per ADR 0004).

    Args:
        result: The captured :class:`SubprocessResult` from kicad-cli.
        origin: ``"drc"`` or ``"erc"``.

    Raises:
        DesignAnalysisError: On mechanical failure (rc != 0 with no JSON).
    """
    rc = result.returncode
    stderr = (result.stderr or "").strip()
    if rc == 0:
        # No JSON but clean exit: treat as "kicad-cli produced nothing".
        # (Stderr text alone with rc=0 is a warning-level condition
        # kicad-cli emits at times; we do not escalate to mechanical.)
        return
    detail = stderr or f"kicad-cli {origin} exited {rc} with no JSON output"
    raise DesignAnalysisError(
        f"kicad-cli {origin} failed without producing JSON (rc={rc}): {detail}",
        origin=origin,
        returncode=rc,
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
