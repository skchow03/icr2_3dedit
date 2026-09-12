"""Diagnostics composed from conservative parsing and reference semantics."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .parser import ParsedDocument, Statement
from .semantics import build_reference_graph
from .geometry import GeometryModel, build_geometry_model


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    severity: Severity
    message: str
    line: int
    statement: Statement | None = None
    start: int | None = None
    end: int | None = None


def analyze(document: ParsedDocument, geometry: GeometryModel | None = None) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for issue in document.issues:
        diagnostics.append(Diagnostic(Severity.WARNING if issue.warning else Severity.ERROR, issue.message, issue.line, document.statement_at(issue.start), issue.start, issue.end))
    for line in document.inline_comment_lines:
        start = sum(len(item) + 1 for item in document.source.splitlines()[:line - 1])
        diagnostics.append(Diagnostic(Severity.ERROR, "Inline comments are not allowed; comments must be on their own line", line, document.statement_at(start), start, start + len(document.source.splitlines()[line - 1])))
    for name, statements in document.duplicates.items():
        for statement in statements[1:]:
            diagnostics.append(Diagnostic(Severity.ERROR, f"Duplicate definition: {name}", statement.line, statement, statement.name_start, statement.name_end))
    geometry = geometry or build_geometry_model(document)
    for issue in geometry.issues:
        severity = Severity.INFO if issue.code == "duplicate-coordinate" else Severity.ERROR
        diagnostics.append(Diagnostic(severity, issue.message, _token_line(document.source, issue.span.start), issue.statement, issue.span.start, issue.span.end))
    known = set(document.definitions)
    for statement in document.statements:
        for token in statement.reference_tokens:
            if token.name not in known:
                diagnostics.append(Diagnostic(Severity.WARNING, f"Unresolved reference: {token.name}", _token_line(document.source, token.start), statement, token.start, token.end))
    graph = build_reference_graph(document)
    for name in sorted(graph.unreachable, key=lambda n: document.definitions[n].start):
        statement = document.definitions[name]
        diagnostics.append(Diagnostic(Severity.INFO, f"Definition is unreachable: {name}", statement.line, statement, statement.name_start, statement.name_end))
    for cycle in graph.cycles:
        statement = document.definitions[cycle[0]]
        diagnostics.append(Diagnostic(Severity.WARNING, f"Reference cycle: {' -> '.join(cycle)}", statement.line, statement, statement.name_start, statement.name_end))
    return sorted(diagnostics, key=lambda item: (item.line, item.severity.value, item.message))


def _token_line(source: str, start: int) -> int:
    return source.count("\n", 0, start) + 1
