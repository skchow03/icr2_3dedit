"""Static diagnostics for parsed .3D documents."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .parser import ParsedDocument, Statement, identifier_candidates


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


def analyze(document: ParsedDocument) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []

    for name, statements in document.duplicates.items():
        for statement in statements[1:]:
            diagnostics.append(Diagnostic(
                Severity.ERROR,
                f"Duplicate definition: {name}",
                statement.line,
                statement,
            ))

    known = set(document.definitions)
    referenced: set[str] = set()
    for statement in document.statements:
        if statement.rhs is None:
            continue
        for candidate in identifier_candidates(statement.rhs):
            if candidate in known:
                referenced.add(candidate)
            elif candidate.upper() != candidate:
                diagnostics.append(Diagnostic(
                    Severity.WARNING,
                    f"Possible unresolved reference: {candidate}",
                    statement.line,
                    statement,
                ))

    for name, statement in document.definitions.items():
        if name not in referenced and statement.kind not in {"NIL", "vertex"}:
            diagnostics.append(Diagnostic(
                Severity.INFO,
                f"Definition is not referenced: {name}",
                statement.line,
                statement,
            ))

    return sorted(diagnostics, key=lambda item: (item.line, item.severity.value, item.message))

