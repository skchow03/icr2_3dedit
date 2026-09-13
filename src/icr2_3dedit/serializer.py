"""Localized, lossless serialization for Papyrus ``.3D`` source.

The serializer never pretty-prints a document.  It applies explicit source-span
replacements and copies every untouched character directly from the source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True, order=True)
class ThreeDSourceEdit:
    """Replace ``source[start:end]`` with ``replacement``."""

    start: int
    end: int
    replacement: str

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError("edit start must not be negative")
        if self.end < self.start:
            raise ValueError("edit end must not precede edit start")


@dataclass(frozen=True, slots=True)
class ThreeDSerializationResult:
    """Serialized text plus inverse edits addressed to that resulting text."""

    text: str
    inverse_edits: tuple[ThreeDSourceEdit, ...]


class ThreeDSerializer:
    """Apply bounded replacements without regenerating untouched source."""

    @staticmethod
    def apply(
        source: str,
        edits: Iterable[ThreeDSourceEdit],
    ) -> ThreeDSerializationResult:
        ordered = tuple(sorted(edits, key=lambda edit: (edit.start, edit.end)))
        previous_end = 0
        for index, edit in enumerate(ordered):
            if edit.end > len(source):
                raise ValueError("edit extends beyond the source")
            if index and edit.start < previous_end:
                raise ValueError("source edits must not overlap")
            previous_end = edit.end

        pieces: list[str] = []
        inverse: list[ThreeDSourceEdit] = []
        cursor = 0
        result_offset = 0
        for edit in ordered:
            unchanged = source[cursor:edit.start]
            pieces.append(unchanged)
            result_offset += len(unchanged)

            replaced = source[edit.start:edit.end]
            pieces.append(edit.replacement)
            inverse.append(ThreeDSourceEdit(
                result_offset,
                result_offset + len(edit.replacement),
                replaced,
            ))
            result_offset += len(edit.replacement)
            cursor = edit.end

        pieces.append(source[cursor:])
        return ThreeDSerializationResult("".join(pieces), tuple(inverse))

    @staticmethod
    def encode(text: str, encoding: str, has_utf8_bom: bool = False) -> bytes:
        data = text.encode(encoding)
        if has_utf8_bom and encoding == "utf-8":
            return b"\xef\xbb\xbf" + data
        return data
