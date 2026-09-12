"""Tolerant, nesting-aware and source-backed Papyrus parser."""

from __future__ import annotations

from dataclasses import dataclass, field

from .syntax import (COMMANDS, KEYWORDS, RECORD_FIELDS, IdentifierToken, Token,
                     TokenKind, command_at_start, tokenize)

OPEN_TO_CLOSE = {"{": "}", "(": ")", "[": "]", "<": ">"}
MAX_PARSE_ISSUES = 100


@dataclass(frozen=True, slots=True)
class ParseIssue:
    code: str
    message: str
    start: int
    end: int
    line: int
    warning: bool = False


@dataclass(slots=True)
class SyntaxGroup:
    """A delimiter pair; children are tokens or nested groups."""
    opener: Token
    closer: Token | None = None
    children: list[Token | "SyntaxGroup"] = field(default_factory=list)

    @property
    def start(self) -> int:
        return self.opener.start

    @property
    def end(self) -> int:
        return self.closer.end if self.closer else (self.children[-1].end if self.children else self.opener.end)


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
    tokens: tuple[Token, ...] = ()
    syntax: tuple[Token | SyntaxGroup, ...] = ()


@dataclass(slots=True)
class ParsedDocument:
    source: str
    statements: list[Statement]
    definitions: dict[str, Statement]
    duplicates: dict[str, list[Statement]] = field(default_factory=dict)
    inline_comment_lines: tuple[int, ...] = ()
    issues: tuple[ParseIssue, ...] = ()
    tokens: tuple[Token, ...] = ()
    header: Statement | None = None
    max_nesting_depth: int = 0

    def statement_at(self, offset: int) -> Statement | None:
        return next((s for s in self.statements if s.start <= offset < s.end), None)

    def references_to(self, name: str) -> list[Statement]:
        return [s for s in self.statements if name in s.references]

    def reference_tokens_to(self, name: str) -> list[IdentifierToken]:
        return [t for s in self.statements for t in s.reference_tokens if t.name == name]


def _significant(tokens: tuple[Token, ...] | list[Token]) -> list[Token]:
    return [t for t in tokens if t.kind not in (TokenKind.WHITESPACE, TokenKind.COMMENT)]


def _header_end(source: str, tokens: tuple[Token, ...]) -> int | None:
    significant = _significant(tokens)
    if len(significant) < 3:
        return None
    first = significant[:3]
    if not (first[0].text.upper() == "3D" and first[1].text.upper() == "VERSION" and first[2].text == "3.0"):
        return None
    end = first[2].end
    if len(significant) > 3 and significant[3].kind is TokenKind.SEMICOLON:
        return significant[3].end
    # A semicolon-free header is line-oriented and must never consume definition 1.
    newline = source.find("\n", end)
    return len(source) if newline < 0 else newline


def _nest(tokens: tuple[Token, ...], issues: list[ParseIssue]) -> tuple[tuple[Token | SyntaxGroup, ...], int]:
    roots: list[Token | SyntaxGroup] = []
    containers: list[list[Token | SyntaxGroup]] = [roots]
    groups: list[SyntaxGroup] = []
    maximum = 0
    for token in tokens:
        if token.kind is TokenKind.OPEN:
            group = SyntaxGroup(token)
            containers[-1].append(group)
            groups.append(group)
            containers.append(group.children)
            # Angle tuples are leaves within the enclosing structural containers.
            # Track container depth while still balancing/representing ``<>``.
            maximum = max(maximum, sum(g.opener.text != "<" for g in groups))
        elif token.kind is TokenKind.CLOSE and groups and OPEN_TO_CLOSE[groups[-1].opener.text] == token.text:
            groups[-1].closer = token
            groups.pop()
            containers.pop()
        elif token.kind is TokenKind.CLOSE and token.text != ">":
            if len(issues) < MAX_PARSE_ISSUES:
                issues.append(ParseIssue("unmatched-close", f"Unmatched closing delimiter {token.text!r}", token.start, token.end, token.line))
            containers[-1].append(token)
        else:
            # A bare '>' is the SWITCH comparison operator, not an unmatched close.
            containers[-1].append(token)
    for group in groups:
        if len(issues) >= MAX_PARSE_ISSUES:
            break
        issues.append(ParseIssue("unclosed-delimiter", f"Unclosed delimiter {group.opener.text!r}", group.start, group.opener.end, group.opener.line))
    return tuple(roots), maximum


def _statement_ranges(tokens: tuple[Token, ...], body_start: int, source_length: int) -> list[tuple[int, int, bool]]:
    ranges: list[tuple[int, int, bool]] = []
    start, stack = body_start, []
    for token in tokens:
        if token.end <= body_start:
            continue
        if token.kind is TokenKind.OPEN:
            stack.append(token.text)
        elif token.kind is TokenKind.CLOSE and stack and OPEN_TO_CLOSE[stack[-1]] == token.text:
            stack.pop()
        elif token.kind is TokenKind.SEMICOLON and not stack:
            ranges.append((start, token.end, True))
            start = token.end
    if start < source_length:
        ranges.append((start, source_length, False))
    return ranges


