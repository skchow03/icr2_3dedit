"""Lossless structural model for Papyrus-style textual .3D files.

This module deliberately models syntax, not rendering semantics.  It keeps the
original byte stream authoritative while providing stable NodeIDs for named
(top-level) definitions and anonymous nested constructs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Iterable

from .syntax import Token, TokenKind, tokenize

_OPEN_TO_CLOSE = {"{": "}", "(": ")", "[": "]", "<": ">"}
_TRIVIA = {TokenKind.WHITESPACE, TokenKind.COMMENT}


@dataclass(frozen=True, slots=True)
class ThreeDDiagnostic:
    severity: str
    code: str
    message: str
    start: int
    end: int
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class ThreeDReference:
    node_id: int
    name: str
    start: int
    end: int
    target_node_id: int | None = None
    ambiguous: bool = False


@dataclass(slots=True)
class ThreeDNode:
    node_id: int
    kind: str
    start: int
    end: int
    parent_id: int | None
    children: list[int] = field(default_factory=list)
    name: str | None = None
    opener: str | None = None
    closer: str | None = None
    token_start: int = 0
    token_end: int = 0


@dataclass(slots=True)
class ThreeDFile:
    original_bytes: bytes
    source_text: str
    encoding: str
    has_utf8_bom: bool
    tokens: tuple[Token, ...]
    nodes_by_id: dict[int, ThreeDNode]
    top_level_nodes: list[int]
    symbols: dict[str, list[int]]
    references: list[ThreeDReference]
    diagnostics: list[ThreeDDiagnostic]
    max_nesting_depth: int
    parse_seconds: float = 0.0
    path: Path | None = None
    dirty: bool = False

    @classmethod
    def load(cls, path: str | Path) -> "ThreeDFile":
        p = Path(path)
        obj = cls.from_bytes(p.read_bytes())
        obj.path = p
        return obj

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ThreeDFile":
        started = perf_counter()
        bom = raw.startswith(b"\xef\xbb\xbf")
        payload = raw[3:] if bom else raw
        try:
            text = payload.decode("utf-8")
            encoding = "utf-8"
        except UnicodeDecodeError:
            text = payload.decode("cp1252")
            encoding = "cp1252"

        tokens = tokenize(text)
        builder = _Builder(text, tokens)
        nodes, top, symbols, refs, diagnostics, depth = builder.build()
        result = cls(raw, text, encoding, bom, tokens, nodes, top, symbols,
                     refs, diagnostics, depth)
        result.parse_seconds = perf_counter() - started
        return result

    def to_bytes(self) -> bytes:
        """Return the exact source bytes while the structural model is clean."""
        if self.dirty:
            raise NotImplementedError(
                "Step 1 only guarantees byte-exact serialization for an unchanged document"
            )
        return self.original_bytes

    def save(self, path: str | Path | None = None) -> Path:
        destination = Path(path) if path is not None else self.path
        if destination is None:
            raise ValueError("A destination is required")
        destination.write_bytes(self.to_bytes())
        self.path = destination
        return destination

    def node_text(self, node_id: int) -> str:
        node = self.nodes_by_id[node_id]
        return self.source_text[node.start:node.end]


class _Builder:
    """Single-pass structural index builder over a lossless token stream."""

    def __init__(self, source: str, tokens: tuple[Token, ...]):
        self.source = source
        self.tokens = tokens
        self.nodes: dict[int, ThreeDNode] = {}
        self.top: list[int] = []
        self.symbols: dict[str, list[int]] = {}
        self.refs: list[ThreeDReference] = []
        self.diags: list[ThreeDDiagnostic] = []
        self.next_id = 1
        self.max_depth = 0

    def _new(self, kind: str, start: int, end: int, parent: int | None,
             token_start: int, token_end: int, *, name: str | None = None,
             opener: str | None = None, closer: str | None = None) -> int:
        nid = self.next_id
        self.next_id += 1
        self.nodes[nid] = ThreeDNode(nid, kind, start, end, parent, [], name,
                                    opener, closer, token_start, token_end)
        if parent is not None:
            self.nodes[parent].children.append(nid)
        return nid

    def _diag(self, token: Token, code: str, message: str, severity: str = "error") -> None:
        self.diags.append(ThreeDDiagnostic(severity, code, message, token.start,
                                           token.end, token.line, token.column))

    def build(self):
        # First identify top-level semicolon-terminated statements while respecting
        # delimiter nesting.  Header text before the first definition is retained
        # by the token stream and original bytes; only definitions become nodes.
        stack: list[tuple[str, Token]] = []
        statement_start = 0
        ranges: list[tuple[int, int]] = []
        for i, tok in enumerate(self.tokens):
            if tok.kind is TokenKind.OPEN:
                # '<' is normally a vector delimiter. Treat it structurally only
                # when a matching '>' exists through the normal stack discipline.
                stack.append((tok.text, tok))
                self.max_depth = max(self.max_depth, len(stack))
            elif tok.kind is TokenKind.CLOSE:
                if stack and _OPEN_TO_CLOSE.get(stack[-1][0]) == tok.text:
                    stack.pop()
                elif tok.text != ">":
                    self._diag(tok, "unmatched-close", f"Unmatched closing delimiter {tok.text!r}")
            elif tok.kind is TokenKind.SEMICOLON and not stack:
                ranges.append((statement_start, i + 1))
                statement_start = i + 1
        for _, opener in stack:
            self._diag(opener, "unclosed-delimiter", f"Unclosed delimiter {opener.text!r}")

        for a, b in ranges:
            sig = [i for i in range(a, b) if self.tokens[i].kind not in _TRIVIA]
            colon = next((j for j, ti in enumerate(sig) if self.tokens[ti].kind is TokenKind.COLON), None)
            if colon != 1 or self.tokens[sig[0]].kind is not TokenKind.IDENTIFIER:
                continue
            name_tok = self.tokens[sig[0]]
            first_tok, last_tok = self.tokens[a], self.tokens[b - 1]
            definition_id = self._new("definition", first_tok.start, last_tok.end,
                                      None, a, b, name=name_tok.text)
            self.top.append(definition_id)
            self.symbols.setdefault(name_tok.text, []).append(definition_id)
            rhs_token_index = sig[2] if len(sig) > 2 else sig[-1]
            self._build_nested(definition_id, rhs_token_index, b - 1)

        for name, ids in self.symbols.items():
            if len(ids) > 1:
                node = self.nodes[ids[1]]
                tok = self.tokens[node.token_start]
                self._diag(tok, "duplicate-symbol", f"Duplicate definition {name!r}")

        self._collect_references()
        return (self.nodes, self.top, self.symbols, self.refs, self.diags,
                self.max_depth)

    def _build_nested(self, definition_id: int, start: int, end: int) -> None:
        """Create anonymous delimiter nodes iteratively; never use Python recursion."""
        stack: list[tuple[int, str]] = []
        for i in range(start, end):
            tok = self.tokens[i]
            if tok.kind is TokenKind.OPEN:
                parent = stack[-1][0] if stack else definition_id
                nid = self._new("group", tok.start, tok.end, parent, i, i + 1,
                                opener=tok.text)
                stack.append((nid, tok.text))
            elif tok.kind is TokenKind.CLOSE and stack and _OPEN_TO_CLOSE.get(stack[-1][1]) == tok.text:
                nid, _ = stack.pop()
                node = self.nodes[nid]
                node.end = tok.end
                node.token_end = i + 1
                node.closer = tok.text

    def _collect_references(self) -> None:
        # Reference occurrences are represented as nodes too.  We intentionally
        # do not expand targets; resolution is a symbol-table lookup only.
        for definition_id in self.top:
            definition = self.nodes[definition_id]
            sig = [i for i in range(definition.token_start, definition.token_end)
                   if self.tokens[i].kind not in _TRIVIA]
            if len(sig) < 3:
                continue
            # Skip definition name and colon; consider identifiers in the RHS.
            for pos, i in enumerate(sig[2:], start=2):
                tok = self.tokens[i]
                if tok.kind is not TokenKind.IDENTIFIER:
                    continue
                upper = tok.text.upper()
                # Commands/keywords/record field names are syntax, not references.
                from .syntax import COMMANDS, KEYWORDS, RECORD_FIELDS
                if upper in COMMANDS or upper in KEYWORDS or upper in RECORD_FIELDS:
                    continue
                prev = self.tokens[sig[pos - 1]] if pos else None
                nxt = self.tokens[sig[pos + 1]] if pos + 1 < len(sig) else None
                if prev is not None and prev.kind is TokenKind.DOT:
                    continue
                if nxt is not None and nxt.kind is TokenKind.EQUALS:
                    continue
                parent = self._innermost_group(definition_id, tok.start) or definition_id
                rid = self._new("reference", tok.start, tok.end, parent, i, i + 1,
                                name=tok.text)
                targets = self.symbols.get(tok.text, [])
                target = targets[0] if len(targets) == 1 else None
                ambiguous = len(targets) > 1
                self.refs.append(ThreeDReference(rid, tok.text, tok.start, tok.end,
                                                 target, ambiguous))
                if not targets:
                    self._diag(tok, "unresolved-reference", f"Unresolved reference {tok.text!r}", "warning")
                elif ambiguous:
                    self._diag(tok, "ambiguous-reference", f"Ambiguous reference {tok.text!r}", "warning")

    def _innermost_group(self, definition_id: int, offset: int) -> int | None:
        best = None
        best_span = None
        # This is deliberately simple for pass 1.  It is linear in groups within
        # one definition; semantic/render expansion remains absent.
        pending = list(self.nodes[definition_id].children)
        while pending:
            nid = pending.pop()
            node = self.nodes[nid]
            if node.kind == "group" and node.start <= offset < node.end:
                span = node.end - node.start
                if best_span is None or span < best_span:
                    best, best_span = nid, span
                pending.extend(node.children)
        return best
