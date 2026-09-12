"""ICR2 structure-aware .3D editor."""

from .document import SourceDocument
from .parser import ParsedDocument, Statement, parse_document

__all__ = ["ParsedDocument", "SourceDocument", "Statement", "parse_document"]
__version__ = "0.1.0"