def _infer_kind(rhs_tokens: list[Token]) -> str:
    if not rhs_tokens:
        return "value"
    first = rhs_tokens[0]
    if first.kind is TokenKind.IDENTIFIER:
        upper = first.text.upper()
        return upper if upper in COMMANDS else "value"
    if first.text == "[":
        fields = {rhs_tokens[i - 1].text.casefold() for i, token in enumerate(rhs_tokens)
                  if token.kind is TokenKind.EQUALS and i and rhs_tokens[i - 1].kind is TokenKind.IDENTIFIER}
        # A texture suffix still describes a position.  Colour/material records do not.
        return "vertex" if not fields or fields <= {"t"} else "record"
    return "value"


def _reference_tokens(tokens: list[Token], definition_name: str) -> tuple[IdentifierToken, ...]:
    result: list[IdentifierToken] = []
    for index, token in enumerate(tokens):
        if token.kind is not TokenKind.IDENTIFIER or token.text == definition_name:
            continue
        upper = token.text.upper()
        previous = tokens[index - 1] if index else None
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if upper in COMMANDS or upper in KEYWORDS or upper in RECORD_FIELDS:
            continue
        if previous is not None and previous.kind is TokenKind.DOT:  # member name
            continue
        if following is not None and following.kind is TokenKind.EQUALS:  # named argument/field
            continue
        result.append(IdentifierToken(token.text, token.start, token.end))
    return tuple(result)


def parse_document(source: str) -> ParsedDocument:
    tokens = tokenize(source)
    issues: list[ParseIssue] = []
    for token in tokens:
        if (token.kind is TokenKind.STRING and len(token.text) > 0 and
                (len(token.text) == 1 or token.text[-1] != token.text[0])):
            issues.append(ParseIssue("unterminated-quote", "Unterminated quoted string",
                                     token.start, token.end, token.line))
    syntax, maximum = _nest(tokens, issues)
    header_end = _header_end(source, tokens)
    header = None
    if header_end is None:
        issues.append(ParseIssue("invalid-header", "Missing or invalid '3D VERSION 3.0' header", 0, min(len(source), source.find("\n") if "\n" in source else len(source)), 1))
        body_start = 0
    else:
        header_tokens = tuple(t for t in tokens if t.start < header_end)
        header = Statement(source[:header_end], 0, header_end, 1, kind="header", tokens=header_tokens)
        body_start = header_end

    statements: list[Statement] = [header] if header else []
    definitions: dict[str, Statement] = {}
    duplicates: dict[str, list[Statement]] = {}
    token_cursor = 0
    while token_cursor < len(tokens) and tokens[token_cursor].end <= body_start:
        token_cursor += 1
    for start, end, terminated in _statement_ranges(tokens, body_start, len(source)):
        first_token = token_cursor
        while token_cursor < len(tokens) and tokens[token_cursor].end <= end:
            token_cursor += 1
        statement_tokens = tokens[first_token:token_cursor]
        significant = _significant(statement_tokens)
        statement = Statement(source[start:end], start, end, significant[0].line if significant else 1, tokens=statement_tokens)
        statement.syntax, _ = _nest(statement_tokens, [])
        colon_index = next((i for i, t in enumerate(significant) if t.kind is TokenKind.COLON), None)
        if terminated and colon_index == 1 and significant[0].kind is TokenKind.IDENTIFIER:
            name_token = significant[0]
            statement.name = name_token.text
            statement.name_start, statement.name_end, statement.line = name_token.start, name_token.end, name_token.line
            semicolon = significant[-1]
            rhs_tokens = significant[2:-1] if semicolon.kind is TokenKind.SEMICOLON else significant[2:]
            statement.rhs_start = significant[2].start if len(significant) > 2 else semicolon.start
            statement.rhs_end = semicolon.start
            statement.rhs = source[statement.rhs_start:statement.rhs_end]
            statement.kind = _infer_kind(rhs_tokens)
            statement.reference_tokens = _reference_tokens(rhs_tokens, statement.name)
            if statement.name in definitions:
                duplicates.setdefault(statement.name, [definitions[statement.name]]).append(statement)
            else:
                definitions[statement.name] = statement
            if rhs_tokens and rhs_tokens[0].kind is TokenKind.IDENTIFIER:
                raw = rhs_tokens[0].text
                if raw == raw.upper() and raw not in COMMANDS and raw not in KEYWORDS:
                    issues.append(ParseIssue("unknown-command", f"Unknown command: {raw}", rhs_tokens[0].start, rhs_tokens[0].end, rhs_tokens[0].line, True))
        elif terminated and colon_index is not None:
            issues.append(ParseIssue("invalid-definition", "Definition-like statement could not be parsed", start, end, statement.line))
        elif significant:
            issues.append(ParseIssue("unterminated-statement", "Unterminated statement or missing semicolon", significant[0].start, end, significant[0].line))
        statements.append(statement)

    known = set(definitions)
    for statement in statements:
        statement.references = tuple(dict.fromkeys(t.name for t in statement.reference_tokens if t.name in known))
    inline_lines = tuple(t.line for t in tokens if t.kind is TokenKind.COMMENT and source[source.rfind("\n", 0, t.start) + 1:t.start].strip())
    return ParsedDocument(source, statements, definitions, duplicates, inline_lines,
                          tuple(issues[:MAX_PARSE_ISSUES]), tokens, header, maximum)


def identifier_candidates(rhs: str) -> tuple[str, ...]:
    significant = _significant(tokenize(rhs))
    return tuple(dict.fromkeys(t.name for t in _reference_tokens(significant, "")))
