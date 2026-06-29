"""kproj domain services (the 11-service decomposition per DESIGN § Source layout).

Most services are foundation-slice stubs that raise :class:`NotImplementedError`
from their primary method. The two services that are fully implemented in this
slice are :class:`ChangeJournal` (ADR 0005) and :class:`ZipArchiver`.
"""

from __future__ import annotations

from .change_journal import ChangeJournal
from .design_analyzer import DesignAnalyzer
from .fab_packager import FabPackager
from .ibom_generator import IbomGenerator
from .kicad_project_reader import KicadProjectReader, ProjectResolutionError
from .metadata_analyzer import MetadataAnalyzer
from .pcb_exporter import PcbExporter
from .schematic_exporter import SchematicExporter
from .site_publisher import SitePublisher
from .source_packager import SourcePackager
from .zip_archiver import ZipArchiver

__all__ = [
    "ChangeJournal",
    "DesignAnalyzer",
    "FabPackager",
    "IbomGenerator",
    "KicadProjectReader",
    "MetadataAnalyzer",
    "PcbExporter",
    "ProjectResolutionError",
    "SchematicExporter",
    "SitePublisher",
    "SourcePackager",
    "ZipArchiver",
]
