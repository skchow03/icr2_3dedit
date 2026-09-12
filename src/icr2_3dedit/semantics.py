"""Reference-graph analysis, isolated from Papyrus entry-point policy."""

from __future__ import annotations

from dataclasses import dataclass

from .parser import ParsedDocument


@dataclass(frozen=True, slots=True)
class ReferenceGraph:
    entry_point: str | None
    inferred_entry_point: bool
    reachable: frozenset[str]
    unreachable: frozenset[str]
    cycles: tuple[tuple[str, ...], ...]


def choose_entry_point(document: ParsedDocument) -> tuple[str | None, bool]:
    if "root" in document.definitions:
        return "root", False
    candidates = [
        statement.name for statement in document.statements
        if statement.name is not None and statement.kind != "NIL"
    ]
    return (candidates[-1], True) if candidates else (None, True)


def build_reference_graph(document: ParsedDocument) -> ReferenceGraph:
    entry, inferred = choose_entry_point(document)
    reachable: set[str] = set()
    active: list[str] = []
    cycles: list[tuple[str, ...]] = []

    def visit(name: str) -> None:
        if name in active:
            cycle = tuple(active[active.index(name):] + [name])
            if cycle not in cycles:
                cycles.append(cycle)
            return
        if name in reachable:
            return
        reachable.add(name)
        active.append(name)
        for target in document.definitions[name].references:
            if target in document.definitions:
                visit(target)
        active.pop()

    if entry is not None:
        visit(entry)
    return ReferenceGraph(
        entry, inferred, frozenset(reachable),
        frozenset(document.definitions) - reachable, tuple(cycles),
    )
