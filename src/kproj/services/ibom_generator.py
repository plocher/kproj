"""The :class:`IbomGenerator` service.

Per ``docs/adr/0008-ibom-direct-script-invocation.md`` +
``docs/DESIGN.md`` § *IbomGenerator*, this service invokes the
``generate_interactive_bom.py`` PCM-installed script directly via
``subprocess.run`` rather than via ``kicad-cli jobset run``. The
``kicad-cli`` job runner requires a live KiCad GUI process, which
contradicts kproj's locked non-interactive Makefile / CI use case
(ADR 0007).

The argv, fixed by ADR 0008:

    <python> <ibom_script>
        --no-browser --no-compression
        --dest-dir <staging>
        --name-format <P>-<R>.ibom
        --extra-data-file <pcb>
        --dnp-field kicad_dnp
        --extra-fields MPN,Manufacturer
        --include-tracks
        <pcb>

``<python>`` is :data:`sys.executable` (kproj's own interpreter, so
the iBOM script runs in the kproj venv environment). ``<ibom_script>``
is resolved by :func:`kproj.common.kicad_install.find_ibom_script`
during pre-flight and injected at construction time.

The script writes ``<staging>/<name-format>.html``. The service moves
that file to the caller's *output_file* via :func:`os.replace` so the
release-asset filename is independent of the iBOM staging directory.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

from ..common.subprocess_runner import DEFAULT_KICAD_TIMEOUT
from ..common.subprocess_runner import run as subprocess_run
from ..model.export_result import ExportResult
from .change_journal import ChangeJournal


class IbomGenerator:
    """Interactive HTML BOM generator.

    Invokes the PCM-installed ``generate_interactive_bom.py`` script
    per ADR 0008.
    """

    def __init__(self, ibom_script: Path) -> None:
        """Construct an iBOM generator.

        Args:
            ibom_script: Path to ``generate_interactive_bom.py``, as
                resolved by
                :func:`kproj.common.kicad_install.find_ibom_script`
                during pre-flight.
        """
        self._ibom_script = ibom_script

    def generate(
        self,
        pcb_path: Path,
        output_file: Path,
        name_format: str,
        *,
        journal: ChangeJournal | None = None,
    ) -> ExportResult:
        """Generate the interactive HTML BOM for *pcb_path*.

        Args:
            pcb_path: Path to the source ``.kicad_pcb``. iBOM is
                directed at it twice — once via ``--extra-data-file``
                (for the variants / properties data extraction) and
                once as the positional argument.
            output_file: Final HTML path. iBOM is allowed to write
                into a private staging directory and the produced
                HTML is then atomically moved here.
            name_format: The ``--name-format`` value to pass iBOM.
                iBOM writes ``<dest-dir>/<name_format>.html``; the
                ``.ibom`` suffix is part of *name_format* per
                ``docs/DESIGN.md`` § *Release asset set*.
            journal: Optional open :class:`ChangeJournal`.

        Returns:
            A populated :class:`ExportResult` carrying the invoked
            argv, elapsed time, and the final *output_file* path.

        Raises:
            FileNotFoundError: When iBOM exits 0 but did not produce
                the expected ``<dest-dir>/<name_format>.html`` file.
            SubprocessFailedError: When iBOM exits non-zero.
            SubprocessTimeoutError: When iBOM exceeds the
                ``DEFAULT_KICAD_TIMEOUT``.
        """
        output_file.parent.mkdir(parents=True, exist_ok=True)
        if journal is not None:
            journal.will_create(output_file)

        with tempfile.TemporaryDirectory(prefix="kproj-ibom-") as staging:
            staging_dir = Path(staging)
            argv = [
                sys.executable,
                str(self._ibom_script),
                "--no-browser",
                "--no-compression",
                "--dest-dir",
                str(staging_dir),
                "--name-format",
                name_format,
                "--extra-data-file",
                str(pcb_path),
                "--dnp-field",
                "kicad_dnp",
                "--extra-fields",
                "MPN,Manufacturer",
                "--include-tracks",
                str(pcb_path),
            ]
            started = time.monotonic()
            result = subprocess_run(argv, timeout=DEFAULT_KICAD_TIMEOUT, check=True)
            elapsed = time.monotonic() - started

            produced = staging_dir / f"{name_format}.html"
            if not produced.is_file():
                raise FileNotFoundError(
                    f"iBOM exited 0 but produced no HTML at {produced}; "
                    f"check the iBOM script ({self._ibom_script}) is the one shipped by PCM."
                )
            os.replace(produced, output_file)

        return ExportResult(
            path=output_file,
            command=result.command,
            elapsed_seconds=elapsed,
        )
