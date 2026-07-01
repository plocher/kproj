"""The :class:`Finding` value object.

A single quality-lint finding (audit, DRC, or ERC). Frozen dataclass per
``docs/GLOSSARY.md`` § *Finding* and jBOM's Diagnostic Collection
Principle (ADR 0001).
"""

from __future__ import annotations

from dataclasses import dataclass

from .severity import Severity


@dataclass(frozen=True)
class Finding:
    """A single quality-lint finding.

    Attributes:
        severity: One of :class:`Severity`.
        field: Symbolic name of the rule that produced the finding
            (e.g. ``"comment9_missing"``, ``"silk_overlap"``).
        value: The offending value or location string. May be empty
            when the rule's trigger is the absence of a value.  For
            DRC/ERC findings, this carries the KiCad-side location
            (coordinate / uuid / sheet) per the wave-3 fix-up.
        reason: Human-readable explanation suitable for stderr +
            Markdown-table rendering.
        project: Project basename when known; empty string otherwise.
            Allows merging Findings from multiple projects in batch
            contexts without loss of origin.
        location_hint: Optional KiCad-side locator (layer name, etc.)
            when ``value`` is the primary location.  Stays empty by
            default.
        source: Origin category of the finding.  Closed taxonomy:
            ``"audit"`` (MetadataAnalyzer), ``"drc"`` /
            ``"erc"`` (DesignAnalyzer), ``"read"`` (read-time
            diagnostics from KicadProjectReader), or empty for
            unspecified / legacy callers.  Drives source-specific
            counting in :class:`FrontMatterSummaryFormatter` and
            section discrimination in :class:`MarkdownTableFormatter`
            (wave-3 M2 fix-up).
    """

    severity: Severity
    field: str
    value: str
    reason: str
    project: str = ""
    location_hint: str = ""
    source: str = ""
