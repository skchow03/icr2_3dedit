"""Shared lexical knowledge for parsing and source highlighting."""

from __future__ import annotations

from dataclasses import dataclass
import re


COMMANDS = frozenset({
    "NIL", "POLY", "POLYGON", "LIST", "BSPF", "DYNAMIC", "DYNO",
    "SUPEROBJ", "SWITCH", "DATA", "EXTERN",
})
KEYWORDS = frozenset({"3D", "VERSION", "AND", "OR", "NOT", "TRUE", "FALSE"})
RESERVED_WORDS = COMMANDS | KEYWORDS
IDENTIFIER_PATTERN = r"[A-Za-z_][A-Za-z0-9_]*"
IDENTIFIER_RE = re.compile(IDENTIFIER_PATTERN)
COMMAND_PATTERN = re.compile(rf"^\s*({IDENTIFIER_PATTERN})\b")


@dataclass(frozen=True, slots=True)
class IdentifierToken:
    name: str
    start: int
    end: int


def identifier_tokens(text: str, offset: int = 0) -> tuple[IdentifierToken, ...]:
    """Return identifiers outside strings and full-line percent comments."""

    result: list[IdentifierToken] = []
    index = 0
    quote: str | None = None
    comment = False
    line_nonspace = False
    while index < len(text):
        char = text[index]
        if comment:
            if char in "\r\n":
                comment = False
                line_nonspace = False
            index += 1
            continue
        if quote:
            if char == "\\" and index + 1 < len(text):
                index += 2
                continue
            if char == quote:
                quote = None
            if char in "\r\n":
                line_nonspace = False
            index += 1
            continue
        if char in "\r\n":
            line_nonspace = False
            index += 1
            continue
        if char in " \t" and not line_nonspace:
            index += 1
            continue
        if char == "%" and not line_nonspace:
            comment = True
            index += 1
            continue
        line_nonspace = True
        if char in "\"'":
            quote = char
            index += 1
            continue
        match = IDENTIFIER_RE.match(text, index)
        if match and index and (text[index - 1].isalnum() or text[index - 1] == "_"):
            index += 1
            continue
        if match:
            name = match.group(0)
            if name.upper() not in RESERVED_WORDS:
                result.append(IdentifierToken(name, offset + match.start(), offset + match.end()))
            index = match.end()
            continue
        index += 1
    return tuple(result)


def command_at_start(rhs: str) -> str | None:
    match = COMMAND_PATTERN.match(rhs)
    return match.group(1).upper() if match else None
