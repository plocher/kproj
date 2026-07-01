"""Contract test for ``kicad-cli pcb drc`` JSON output shape.

Wave-3 fix-up (M12): pins the kicad-cli DRC contract kproj depends
on.  DesignAnalyzer's unit tests use canned JSON — this test runs
the real local ``kicad-cli`` against ``tests/fixtures/minimal`` so
we detect JSON-shape drift between KiCad minor versions.

Skipped automatically when ``kicad-cli`` is not installed locally
(CI / non-developer machines), per ``docs/DESIGN.md`` § *Contract
tests*.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kproj.common.kicad_install import KicadNotFoundError, find_kicad_cli
from kproj.model.severity import Severity
from kproj.services.design_analyzer import (
    _SEVERITY_BY_TOKEN,
    _VIOLATION_ARRAYS,
)


def _kicad_cli_available() -> bool:
    """Return ``True`` iff :func:`find_kicad_cli` resolves a real binary."""
    try:
        find_kicad_cli()
    except KicadNotFoundError:
        return False
    return True


_MINIMAL_PCB = Path(__file__).parent.parent / "fixtures" / "minimal" / "minimal.kicad_pcb"

pytestmark = pytest.mark.contract


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_drc_produces_json_output(tmp_path: Path) -> None:
    """``kicad-cli pcb drc --format json`` writes valid JSON to --output."""
    output = tmp_path / "drc.json"
    result = subprocess.run(
        [
            str(find_kicad_cli()),
            "pcb",
            "drc",
            "--format",
            "json",
            "--severity-all",
            "--output",
            str(output),
            str(_MINIMAL_PCB),
        ],
        check=False,
        capture_output=True,
        timeout=60,
    )
    # kicad-cli returns non-zero when violations exist; treat as data.
    assert output.exists(), (
        f"kicad-cli pcb drc did not write JSON to {output}. "
        f"stderr={result.stderr.decode(errors='replace')[:400]!r}"
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), (
        f"expected top-level JSON object; got {type(payload).__name__}"
    )


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_drc_json_contains_violations_key(tmp_path: Path) -> None:
    """The DRC JSON top-level shape carries a ``violations`` array."""
    output = tmp_path / "drc.json"
    subprocess.run(
        [
            str(find_kicad_cli()),
            "pcb",
            "drc",
            "--format",
            "json",
            "--severity-all",
            "--output",
            str(output),
            str(_MINIMAL_PCB),
        ],
        check=False,
        capture_output=True,
        timeout=60,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert "violations" in payload, (
        f"DRC JSON is missing the 'violations' top-level key; "
        f"kproj DesignAnalyzer._VIOLATION_ARRAYS={_VIOLATION_ARRAYS}. "
        f"Actual keys: {sorted(payload.keys())}"
    )
    assert isinstance(payload["violations"], list)


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_drc_severity_tokens_match_designanalyzer_map(tmp_path: Path) -> None:
    """Any per-violation ``severity`` token DRC emits must be in kproj's map.

    ``DesignAnalyzer._SEVERITY_BY_TOKEN`` maps kicad-cli severity
    tokens to :class:`Severity`; a KiCad minor-version change that
    added a new token would silently fall back to ``Severity.WARNING``.
    This test asserts every token DRC actually emits is known.
    """
    output = tmp_path / "drc.json"
    subprocess.run(
        [
            str(find_kicad_cli()),
            "pcb",
            "drc",
            "--format",
            "json",
            "--severity-all",
            "--output",
            str(output),
            str(_MINIMAL_PCB),
        ],
        check=False,
        capture_output=True,
        timeout=60,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    emitted_tokens: set[str] = set()
    for key in _VIOLATION_ARRAYS:
        for violation in payload.get(key, []):
            token = str(violation.get("severity", "")).lower()
            if token:
                emitted_tokens.add(token)
    unknown = emitted_tokens - set(_SEVERITY_BY_TOKEN)
    assert not unknown, (
        f"kicad-cli pcb drc emitted severity tokens not in "
        f"DesignAnalyzer._SEVERITY_BY_TOKEN: {unknown}. "
        f"Known tokens: {set(_SEVERITY_BY_TOKEN)}. "
        f"Update _SEVERITY_BY_TOKEN if a new taxonomy value is intentional."
    )
    # Sanity: every mapped Severity is actually a Severity enum member.
    for sev in _SEVERITY_BY_TOKEN.values():
        assert isinstance(sev, Severity)


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_drc_returncode_semantics(tmp_path: Path) -> None:
    """kicad-cli pcb drc's return code differentiates violations vs errors.

    DesignAnalyzer runs kicad-cli with ``check=False`` because a
    non-zero exit is expected when violations exist (that's a
    finding, not a mechanical failure).  This test just documents
    that the JSON file is produced regardless of return code; the
    M4 mechanical-failure detector kicks in only when JSON is
    absent AND rc != 0.
    """
    output = tmp_path / "drc.json"
    result = subprocess.run(
        [
            str(find_kicad_cli()),
            "pcb",
            "drc",
            "--format",
            "json",
            "--severity-all",
            "--output",
            str(output),
            str(_MINIMAL_PCB),
        ],
        check=False,
        capture_output=True,
        timeout=60,
    )
    # Either 0 (no violations) or non-zero (violations present); both
    # cases must still leave a parseable JSON file behind.
    assert output.exists()
    json.loads(output.read_text(encoding="utf-8"))
    # Pin the observation for future contract diffs.
    assert result.returncode in (0, 1, 2, 3, 4, 5), (
        f"unexpected return code {result.returncode} from kicad-cli pcb drc"
    )
