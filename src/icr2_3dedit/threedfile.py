"""Lossless structural model for Papyrus-style textual .3D files.

This module deliberately models syntax, not rendering semantics. It keeps the
original byte stream authoritative while providing stable NodeIDs for named
definitions, command expressions, delimiter groups, and references.
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
    severity: str; code: str; message: str; start: int; end: int; line: int; column: int

@dataclass(frozen=True, slots=True)
class ThreeDReference:
    node_id: int; name: str; start: int; end: int
    target_node_id: int | None = None; ambiguous: bool = False

@dataclass(slots=True)
class ThreeDNode:
    node_id: int; kind: str; start: int; end: int; parent_id: int | None
    children: list[int] = field(default_factory=list)
    name: str | None = None; command: str | None = None
    opener: str | None = None; closer: str | None = None
    token_start: int = 0; token_end: int = 0

@dataclass(slots=True)
class ThreeDFile:
    original_bytes: bytes; source_text: str; encoding: str; has_utf8_bom: bool
    tokens: tuple[Token, ...]; nodes_by_id: dict[int, ThreeDNode]
    top_level_nodes: list[int]; symbols: dict[str, list[int]]
    references: list[ThreeDReference]; diagnostics: list[ThreeDDiagnostic]
    max_nesting_depth: int; parse_seconds: float = 0.0
    path: Path | None = None; dirty: bool = False

    @classmethod
    def load(cls, path: str | Path) -> "ThreeDFile":
        p = Path(path); obj = cls.from_bytes(p.read_bytes()); obj.path = p; return obj

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ThreeDFile":
        started = perf_counter(); bom = raw.startswith(b"\xef\xbb\xbf"); payload = raw[3:] if bom else raw
        try: text = payload.decode("utf-8"); encoding = "utf-8"
        except UnicodeDecodeError: text = payload.decode("cp1252"); encoding = "cp1252"
        tokens = tokenize(text); builder = _Builder(text, tokens)
        nodes, top, symbols, refs, diagnostics, depth = builder.build()
        result = cls(raw, text, encoding, bom, tokens, nodes, top, symbols, refs, diagnostics, depth)
        result.parse_seconds = perf_counter() - started; return result

    def to_bytes(self) -> bytes:
        if self.dirty: raise NotImplementedError("Step 1 only guarantees byte-exact serialization for an unchanged document")
        return self.original_bytes

    def save(self, path: str | Path | None = None) -> Path:
        destination = Path(path) if path is not None else self.path
        if destination is None: raise ValueError("A destination is required")
        destination.write_bytes(self.to_bytes()); self.path = destination; return destination

    def node_text(self, node_id: int) -> str:
        node = self.nodes_by_id[node_id]; return self.source_text[node.start:node.end]

class _Builder:
    def __init__(self, source: str, tokens: tuple[Token, ...]):
        self.source=source; self.tokens=tokens; self.nodes={}; self.top=[]; self.symbols={}; self.refs=[]; self.diags=[]
        self.next_id=1; self.max_depth=0; self.owner_by_token: dict[int,int]={}

    def _new(self, kind, start, end, parent, token_start, token_end, *, name=None, command=None, opener=None, closer=None):
        nid=self.next_id; self.next_id+=1
        self.nodes[nid]=ThreeDNode(nid,kind,start,end,parent,[],name,command,opener,closer,token_start,token_end)
        if parent is not None: self.nodes[parent].children.append(nid)
        return nid

    def _diag(self, token, code, message, severity="error"):
        self.diags.append(ThreeDDiagnostic(severity,code,message,token.start,token.end,token.line,token.column))

    def _statement_start_after_semicolonless_header(self):
        line_end=len(self.source)
        for marker in ("\r","\n"):
            pos=self.source.find(marker)
            if pos!=-1: line_end=min(line_end,pos)
        sig=[(i,t) for i,t in enumerate(self.tokens) if t.start<line_end and t.kind not in _TRIVIA]
        if len(sig)<3 or sig[0][1].text.upper()!="3D" or sig[1][1].text.upper()!="VERSION": return 0
        if any(t.kind is TokenKind.SEMICOLON for _,t in sig): return 0
        next_line=line_end
        if self.source[line_end:line_end+2]=="\r\n": next_line+=2
        elif line_end<len(self.source) and self.source[line_end] in "\r\n": next_line+=1
        for i,t in enumerate(self.tokens):
            if t.start>=next_line: return i
            if t.start<next_line<t.end: return i+1
        return len(self.tokens)

    def build(self):
        stack=[]; statement_start=self._statement_start_after_semicolonless_header(); ranges=[]
        for i,tok in enumerate(self.tokens):
            if i<statement_start: continue
            if tok.kind is TokenKind.OPEN: stack.append((tok.text,tok)); self.max_depth=max(self.max_depth,len(stack))
            elif tok.kind is TokenKind.CLOSE:
                if stack and _OPEN_TO_CLOSE.get(stack[-1][0])==tok.text: stack.pop()
                elif tok.text!=">": self._diag(tok,"unmatched-close",f"Unmatched closing delimiter {tok.text!r}")
            elif tok.kind is TokenKind.SEMICOLON and not stack: ranges.append((statement_start,i+1)); statement_start=i+1
        for _,opener in stack: self._diag(opener,"unclosed-delimiter",f"Unclosed delimiter {opener.text!r}")
        for a,b in ranges:
            sig=[i for i in range(a,b) if self.tokens[i].kind not in _TRIVIA]
            colon=next((j for j,ti in enumerate(sig) if self.tokens[ti].kind is TokenKind.COLON),None)
            if colon!=1 or self.tokens[sig[0]].kind is not TokenKind.IDENTIFIER: continue
            name_tok=self.tokens[sig[0]]; first_tok,last_tok=self.tokens[a],self.tokens[b-1]
            did=self._new("definition",first_tok.start,last_tok.end,None,a,b,name=name_tok.text)
            self.top.append(did); self.symbols.setdefault(name_tok.text,[]).append(did)
            rhs=sig[2] if len(sig)>2 else sig[-1]; self._build_structure(did,rhs,b-1)
        for name,ids in self.symbols.items():
            if len(ids)>1:
                node=self.nodes[ids[1]]; self._diag(self.tokens[node.token_start],"duplicate-symbol",f"Duplicate definition {name!r}")
        self._collect_references(); return self.nodes,self.top,self.symbols,self.refs,self.diags,self.max_depth

    def _build_structure(self, definition_id, start, end):
        """Create explicit command nodes while retaining lossless delimiter groups."""
        stack=[]; pending=None; created=[]
        for i in range(start,end):
            tok=self.tokens[i]; current=stack[-1][0] if stack else definition_id
            if tok.kind is TokenKind.IDENTIFIER and tok.text.upper() in COMMANDS:
                cmd=tok.text.upper()
                if cmd not in {"NIL","EXTERN"}:
                    cid=self._new("command",tok.start,tok.end,current,i,i+1,command=cmd); created.append(cid); pending=cid
                else: pending=None
                continue
            if tok.kind in _TRIVIA: continue
            if tok.kind is TokenKind.OPEN:
                parent=pending if pending is not None else current
                gid=self._new("group",tok.start,tok.end,parent,i,i+1,opener=tok.text); created.append(gid); stack.append((gid,tok.text))
                if pending is not None: self.nodes[pending].end=tok.end; self.nodes[pending].token_end=i+1
                pending=None; continue
            if tok.kind is TokenKind.CLOSE and stack and _OPEN_TO_CLOSE.get(stack[-1][1])==tok.text:
                gid,_=stack.pop(); g=self.nodes[gid]; g.end=tok.end; g.token_end=i+1; g.closer=tok.text
                if g.parent_id is not None and self.nodes[g.parent_id].kind=="command":
                    c=self.nodes[g.parent_id]; c.end=tok.end; c.token_end=i+1
                pending=None; continue
            if pending is not None:
                c=self.nodes[pending]; c.end=tok.end; c.token_end=i+1
            if tok.kind is TokenKind.COMMA: pending=None
        # Direct RHS commands span the RHS, while nested container commands retain their group span.
        if end>start:
            last=self.tokens[end-1]
            for nid in created:
                n=self.nodes[nid]
                if n.kind=="command" and n.parent_id==definition_id and n.token_start==start:
                    n.end=max(n.end,last.end); n.token_end=max(n.token_end,end)
        # Only nodes created for this definition are considered: total work remains linear in file size.
        events={}
        for nid in created:
            n=self.nodes[nid]
            if n.token_end>n.token_start:
                events.setdefault(n.token_start,[]).append((1,nid)); events.setdefault(n.token_end,[]).append((-1,nid))
        active=[]
        for i in range(start,end):
            for action,nid in events.get(i,[]):
                if action<0 and nid in active: active.remove(nid)
            for action,nid in events.get(i,[]):
                if action>0: active.append(nid)
            self.owner_by_token[i]=active[-1] if active else definition_id

    def _collect_references(self):
        for did in self.top:
            d=self.nodes[did]; sig=[i for i in range(d.token_start,d.token_end) if self.tokens[i].kind not in _TRIVIA]
            if len(sig)<3: continue
            for pos,i in enumerate(sig[2:],start=2):
                tok=self.tokens[i]
                if tok.kind is not TokenKind.IDENTIFIER: continue
                upper=tok.text.upper()
                if upper in COMMANDS or upper in KEYWORDS or upper in RECORD_FIELDS: continue
                prev=self.tokens[sig[pos-1]] if pos else None; nxt=self.tokens[sig[pos+1]] if pos+1<len(sig) else None
                if prev is not None and prev.kind is TokenKind.DOT: continue
                if nxt is not None and nxt.kind is TokenKind.EQUALS: continue
                parent=self.owner_by_token.get(i,did)
                rid=self._new("reference",tok.start,tok.end,parent,i,i+1,name=tok.text)
                targets=self.symbols.get(tok.text,[]); target=targets[0] if len(targets)==1 else None; ambiguous=len(targets)>1
                self.refs.append(ThreeDReference(rid,tok.text,tok.start,tok.end,target,ambiguous))
                if not targets: self._diag(tok,"unresolved-reference",f"Unresolved reference {tok.text!r}","warning")
                elif ambiguous: self._diag(tok,"ambiguous-reference",f"Ambiguous reference {tok.text!r}","warning")
