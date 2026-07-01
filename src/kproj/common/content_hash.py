"""Content-hash helpers for the M11 title-block-only refresh detection.

Per ``docs/PRD.md`` § *Story 6 — status transitions are cheap*, changing
only the schematic ${COMMENT9} value must trigger a metadata refresh
(front-matter update), not a full artifact regeneration.  Wave-3 M1
introduced an asset-freshness safety net that compares asset mtimes
against source mtimes; that safety net was correct for genuine design
edits but caught title-block-only edits as false-positive stale-asset
signals.

Wave-3 M11 round-2 threads a **title-block-stripped content hash**
through the publish pipeline: at publish time the workflow computes
``sha256(schematic_content_minus_title_block)`` and
``sha256(pcb_content_minus_title_block)`` and persists them in the
version-page YAML front-matter.  On a subsequent run the workflow reads
back the persisted hashes and compares them to the current file hashes:

- Hash unchanged -> the edit is title-block-only (or purely a comment
  change inside the ``(title_block ...)`` subtree).  The M1 stale-asset
  escalation is skipped and the outcome stays ``refresh`` / ``noop``.
- Hash changed -> real schematic-content edit.  The M1 escalation runs
  as before and the outcome becomes ``publish``.

The stripping walks the S-expression paren tree rather than a regex so
nested parens inside the title-block (e.g. ``(comment 9 "hello (world)")``)
are handled correctly.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_TITLE_BLOCK_TOKEN = "(title_block"


def _strip_title_block(content: str) -> str:
    """Remove every ``(title_block ...)`` subtree from *content*.

    Walks the S-expression paren tree so nested parens inside a
    ``(comment N "...(...)")`` field are handled correctly.  The
    surrounding whitespace is left intact; only the ``(title_block``
    open-paren through its matching close-paren is elided.

    Args:
        content: Raw KiCad ``.kicad_sch`` / ``.kicad_pcb`` text.

    Returns:
        *content* with every ``(title_block ...)`` subtree replaced by
        an empty string.
    """
    if _TITLE_BLOCK_TOKEN not in content:
        return content

    output: list[str] = []
    i = 0
    n = len(content)
    while i < n:
        idx = content.find(_TITLE_BLOCK_TOKEN, i)
        if idx == -1:
            output.append(content[i:])
            break
        # Confirm the token boundary: the character after ``title_block``
        # must be whitespace or a close-paren so we don't accidentally
        # match a hypothetical ``(title_block_something ...)``.
        after = idx + len(_TITLE_BLOCK_TOKEN)
        if after < n and content[after] not in " \t\n\r)":
            output.append(content[i : idx + 1])
            i = idx + 1
            continue
        # Everything up to the ``(`` of the token stays.
        output.append(content[i:idx])
        depth = 1
        k = after
        # Walk forward until the matching close-paren, honouring nested
        # parens and skipping over the interior of double-quoted strings
        # so a paren inside a quoted comment doesn't confuse the counter.
        while k < n and depth > 0:
            c = content[k]
            if c == '"':
                k = _skip_quoted_string(content, k)
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            k += 1
        i = k
    return "".join(output)


def _skip_quoted_string(content: str, start: int) -> int:
    """Return the index just past the closing quote of a KiCad quoted string.

    Args:
        content: The full S-expression text.
        start: Index of the opening ``"`` character.

    Returns:
        Index of the character immediately after the matching close
        quote.  Escapes (``\\"``, ``\\\\``) are honoured so an escaped
        quote does not terminate the string.
    """
    k = start + 1
    n = len(content)
    while k < n:
        c = content[k]
        if c == "\\" and k + 1 < n:
            k += 2
            continue
        if c == '"':
            return k + 1
        k += 1
    return k


def content_hash_excluding_title_block(path: Path) -> str:
    """Return the SHA-256 hex-digest of *path* with title-block subtrees stripped.

    Reads *path* as UTF-8 text, strips every ``(title_block ...)``
    subtree, then hashes the remainder.  A non-existent or unreadable
    file yields the empty-string sentinel ``""`` so the caller can
    distinguish "no captured hash" from "captured but different".

    Args:
        path: A KiCad ``.kicad_sch`` or ``.kicad_pcb`` file.

    Returns:
        The lowercase-hex SHA-256 digest, or ``""`` when *path* cannot
        be read.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    stripped = _strip_title_block(text)
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()
