"""Contract test for ``kicad-cli sch erc`` JSON output shape.

Wave-3 fix-up (M12): pins the kicad-cli ERC contract kproj depends
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


_MINIMAL_SCH = Path(__file__).parent.parent / "fixtures" / "minimal" / "minimal.kicad_sch"

pytestmark = pytest.mark.contract


def _run_erc(tmp_path: Path) -> tuple[dict[str, object], subprocess.CompletedProcess[bytes]]:
    """Invoke ``kicad-cli sch erc`` and return the parsed JSON + result."""
    output = tmp_path / "erc.json"
    result = subprocess.run(
        [
            str(find_kicad_cli()),
            "sch",
            "erc",
            "--format",
            "json",
            "--severity-all",
            "--output",
            str(output),
            str(_MINIMAL_SCH),
        ],
        check=False,
        capture_output=True,
        timeout=60,
    )
    assert output.exists(), (
        f"kicad-cli sch erc did not write JSON to {output}. "
        f"stderr={result.stderr.decode(errors='replace')[:400]!r}"
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert isinstance(payload, dict), (
        f"expected top-level JSON object; got {type(payload).__name__}"
    )
    return payload, result


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_erc_produces_json_output(tmp_path: Path) -> None:
    """``kicad-cli sch erc --format json`` writes valid JSON to --output."""
    payload, _ = _run_erc(tmp_path)
    assert isinstance(payload, dict)


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_erc_json_contains_known_violation_keys(tmp_path: Path) -> None:
    """The ERC JSON top-level shape exposes findings through a known route.

    DesignAnalyzer supports two shapes:

    - Flat: any of :data:`_VIOLATION_ARRAYS` keys at the payload root.
    - Per-sheet: a ``sheets`` array whose elements each carry one of
      the :data:`_VIOLATION_ARRAYS` keys (KiCad 10.x ERC).

    This test asserts kicad-cli emits at least one recognised route
    so kproj's parser is guaranteed to reach the findings.
    """
    payload, _ = _run_erc(tmp_path)
    recognised_flat = [k for k in _VIOLATION_ARRAYS if k in payload]
    sheets = payload.get("sheets")
    recognised_per_sheet: list[str] = []
    if isinstance(sheets, list):
        for sheet in sheets:
            if not isinstance(sheet, dict):
                continue
            recognised_per_sheet.extend(k for k in _VIOLATION_ARRAYS if k in sheet)
    assert recognised_flat or recognised_per_sheet, (
        f"ERC JSON top-level keys {sorted(payload.keys())} do not carry "
        f"a recognised violations shape. Known top-level keys are "
        f"{_VIOLATION_ARRAYS}; KiCad 10.x also nests them under "
        f"'sheets[].<key>'. Update DesignAnalyzer._findings_from_payload "
        f"if kicad-cli changed the shape."
    )
    for key in recognised_flat:
        assert isinstance(payload[key], list)


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_erc_severity_tokens_match_designanalyzer_map(tmp_path: Path) -> None:
    """Any per-violation ``severity`` token ERC emits must be in kproj's map."""
    payload, _ = _run_erc(tmp_path)
    emitted_tokens: set[str] = set()
    # Flat + per-sheet shapes both scanned.
    for key in _VIOLATION_ARRAYS:
        for violation in payload.get(key, []):
            token = str(violation.get("severity", "")).lower()
            if token:
                emitted_tokens.add(token)
    for sheet in payload.get("sheets", []) or []:
        if not isinstance(sheet, dict):
            continue
        for key in _VIOLATION_ARRAYS:
            for violation in sheet.get(key, []):
                token = str(violation.get("severity", "")).lower()
                if token:
                    emitted_tokens.add(token)
    unknown = emitted_tokens - set(_SEVERITY_BY_TOKEN)
    assert not unknown, (
        f"kicad-cli sch erc emitted severity tokens not in "
        f"DesignAnalyzer._SEVERITY_BY_TOKEN: {unknown}. "
        f"Known tokens: {set(_SEVERITY_BY_TOKEN)}."
    )


@pytest.mark.skipif(not _kicad_cli_available(), reason="kicad-cli not installed locally")
def test_erc_returncode_semantics(tmp_path: Path) -> None:
    """kicad-cli sch erc's return code differentiates violations vs errors."""
    _, result = _run_erc(tmp_path)
    assert result.returncode in (0, 1, 2, 3, 4, 5), (
        f"unexpected return code {result.returncode} from kicad-cli sch erc"
    )
