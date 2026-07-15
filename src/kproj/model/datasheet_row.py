"""The :class:`DatasheetRow` value object (kproj#36).

Per the kproj#36 owner ruling, the live ``jbom bom`` datasheet lookup
(:mod:`kproj.common.datasheet_library`) returns structured **per-reference**
rows rather than only a distinct-name list. This is general BOM-row
plumbing whose eventual consumer is the iBOM interactive-BOM viewer
(owner-stated destination; out of scope for kproj#36 itself), so the
shape intentionally carries one row per BOM reference rather than
collapsing to a single column up front.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasheetRow:
    """One per-reference row from the ``jbom bom`` datasheet lookup.

    Attributes:
        reference: The BOM reference designator (e.g. ``"R1"``).
        datasheet: The raw ``datasheet`` field value (typically a URL),
            as reported by jBOM. Empty when absent.
        datasheet_name: The curated ``Datasheet Name`` value (per the
            SPCoast-inventory document library's Never-Rename
            invariant). Empty for an uncurated reference.
        manufacturer: Inventory-resolved manufacturer name.
        mfgpn: Inventory-resolved manufacturer part number.
        mpn: Alias of :attr:`mfgpn` for downstream consumers that expect
            an ``MPN`` column label.
        fabricator_part_number: Inventory-resolved supplier/fabricator
            part number.
        description: Inventory-resolved component description.
        dnp: DNP marker value (typically ``"DNP"`` or empty string).
    """

    reference: str
    datasheet: str
    datasheet_name: str
    manufacturer: str = ""
    mfgpn: str = ""
    mpn: str = ""
    fabricator_part_number: str = ""
    description: str = ""
    dnp: str = ""
