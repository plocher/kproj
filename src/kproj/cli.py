"""kproj CLI entry point.

Not implemented yet — Phase 6 is the TDD/implementation phase. This module
exists so the `kproj` console script wires up cleanly after `uv pip install -e .`
or equivalent, and so the Phase 3 PRD can reference a concrete entry point.

See docs/CONTEXT.md for the locked v1 contract.
"""

from __future__ import annotations

import sys


def main() -> int:
    """kproj CLI entry point (placeholder)."""
    print("kproj v0.1.0 — not yet implemented", file=sys.stderr)
    print("See docs/CONTEXT.md for the locked v1 contract.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
