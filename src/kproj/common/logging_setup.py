"""Kproj logging configuration.

Per ``docs/DESIGN.md`` § *Verbosity* and PRD Story 12, this module maps
the CLI's ``-v`` / ``-d`` flags to the ``kproj`` root logger's level and
attaches a compact stderr handler.  It is invoked once from
:func:`kproj.cli.main` before :meth:`PublishWorkflow.run`.

The configuration is deliberately scoped to the ``kproj`` logger:
third-party loggers (``jbom``, ``urllib3``, ...) keep whatever level
they had on entry so a ``-d`` run does not turn into a firehose from
unrelated libraries.  Callers within kproj obtain a module logger via
``_log = logging.getLogger(__name__)``; because every kproj module lives
under the ``kproj`` package, they all inherit the configured level.
"""

from __future__ import annotations

import logging
import sys

_KPROJ_LOGGER_NAME = "kproj"
"""The kproj root logger.  Every ``logging.getLogger(__name__)`` inside the
``kproj`` package is a descendant of this logger and inherits its level +
handlers when propagation is enabled (the default)."""

_LOG_FORMAT = "kproj [%(levelname)s] %(message)s"
"""Compact stderr format: level in brackets, then the message.  Matches
the one-liner shape of :class:`~kproj.formatters.stderr_formatter.StderrFormatter`
so mixed output stays scan-friendly."""

_HANDLER_ATTR = "_kproj_stderr_handler"
"""Marker attribute on the stderr handler so repeat calls to
:func:`configure` (e.g. tests, or a future long-lived host process) do not
stack duplicate handlers on the kproj logger."""


def configure(*, verbose_level: int, debug: bool) -> None:
    """Configure the ``kproj`` logger from CLI flags.

    Args:
        verbose_level: The ``count`` value of the ``-v`` / ``--verbose``
            flag.  ``>=1`` sets the logger to ``INFO``.
        debug: The ``-d`` / ``--debug`` flag.  ``True`` sets the logger
            to ``DEBUG`` (overrides ``verbose_level``).

    Behaviour:
        Level baseline is ``WARNING``.  ``-v`` -> ``INFO``.  ``-d`` ->
        ``DEBUG``.  A single ``StreamHandler`` writing to ``sys.stderr``
        is attached to the ``kproj`` logger; propagation to the root
        logger is disabled so kproj lines do not double-print when a
        host application configures its own handlers.  The handler is
        idempotent: repeat calls replace the previous handler rather
        than stacking.
    """
    level = _level_for(verbose_level=verbose_level, debug=debug)
    logger = logging.getLogger(_KPROJ_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False

    handler = _get_or_create_handler(logger)
    handler.setLevel(level)


def _level_for(*, verbose_level: int, debug: bool) -> int:
    """Map CLI flags to a :mod:`logging` level integer.

    ``-d`` wins over ``-v`` (``debug=True`` always means DEBUG regardless
    of ``verbose_level``).  ``-v`` alone means INFO.  Baseline is
    WARNING so findings + failures still surface at default verbosity.
    """
    if debug:
        return logging.DEBUG
    if verbose_level >= 1:
        return logging.INFO
    return logging.WARNING


def _get_or_create_handler(logger: logging.Logger) -> logging.Handler:
    """Return the kproj stderr handler, creating it if it does not exist.

    Marked with a private attribute so repeat :func:`configure` calls
    reuse the same handler instead of stacking new ones.
    """
    for existing in logger.handlers:
        if getattr(existing, _HANDLER_ATTR, False):
            return existing
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    setattr(handler, _HANDLER_ATTR, True)
    logger.addHandler(handler)
    return handler
