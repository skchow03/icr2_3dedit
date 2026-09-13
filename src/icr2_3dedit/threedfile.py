"""Lossless structural model for Papyrus-style textual .3D files.

This module deliberately models syntax, not rendering semantics.  It keeps the
original byte stream authoritative while providing stable NodeIDs for named
(top-level) definitions, command expressions, delimiter groups, and references.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter

from .syntax import COMMANDS, KEYWORDS, RECORD_FIELDS, Token, TokenKind, tokenize

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
    command: str | None = None
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
        # Direct token -> structural owner mapping makes reference parenting O(1)
        # after the structural pass, avoiding a tree search for every reference.
        self.owner_by_token: dict[int, int] = {}

    def _new(self, kind: str, start: int, end: int, parent: int | None,
             token_start: int, token_end: int, *, name: str | None = None,
             command: str | None = None, opener: str | None = None,
             closer: str | None = None) -> int:
        nid = self.next_id
        self.next_id += 1
        self.nodes[nid] = ThreeDNode(nid, kind, start, end, parent, [], name,
                                    command, opener, closer, token_start, token_end)
        if parent is not None:
            self.nodes[parent].children.append(nid)
        return nid

    def _diag(self, token: Token, code: str, message: str, severity: str = "error") -> None:
        self.diags.append(ThreeDDiagnostic(severity, code, message, token.start,
                                           token.end, token.line, token.column))

    def _statement_start_after_semicolonless_header(self) -> int:
        line_end = len(self.source)
        for marker in ("\r", "\n"):
            pos = self.source.find(marker)
            if pos != -1:
                line_end = min(line_end, pos)
        sig = [(i, tok) for i, tok in enumerate(self.tokens)
               if tok.start < line_end and tok.kind not in _TRIVIA]
        if len(sig) < 3:
            return 0
        if sig[0][1].text.upper() != "3D" or sig[1][1].text.upper() != "VERSION":
            return 0
        if any(tok.kind is TokenKind.SEMICOLON for _, tok in sig):
            return 0
        next_line = line_end
        if self.source[line_end:line_end + 2] == "\r\n":
            next_line += 2
        elif line_end < len(self.source) and self.source[line_end] in "\r\n":
            next_line += 1
        for i, tok in enumerate(self.tokens):
            if tok.start >= next_line:
                return i
            if tok.start < next_line < tok.end:
                return i + 1
        return len(self.tokens)

    def build(self):
        stack: list[tuple[str, Token]] = []
        statement_start = self._statement_start_after_semicolonless_header()
        ranges: list[tuple[int, int]] = []
        for i, tok in enumerate(self.tokens):
            if i < statement_start:
                continue
            if tok.kind is TokenKind.OPEN:
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
            colon = next((j for j, ti in enumerate(sig)
                          if self.tokens[ti].kind is TokenKind.COLON), None)
            if colon != 1 or self.tokens[sig[0]].kind is not TokenKind.IDENTIFIER:
                continue
            name_tok = self.tokens[sig[0]]
            first_tok, last_tok = self.tokens[a], self.tokens[b - 1]
            definition_id = self._new("definition", first_tok.start, last_tok.end,
                                      None, a, b, name=name_tok.text)
            self.top.append(definition_id)
            self.symbols.setdefault(name_tok.text, []).append(definition_id)
            rhs_token_index = sig[2] if len(sig) > 2 else sig[-1]
            self._build_structure(definition_id, rhs_token_index, b - 1)

        for name, ids in self.symbols.items():
            if len(ids) > 1:
                node = self.nodes[ids[1]]
                tok = self.tokens[node.token_start]
                self._diag(tok, "duplicate-symbol", f"Duplicate definition {name!r}")

        self._collect_references()
        return (self.nodes, self.top, self.symbols, self.refs, self.diags,
                self.max_depth)

    def _build_structure(self, definition_id: int, start: int, end: int) -> None:
        """Build command-expression and delimiter nodes without recursion.

        A recognized command token owns the immediately following delimiter group
        when that group is its syntactic argument container. Nested commands are
        therefore represented explicitly (LIST -> LIST -> reference) rather than
        only as anonymous braces. Other delimiters remain lossless generic groups.
        """
        stack: list[tuple[int, str]] = []
        pending_command: tuple[int, int] | None = None  # (node_id, token_index)

        for i in range(start, end):
            tok = self.tokens[i]
            current_parent = stack[-1][0] if stack else definition_id

            if tok.kind is TokenKind.IDENTIFIER and tok.text.upper() in COMMANDS:
                command = tok.text.upper()
                # EXTERN is a modifier/value introducer rather than a container;
                # NIL is atomic. They do not need expression nodes of their own.
                if command not in {"NIL", "EXTERN"}:
                    cid = self._new("command", tok.start, tok.end, current_parent,
                                    i, i + 1, command=command)
                    self.owner_by_token[i] = cid
                    pending_command = (cid, i)
                else:
                    pending_command = None
                continue

            if tok.kind in _TRIVIA:
                continue

            if tok.kind is TokenKind.OPEN:
                parent = current_parent
                command_id = None
                if pending_command is not None:
                    command_id, _ = pending_command
                    parent = command_id
                gid = self._new("group", tok.start, tok.end, parent, i, i + 1,
                                opener=tok.text)
                stack.append((gid, tok.text))
                if command_id is not None:
                    command_node = self.nodes[command_id]
                    command_node.end = tok.end
                    command_node.token_end = i + 1
                pending_command = None
                continue

            if tok.kind is TokenKind.CLOSE and stack and _OPEN_TO_CLOSE.get(stack[-1][1]) == tok.text:
                gid, _ = stack.pop()
                group = self.nodes[gid]
                group.end = tok.end
                group.token_end = i + 1
                group.closer = tok.text
                if group.parent_id is not None:
                    parent = self.nodes[group.parent_id]
                    if parent.kind == "command":
                        parent.end = tok.end
                        parent.token_end = i + 1
                pending_command = None
                continue

            # A command such as DYNAMIC/SUPEROBJ can have scalar arguments before
            # any nested construct. Keep its node useful by extending its span over
            # tokens until another structural construct supersedes it.
            if pending_command is not None:
                cid, _ = pending_command
                self.nodes[cid].end = tok.end
                self.nodes[cid].token_end = i + 1
            # Do not carry a command across a comma into an unrelated argument.
            if tok.kind is TokenKind.COMMA:
                pending_command = None

        # Command nodes that are direct RHS commands should cover the definition's
        # RHS through the final non-semicolon token, even when they have no braces.
        direct_commands = [self.nodes[n] for n in self.nodes[definition_id].children
                           if self.nodes[n].kind == "command"]
        if direct_commands and end > start:
            last = self.tokens[end - 1]
            for node in direct_commands:
                if node.token_start == start:
                    node.end = max(node.end, last.end)
                    node.token_end = max(node.token_end, end)

        # Fill token ownership in one linear pass. Deepest structural container
        # wins; this is later used to parent reference nodes without tree scans.
        containers = [self.nodes[n] for n in self.nodes
                      if self.nodes[n].kind in {"command", "group"}
                      and self.nodes[n].token_start >= start
                      and self.nodes[n].token_end <= end
                      and self.nodes[n].token_end > self.nodes[n].token_start]
        events: dict[int, list[tuple[int, int]]] = {}
        for node in containers:
            events.setdefault(node.token_start, []).append((1, node.node_id))
            events.setdefault(node.token_end, []).append((-1, node.node_id))
        active: list[int] = []
        for i in range(start, end):
            for action, nid in sorted(events.get(i, [])):
                if action < 0 and nid in active:
                    active.remove(nid)
            for action, nid in sorted(events.get(i, [])):
                if action > 0:
                    active.append(nid)
            if active:
                self.owner_by_token[i] = active[-1]
            else:
                self.owner_by_token[i] = definition_id

    def _collect_references(self) -> None:
        for definition_id in self.top:
            definition = self.nodes[definition_id]
            sig = [i for i in range(definition.token_start, definition.token_end)
                   if self.tokens[i].kind not in _TRIVIA]
            if len(sig) < 3:
                continue
            for pos, i in enumerate(sig[2:], start=2):
                tok = self.tokens[i]
                if tok.kind is not TokenKind.IDENTIFIER:
                    continue
                upper = tok.text.upper()
                if upper in COMMANDS or upper in KEYWORDS or upper in RECORD_FIELDS:
                    continue
                prev = self.tokens[sig[pos - 1]] if pos else None
                nxt = self.tokens[sig[pos + 1]] if pos + 1 < len(sig) else None
                if prev is not None and prev.kind is TokenKind.DOT:
                    continue
                if nxt is not None and nxt.kind is TokenKind.EQUALS:
                    continue
                parent = self.owner_by_token.get(i, definition_id)
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
