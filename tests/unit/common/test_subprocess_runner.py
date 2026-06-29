"""Unit tests for :mod:`kproj.common.subprocess_runner`.

Validates the single ``run()`` entry point's contract per
``docs/DESIGN.md`` § *Subprocess runner*: timeout / failure / success
paths + SubprocessResult shape.
"""

from __future__ import annotations

import dataclasses
import subprocess
from collections.abc import Iterable
from pathlib import Path

import pytest

from kproj.common import subprocess_runner
from kproj.common.subprocess_runner import (
    DEFAULT_GIT_TIMEOUT,
    DEFAULT_KICAD_TIMEOUT,
    SubprocessFailedError,
    SubprocessResult,
    SubprocessTimeoutError,
    run,
)


@dataclasses.dataclass
class _FakeCompleted:
    """Stand-in for :class:`subprocess.CompletedProcess`."""

    args: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""


def _make_fake_run(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    raise_timeout: bool = False,
):
    """Build a ``subprocess.run`` stand-in for monkeypatching."""

    def _fake_run(cmd: Iterable[str], **kwargs: object) -> _FakeCompleted:
        if raise_timeout:
            raise subprocess.TimeoutExpired(cmd=list(cmd), timeout=1.0)
        return _FakeCompleted(args=list(cmd), returncode=returncode, stdout=stdout, stderr=stderr)

    return _fake_run


def test_subprocess_result_is_frozen() -> None:
    """``SubprocessResult`` is a frozen dataclass."""
    result = SubprocessResult(
        command=("a",), returncode=0, stdout="", stderr="", elapsed_seconds=0.0
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.returncode = 1  # type: ignore[misc]


def test_run_returns_subprocess_result_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Success path returns a populated :class:`SubprocessResult`."""
    monkeypatch.setattr(
        subprocess_runner.subprocess,
        "run",
        _make_fake_run(returncode=0, stdout="hello", stderr=""),
    )
    result = run(["echo", "hi"])
    assert isinstance(result, SubprocessResult)
    assert result.returncode == 0
    assert result.stdout == "hello"
    assert result.command == ("echo", "hi")
    assert result.elapsed_seconds >= 0.0


def test_run_raises_subprocess_failed_error_on_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-zero return raises :class:`SubprocessFailedError`."""
    monkeypatch.setattr(
        subprocess_runner.subprocess,
        "run",
        _make_fake_run(returncode=2, stdout="x", stderr="boom"),
    )
    with pytest.raises(SubprocessFailedError) as exc_info:
        run(["false"])
    err = exc_info.value
    assert err.returncode == 2
    assert err.stderr == "boom"
    assert err.command == ("false",)


def test_run_raises_subprocess_timeout_error_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """:exc:`subprocess.TimeoutExpired` becomes :class:`SubprocessTimeoutError`."""
    monkeypatch.setattr(subprocess_runner.subprocess, "run", _make_fake_run(raise_timeout=True))
    with pytest.raises(SubprocessTimeoutError) as exc_info:
        run(["kicad-cli", "pcb", "drc"], timeout=1.0)
    err = exc_info.value
    assert err.command == ("kicad-cli", "pcb", "drc")
    assert err.timeout == 1.0


def test_run_does_not_raise_when_check_is_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``check=False`` returns the SubprocessResult even on non-zero return.

    Useful for commands like ``git status --porcelain`` where a non-zero
    return is an expected (informational) outcome.
    """
    monkeypatch.setattr(
        subprocess_runner.subprocess,
        "run",
        _make_fake_run(returncode=128, stdout="", stderr="not a repo"),
    )
    result = run(["git", "status"], check=False)
    assert result.returncode == 128


def test_run_default_timeouts_match_design() -> None:
    """Module-level default timeouts match the DESIGN doc."""
    assert DEFAULT_KICAD_TIMEOUT == 120.0
    assert DEFAULT_GIT_TIMEOUT == 30.0


def test_run_passes_cwd_and_env_through(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``cwd`` and ``env`` are forwarded to the underlying subprocess.run."""
    captured: dict[str, object] = {}

    def _fake_run(cmd: Iterable[str], **kwargs: object) -> _FakeCompleted:
        captured["cmd"] = list(cmd)
        captured["kwargs"] = kwargs
        return _FakeCompleted(args=list(cmd), returncode=0)

    monkeypatch.setattr(subprocess_runner.subprocess, "run", _fake_run)
    run(["true"], cwd=tmp_path, env={"FOO": "bar"})
    kwargs = captured["kwargs"]
    assert kwargs["cwd"] == tmp_path  # type: ignore[index]
    assert kwargs["env"] == {"FOO": "bar"}  # type: ignore[index]
