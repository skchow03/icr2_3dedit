"""Conservative, source-range-preserving Papyrus structure parser."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from .syntax import COMMANDS, IDENTIFIER_PATTERN, IdentifierToken, command_at_start, identifier_tokens


LEADING_TRIVIA = r"(?:(?:\s+)|(?:[ \t]*%[^\r\n]*(?:\r?\n|$)))*"
DEFINITION_RE = re.compile(
    rf"^{LEADING_TRIVIA}({IDENTIFIER_PATTERN})\s*:\s*(.*?)\s*;\s*$", re.DOTALL
)
DEFINITION_LIKE_RE = re.compile(rf"^{LEADING_TRIVIA}{IDENTIFIER_PATTERN}\s*:", re.DOTALL)
HEADER_RE = re.compile(r"^\s*3D\s+VERSION\s+3\.0\s*;", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParseIssue:
    code: str
    message: str
    start: int
    end: int
    line: int
    warning: bool = False


@dataclass(slots=True)
class Statement:
    text: str
    start: int
    end: int
    line: int
    name: str | None = None
    name_start: int | None = None
    name_end: int | None = None
    rhs: str | None = None
    rhs_start: int | None = None
    rhs_end: int | None = None
    kind: str = "statement"
    references: tuple[str, ...] = ()
    reference_tokens: tuple[IdentifierToken, ...] = ()


@dataclass(slots=True)
class ParsedDocument:
    source: str
    statements: list[Statement]
    definitions: dict[str, Statement]
    duplicates: dict[str, list[Statement]] = field(default_factory=dict)
    inline_comment_lines: tuple[int, ...] = ()
    issues: tuple[ParseIssue, ...] = ()

    def statement_at(self, offset: int) -> Statement | None:
        return next((s for s in self.statements if s.start <= offset < s.end), None)

    def references_to(self, name: str) -> list[Statement]:
        return [s for s in self.statements if name in s.references]

    def reference_tokens_to(self, name: str) -> list[IdentifierToken]:
        return [token for s in self.statements for token in s.reference_tokens if token.name == name]


def _line(source: str, offset: int) -> int:
    return source.count("\n", 0, offset) + 1


def _scan(source: str) -> tuple[list[tuple[int, int, bool]], list[ParseIssue]]:
    """Split at semicolons outside quotes/comments and report lexical endings."""
    ranges: list[tuple[int, int, bool]] = []
    issues: list[ParseIssue] = []
    start = index = 0
    quote: str | None = None
    quote_start = 0
    comment = False
    line_nonspace = False
    while index < len(source):
        char = source[index]
        if comment:
            if char in "\r\n":
                comment = False
                line_nonspace = False
            index += 1
            continue
        if quote:
            if char == "\\" and index + 1 < len(source):
                index += 2
                continue
            if char == quote:
                quote = None
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
            quote, quote_start = char, index
        elif char == ";":
            ranges.append((start, index + 1, True))
            start = index + 1
        index += 1
    if quote:
        issues.append(ParseIssue("unterminated-quote", "Unterminated quoted string", quote_start, len(source), _line(source, quote_start)))
    if start < len(source):
        ranges.append((start, len(source), False))
        remainder = source[start:]
        meaningful = [line for line in remainder.splitlines() if line.strip() and not line.lstrip().startswith("%")]
        if meaningful:
            pos = start + next((i for i, c in enumerate(remainder) if not c.isspace()), 0)
            issues.append(ParseIssue("unterminated-statement", "Unterminated statement or missing semicolon", pos, len(source), _line(source, pos)))
    return ranges, issues


def _infer_kind(rhs: str) -> str:
    stripped = rhs.strip()
    if stripped.upper() == "NIL":
        return "NIL"
    if re.match(r"^\[\s*<", stripped):
        return "vertex"
    return command_at_start(stripped) or "value"


def parse_document(source: str) -> ParsedDocument:
    statements: list[Statement] = []
    definitions: dict[str, Statement] = {}
    duplicates: dict[str, list[Statement]] = {}
    ranges, issues = _scan(source)
    if not HEADER_RE.match(source):
        issues.append(ParseIssue("invalid-header", "Missing or invalid '3D VERSION 3.0;' header", 0, min(len(source), source.find("\n") if "\n" in source else len(source)), 1))

    inline_lines = tuple(i for i, line in enumerate(source.splitlines(), 1) if _has_inline_percent(line))
    for start, end, terminated in ranges:
        text = source[start:end]
        definition = DEFINITION_RE.match(text) if terminated else None
        statement = Statement(text, start, end, _line(source, start))
        if definition:
            statement.name = definition.group(1)
            statement.name_start = start + definition.start(1)
            statement.name_end = start + definition.end(1)
            statement.rhs = definition.group(2)
            statement.rhs_start = start + definition.start(2)
            statement.rhs_end = start + definition.end(2)
            statement.kind = _infer_kind(statement.rhs)
            statement.line = _line(source, statement.name_start)
            rhs_start = statement.rhs_start
            tokens = tuple(t for t in identifier_tokens(statement.rhs, rhs_start) if t.name != statement.name)
            statement.reference_tokens = tokens
            if statement.name in definitions:
                duplicates.setdefault(statement.name, [definitions[statement.name]]).append(statement)
            else:
                definitions[statement.name] = statement
            leading = re.match(rf"^\s*({IDENTIFIER_PATTERN})\b", statement.rhs)
            raw_command = leading.group(1) if leading else None
            if raw_command and raw_command == raw_command.upper() and raw_command not in COMMANDS:
                command_start = rhs_start + leading.start(1)
                issues.append(ParseIssue("unknown-command", f"Unknown command: {raw_command}", command_start, command_start + len(raw_command), _line(source, command_start), True))
        elif DEFINITION_LIKE_RE.match(text):
            issues.append(ParseIssue("invalid-definition", "Definition-like statement could not be parsed", start, end, _line(source, start)))
        statements.append(statement)

    known = set(definitions)
    for statement in statements:
        statement.references = tuple(dict.fromkeys(t.name for t in statement.reference_tokens if t.name in known))
    return ParsedDocument(source, statements, definitions, duplicates, inline_lines, tuple(issues))


def identifier_candidates(rhs: str) -> tuple[str, ...]:
    """Compatibility helper returning lexically plausible references."""
    return tuple(dict.fromkeys(token.name for token in identifier_tokens(rhs)))


def _has_inline_percent(line: str) -> bool:
    quote: str | None = None
    for index, char in enumerate(line):
        if quote:
            if char == quote and (index == 0 or line[index - 1] != "\\"):
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "%":
            return bool(line[:index].strip())
    return False
