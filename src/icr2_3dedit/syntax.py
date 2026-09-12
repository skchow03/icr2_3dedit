"""Lossless lexical primitives for Papyrus ``.3D`` source.

The lexer deliberately assigns a token to every byte of decoded source.  Parsing
can therefore attach meaning to spans without ever becoming a pretty-printer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


COMMANDS = frozenset({
    "NIL", "FACE", "POLY", "POLYGON", "LINE", "LIST", "BSPF", "BSPA",
    "MATERIAL", "DYNAMIC", "DYNO", "SUPEROBJ", "SWITCH", "DATA", "EXTERN",
})
KEYWORDS = frozenset({
    "3D", "VERSION", "AND", "OR", "NOT", "TRUE", "FALSE", "GROUP", "MIP",
    "DISTANCE",
})
RECORD_FIELDS = frozenset({"C", "T"})
RESERVED_WORDS = COMMANDS | KEYWORDS


class TokenKind(str, Enum):
    WHITESPACE = "whitespace"
    COMMENT = "comment"
    IDENTIFIER = "identifier"
    NUMBER = "number"
    STRING = "string"
    COMMA = "comma"
    SEMICOLON = "semicolon"
    COLON = "colon"
    EQUALS = "equals"
    QUESTION = "question"
    DOT = "dot"
    OPEN = "open"
    CLOSE = "close"
    SYMBOL = "symbol"


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    text: str
    start: int
    end: int
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class IdentifierToken:
    name: str
    start: int
    end: int


_SINGLE = {
    ",": TokenKind.COMMA, ";": TokenKind.SEMICOLON, ":": TokenKind.COLON,
    "=": TokenKind.EQUALS, "?": TokenKind.QUESTION, ".": TokenKind.DOT,
    "{": TokenKind.OPEN, "(": TokenKind.OPEN, "[": TokenKind.OPEN,
    "<": TokenKind.OPEN, "}": TokenKind.CLOSE, ")": TokenKind.CLOSE,
    "]": TokenKind.CLOSE, ">": TokenKind.CLOSE,
}

_TOKEN_RE = re.compile(
    r"(?P<whitespace>\s+)|(?P<comment>%[^\r\n]*)|"
    r"(?P<string>\"(?:\\.|[^\"\\])*\"?|'(?:\\.|[^'\\])*'?)|"
    r"(?P<identifier>3[Dd](?![A-Za-z0-9_])|[A-Za-z_][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)*)|"
    r"(?P<number>[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?))|"
    r"(?P<punctuation>[,;:=?.{}()\[\]<>])|(?P<symbol>.)",
    re.DOTALL,
)


def tokenize(source: str, offset: int = 0, line: int = 1, column: int = 1) -> tuple[Token, ...]:
    """Tokenize *source* tolerantly, retaining trivia and exact source spans."""
    result: list[Token] = []
    current_line, current_column = line, column
    names = {
        "whitespace": TokenKind.WHITESPACE, "comment": TokenKind.COMMENT,
        "string": TokenKind.STRING, "identifier": TokenKind.IDENTIFIER,
        "number": TokenKind.NUMBER, "symbol": TokenKind.SYMBOL,
    }
    for match in _TOKEN_RE.finditer(source):
        raw = match.group(0)
        kind = _SINGLE.get(raw, names.get(match.lastgroup or "", TokenKind.SYMBOL))
        result.append(Token(kind, raw, offset + match.start(), offset + match.end(),
                            current_line, current_column))
        newline_count = raw.count("\n")
        if newline_count:
            current_line += newline_count
            current_column = len(raw.rsplit("\n", 1)[1]) + 1
        else:
            current_column += len(raw)
    return tuple(result)


def identifier_tokens(text: str, offset: int = 0) -> tuple[IdentifierToken, ...]:
    """Compatibility helper returning non-reserved identifiers outside trivia."""
    return tuple(
        IdentifierToken(token.text, token.start, token.end)
        for token in tokenize(text, offset)
        if token.kind is TokenKind.IDENTIFIER and token.text.upper() not in RESERVED_WORDS
    )


def command_at_start(rhs: str) -> str | None:
    for token in tokenize(rhs):
        if token.kind in (TokenKind.WHITESPACE, TokenKind.COMMENT):
            continue
        return token.text.upper() if token.kind is TokenKind.IDENTIFIER else None
    return None
