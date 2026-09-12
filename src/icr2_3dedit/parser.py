"""Conservative parsing for structure and navigation.

This is not yet a complete Papyrus grammar. It divides the source into
semicolon-terminated statements while preserving their exact source ranges,
then recognizes definitions without rebuilding or normalizing the source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re


IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_]*"
LEADING_TRIVIA = r"(?:(?:\s+)|(?://[^\r\n]*(?:\r?\n|$))|(?:/\*.*?\*/))*"
DEFINITION_RE = re.compile(
    rf"^{LEADING_TRIVIA}({IDENTIFIER})\s*:\s*(.*?)\s*;\s*$",
    re.DOTALL,
)
REFERENCE_RE = re.compile(rf"\b({IDENTIFIER})\b")
COMMAND_RE = re.compile(rf"^\s*({IDENTIFIER})\b")

RESERVED_WORDS = {
    "and", "or", "not", "nil", "true", "false", "version",
    "poly", "polygon", "list", "bsp", "dynamic", "superobj", "switch",
}


@dataclass(slots=True)
class Statement:
    text: str
    start: int
    end: int
    line: int
    name: str | None = None
    rhs: str | None = None
    kind: str = "statement"
    references: tuple[str, ...] = ()


@dataclass(slots=True)
class ParsedDocument:
    source: str
    statements: list[Statement]
    definitions: dict[str, Statement]
    duplicates: dict[str, list[Statement]] = field(default_factory=dict)

    def statement_at(self, offset: int) -> Statement | None:
        for statement in self.statements:
            if statement.start <= offset < statement.end:
                return statement
        return None

    def references_to(self, name: str) -> list[Statement]:
        return [s for s in self.statements if name in s.references]


def _split_statements(source: str) -> list[tuple[int, int]]:
    """Return source ranges ending at semicolons outside quotes/comments."""

    ranges: list[tuple[int, int]] = []
    start = 0
    index = 0
    quote: str | None = None
    line_comment = False
    block_comment = False

    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""

        if line_comment:
            if char in "\r\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and following == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
            continue
        if char == "/" and following == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and following == "*":
            block_comment = True
            index += 2
            continue
        if char in "\"'":
            quote = char
            index += 1
            continue
        if char == ";":
            ranges.append((start, index + 1))
            start = index + 1
        index += 1

    # Preserve trailing whitespace/comments as a trivia statement. This makes
    # concatenating statement text reproduce the source byte-for-byte after
    # decoding, including a final newline.
    if start < len(source):
        ranges.append((start, len(source)))
    return ranges


def _infer_kind(rhs: str) -> str:
    stripped = rhs.strip()
    if stripped.upper() == "NIL":
        return "NIL"
    if re.match(r"^\[\s*<", stripped):
        return "vertex"
    command = COMMAND_RE.match(stripped)
    return command.group(1).upper() if command else "value"


def parse_document(source: str) -> ParsedDocument:
    statements: list[Statement] = []
    definitions: dict[str, Statement] = {}
    duplicates: dict[str, list[Statement]] = {}

    for start, end in _split_statements(source):
        text = source[start:end]
        definition = DEFINITION_RE.match(text)
        line = source.count("\n", 0, start) + 1
        statement = Statement(text=text, start=start, end=end, line=line)
        if definition:
            statement.name = definition.group(1)
            statement.rhs = definition.group(2)
            statement.kind = _infer_kind(statement.rhs)
            statement.line += text.count("\n", 0, definition.start(1))
            if statement.name in definitions:
                duplicates.setdefault(statement.name, [definitions[statement.name]]).append(statement)
            else:
                definitions[statement.name] = statement
        statements.append(statement)

    known_names = set(definitions)
    for statement in statements:
        if statement.rhs is None:
            continue
        candidates = REFERENCE_RE.findall(statement.rhs)
        statement.references = tuple(
            dict.fromkeys(
                candidate for candidate in candidates
                if candidate in known_names and candidate != statement.name
            )
        )

    return ParsedDocument(source, statements, definitions, duplicates)


def identifier_candidates(rhs: str) -> tuple[str, ...]:
    """Identifiers that might be references, including unresolved names."""

    candidates = REFERENCE_RE.findall(rhs)
    return tuple(
        dict.fromkeys(name for name in candidates if name.lower() not in RESERVED_WORDS)
    )
