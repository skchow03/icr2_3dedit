"""Lossless file loading and saving for Papyrus .3D source."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import tempfile


def _newline_style(raw: bytes) -> str:
    if b"\r\n" in raw:
        return "\r\n"
    if b"\r" in raw:
        return "\r"
    return "\n"


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def atomic_write(destination: Path, data: bytes) -> None:
    """Durably stage bytes beside destination, then atomically replace it."""
    temporary: Path | None = None
    try:
        descriptor, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass(slots=True)
class SourceDocument:
    """Normalized editor text and the exact last successful byte baseline."""

    text: str
    path: Path | None = None
    encoding: str = "utf-8"
    newline: str = "\n"
    has_utf8_bom: bool = False
    original_bytes: bytes = b""
    clean_text: str = field(default="")

    def __post_init__(self) -> None:
        self.text = _normalize_newlines(self.text)
        if not self.clean_text:
            self.clean_text = self.text

    @property
    def dirty(self) -> bool:
        return self.text != self.clean_text

    @classmethod
    def load(cls, path: str | Path) -> "SourceDocument":
        source_path = Path(path)
        raw = source_path.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        try:
            text = raw.decode("utf-8-sig" if bom else "utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
            encoding = "cp1252"
        normalized = _normalize_newlines(text)
        return cls(normalized, source_path, encoding, _newline_style(raw), bom, raw, normalized)

    def save(self, path: str | Path | None = None) -> Path:
        destination = Path(path) if path is not None else self.path
        if destination is None:
            raise ValueError("A destination is required for an untitled document")
        if self.text == self.clean_text and self.original_bytes:
            data = self.original_bytes
        else:
            external_text = self.text.replace("\n", self.newline)
            data = external_text.encode(self.encoding)
            if self.has_utf8_bom and self.encoding == "utf-8":
                data = b"\xef\xbb\xbf" + data
        atomic_write(destination, data)
        self.path = destination
        self.original_bytes = data
        self.clean_text = self.text
        return destination
