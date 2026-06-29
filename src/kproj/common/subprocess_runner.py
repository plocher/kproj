"""Shared subprocess runner per ``docs/DESIGN.md`` § *Subprocess runner*.

This is the **only** place in kproj that calls :func:`subprocess.run`.
All kicad-cli / iBOM / git invocations go through :func:`run` to
guarantee uniform timeout handling, error translation, and verbose-mode
logging.

Per the locked DESIGN contract:

- Default timeout 120 s for kicad-cli + iBOM, 30 s for git
  (:data:`DEFAULT_KICAD_TIMEOUT` / :data:`DEFAULT_GIT_TIMEOUT`).
- :exc:`subprocess.TimeoutExpired` becomes :exc:`SubprocessTimeoutError`.
- Non-zero return becomes :exc:`SubprocessFailedError` (unless
  ``check=False``).
- :exc:`KeyboardInterrupt` propagates unchanged after attempting to
  terminate the child process cleanly.
- Success returns :class:`SubprocessResult` with the argv, returncode,
  stdout, stderr, and elapsed wall-clock time.
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_KICAD_TIMEOUT: float = 120.0
"""Default per-step timeout for kicad-cli + iBOM invocations (seconds)."""

DEFAULT_GIT_TIMEOUT: float = 30.0
"""Default per-step timeout for git invocations (seconds)."""


@dataclass(frozen=True)
class SubprocessResult:
    """Successful subprocess invocation result.

    Attributes:
        command: Argv that was executed, as a tuple.
        returncode: Process exit code (always ``0`` when ``check=True``;
            may be non-zero when ``check=False`` is set on the caller).
        stdout: Captured standard output as text.
        stderr: Captured standard error as text.
        elapsed_seconds: Wall-clock seconds spent in the subprocess.
    """

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float


class SubprocessTimeoutError(RuntimeError):
    """Raised when a subprocess exceeds its per-step timeout.

    Carries the command and timeout for diagnostic surfacing.
    """

    def __init__(self, command: Sequence[str], timeout: float) -> None:
        """Construct the error.

        Args:
            command: The argv that timed out.
            timeout: The configured timeout (seconds) that was exceeded.
        """
        super().__init__(f"timed out after {timeout}s: {list(command)!r}")
        self.command: tuple[str, ...] = tuple(command)
        self.timeout: float = timeout


@dataclass(frozen=True)
class _FailedDetails:
    """Internal helper carrying SubprocessFailedError fields."""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class SubprocessFailedError(RuntimeError):
    """Raised when a subprocess exits with a non-zero return code.

    Attributes:
        command: Argv that was executed.
        returncode: The non-zero process exit code.
        stdout: Captured standard output.
        stderr: Captured standard error.
    """

    def __init__(
        self,
        command: Sequence[str],
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> None:
        """Construct the error.

        Args:
            command: Argv that was executed.
            returncode: The non-zero process exit code.
            stdout: Captured standard output.
            stderr: Captured standard error.
        """
        super().__init__(f"command failed with exit {returncode}: {list(command)!r}")
        self._details = _FailedDetails(
            command=tuple(command),
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    @property
    def command(self) -> tuple[str, ...]:
        """Argv that was executed."""
        return self._details.command

    @property
    def returncode(self) -> int:
        """The non-zero process exit code."""
        return self._details.returncode

    @property
    def stdout(self) -> str:
        """Captured standard output."""
        return self._details.stdout

    @property
    def stderr(self) -> str:
        """Captured standard error."""
        return self._details.stderr


@dataclass(frozen=True)
class _RunOptions:
    """Resolved options for a single :func:`run` invocation."""

    command: tuple[str, ...]
    timeout: float
    check: bool
    cwd: Path | None = None
    env: Mapping[str, str] | None = field(default=None)


def _execute(options: _RunOptions) -> SubprocessResult:
    """Run *options.command* under :func:`subprocess.run` with capture."""
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(options.command),
            capture_output=True,
            text=True,
            timeout=options.timeout,
            cwd=options.cwd,
            env=dict(options.env) if options.env is not None else None,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SubprocessTimeoutError(options.command, options.timeout) from exc
    elapsed = time.monotonic() - started

    if options.check and completed.returncode != 0:
        raise SubprocessFailedError(
            options.command,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )

    return SubprocessResult(
        command=options.command,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        elapsed_seconds=elapsed,
    )


def run(
    command: Sequence[str | os.PathLike[str]],
    *,
    timeout: float = DEFAULT_KICAD_TIMEOUT,
    check: bool = True,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> SubprocessResult:
    """Execute *command* and return a :class:`SubprocessResult`.

    Args:
        command: Argv to execute. Path-like elements are stringified.
        timeout: Per-step timeout in seconds. Defaults to
            :data:`DEFAULT_KICAD_TIMEOUT`; callers invoking git should
            pass :data:`DEFAULT_GIT_TIMEOUT`.
        check: When ``True`` (default), a non-zero return raises
            :exc:`SubprocessFailedError`. When ``False`` the result is
            returned as-is.
        cwd: Optional working directory.
        env: Optional environment mapping forwarded to subprocess.

    Returns:
        A populated :class:`SubprocessResult`.

    Raises:
        SubprocessTimeoutError: When the subprocess exceeds *timeout*.
        SubprocessFailedError: When ``check`` is ``True`` and the
            subprocess returns a non-zero exit code.
        KeyboardInterrupt: Propagated unchanged.
    """
    resolved = _RunOptions(
        command=tuple(str(arg) for arg in command),
        timeout=timeout,
        check=check,
        cwd=cwd,
        env=env,
    )
    return _execute(resolved)
