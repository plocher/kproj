"""The :class:`PublishRequest` value object.

Bundles the inputs for one ``PublishWorkflow.run`` invocation.  Lives in
``model/`` (rather than alongside ``PublishWorkflow``) so services and
the workflow can share a single source of truth without circular
imports - addressing the wave-1 carry-forward note about
``PublishRequest`` / ``PublishResult`` location.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import KprojConfig


@dataclass(frozen=True)
class PublishRequest:
    """Inputs for one ``PublishWorkflow.run`` invocation.

    Attributes:
        project_arg: CLI positional - path to a ``.kicad_pro`` / dir /
            basename / ``"."``.  Resolved by
            ``KicadProjectReader.resolve``.
        config: Effective configuration after the precedence chain
            (``cli > env > yaml > default``).
        dry_run: ``True`` enables read-only mode (no writes, no git ops).
        verbose_level: ``0`` = quiet, ``1`` = ``-v``, ``2`` = ``-v -d``.
        debug: ``True`` enables implementation-private debug output;
            independent of :attr:`verbose_level`.
    """

    project_arg: str
    config: KprojConfig
    dry_run: bool = False
    verbose_level: int = 0
    debug: bool = False
