"""Unit tests for :mod:`kproj.common.logging_setup`.

Validates the ``-v`` / ``-d`` -> kproj logger level mapping, the
handler-attachment contract (one stderr handler, no stacking on repeat
calls), and the isolation guarantee (third-party loggers untouched).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from kproj.common.logging_setup import _HANDLER_ATTR, _KPROJ_LOGGER_NAME, configure


@pytest.fixture(autouse=True)
def _reset_kproj_logger() -> Iterator[None]:
    """Snapshot + restore the kproj logger state around each test."""
    logger = logging.getLogger(_KPROJ_LOGGER_NAME)
    prior_level = logger.level
    prior_handlers = list(logger.handlers)
    prior_propagate = logger.propagate
    # Start each test from a known-clean baseline.
    for h in list(logger.handlers):
        logger.removeHandler(h)
    logger.setLevel(logging.WARNING)
    logger.propagate = True
    yield
    for h in list(logger.handlers):
        logger.removeHandler(h)
    for h in prior_handlers:
        logger.addHandler(h)
    logger.setLevel(prior_level)
    logger.propagate = prior_propagate


def test_baseline_no_flags_is_warning() -> None:
    """With no -v/-d, the kproj logger sits at WARNING (findings-only baseline)."""
    configure(verbose_level=0, debug=False)
    assert logging.getLogger(_KPROJ_LOGGER_NAME).level == logging.WARNING


def test_verbose_flag_is_info() -> None:
    """``-v`` (verbose_level >= 1) lifts the kproj logger to INFO."""
    configure(verbose_level=1, debug=False)
    assert logging.getLogger(_KPROJ_LOGGER_NAME).level == logging.INFO


def test_debug_flag_is_debug_and_overrides_verbose() -> None:
    """``-d`` sets DEBUG and wins even when ``-v`` is also present."""
    configure(verbose_level=2, debug=True)
    assert logging.getLogger(_KPROJ_LOGGER_NAME).level == logging.DEBUG


def test_configure_attaches_a_single_marked_stderr_handler() -> None:
    """Exactly one handler bearing the kproj marker is attached."""
    configure(verbose_level=1, debug=False)
    logger = logging.getLogger(_KPROJ_LOGGER_NAME)
    marked = [h for h in logger.handlers if getattr(h, _HANDLER_ATTR, False)]
    assert len(marked) == 1
    assert isinstance(marked[0], logging.StreamHandler)


def test_configure_is_idempotent_across_repeat_calls() -> None:
    """Repeated ``configure`` calls do not stack duplicate handlers."""
    configure(verbose_level=0, debug=False)
    configure(verbose_level=1, debug=False)
    configure(verbose_level=0, debug=True)
    logger = logging.getLogger(_KPROJ_LOGGER_NAME)
    marked = [h for h in logger.handlers if getattr(h, _HANDLER_ATTR, False)]
    assert len(marked) == 1


def test_third_party_loggers_unaffected(caplog: pytest.LogCaptureFixture) -> None:
    """The kproj configuration must not raise unrelated loggers to INFO/DEBUG.

    A third-party logger (here ``urllib3.connectionpool``) keeps its
    pre-configure level regardless of what kproj sets, so a ``-d`` run
    does not turn into a firehose from unrelated libraries.
    """
    third_party = logging.getLogger("urllib3.connectionpool")
    third_party.setLevel(logging.WARNING)
    configure(verbose_level=2, debug=True)
    assert third_party.level == logging.WARNING
