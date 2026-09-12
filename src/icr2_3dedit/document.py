"""Lossless file loading and saving for Papyrus .3D source."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SourceDocument:
    """The exact decoded text plus the encoding used to read it."""

    text: str
    path: Path | None = None
    encoding: str = "utf-8"

    @classmethod
    def load(cls, path: str | Path) -> "SourceDocument":
        source_path = Path(path)
        raw = source_path.read_bytes()
        try:
            text = raw.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
            encoding = "cp1252"
        return cls(text=text, path=source_path, encoding=encoding)

    def save(self, path: str | Path | None = None) -> Path:
        destination = Path(path) if path is not None else self.path
        if destination is None:
            raise ValueError("A destination is required for an untitled document")
        destination.write_bytes(self.text.encode(self.encoding))
        self.path = destination
        return destination

