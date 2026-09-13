"""ICR2 structure-aware .3D editor."""

from .document import SourceDocument
from .parser import ParsedDocument, Statement, parse_document
from .threedfile import ThreeDFile

__all__ = ["ParsedDocument", "SourceDocument", "Statement", "ThreeDFile", "parse_document"]
__version__ = "0.1.0"

