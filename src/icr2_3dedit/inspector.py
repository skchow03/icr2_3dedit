"""Read-only, scalable projections of :class:`ThreeDFile` for the GUI.

This module deliberately contains no Tk code.  It indexes cheap structural
relationships that already exist in ``ThreeDFile``; it never expands the
reference graph or derives geometry.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass

from .syntax import TokenKind
from .threedfile import ThreeDDiagnostic, ThreeDFile, ThreeDNode, ThreeDReference
from .values import editable_values


SOURCE_PAGE_CHARS = 100_000
TREE_CHILD_BATCH = 250
SEARCH_RESULT_LIMIT = 500


@dataclass(frozen=True, slots=True)
class SourcePage:
    """One bounded, exact slice of a selected node's source span."""

    text: str
    absolute_start: int
    absolute_end: int
    node_start: int
    node_end: int
    page_index: int
    page_count: int


@dataclass(frozen=True, slots=True)
class InspectorSearchResult:
    """One bounded result row for the inspector's lazy find UI."""

    node_id: int
    label: str
    kind: str
    line: int
    detail: str


class ThreeDInspectorModel:
    """Demand-driven structural queries over one ``ThreeDFile``.

    Construction is O(nodes + references) but creates no duplicate syntax tree,
    rendered world, geometry, or GUI objects.
    """

    def __init__(self, document: ThreeDFile) -> None:
        self.document = document
        self._references_by_node_id = {ref.node_id: ref for ref in document.references}
        reverse: dict[int, list[ThreeDReference]] = defaultdict(list)
        for ref in document.references:
            if ref.target_node_id is not None:
                reverse[ref.target_node_id].append(ref)
        self._reverse_references = {node_id: tuple(refs) for node_id, refs in reverse.items()}
        self._reference_starts = tuple(ref.start for ref in document.references)

        starts = [0]
        position = document.source_text.find("\n")
        while position >= 0:
            starts.append(position + 1)
            position = document.source_text.find("\n", position + 1)
        self._line_starts = tuple(starts)

    @property
    def root_node_ids(self) -> tuple[int, ...]:
        return tuple(self.document.top_level_nodes)

    def node(self, node_id: int) -> ThreeDNode:
        return self.document.nodes_by_id[node_id]

    def children(self, node_id: int) -> tuple[int, ...]:
        return tuple(self.node(node_id).children)

    def label(self, node_id: int) -> str:
        node = self.node(node_id)
        if node.kind == "definition":
            return node.name or "(anonymous definition)"
        if node.kind == "command":
            return node.command or "command"
        if node.kind == "reference":
            return f"→ {node.name or '(unnamed)'}"
        return node.kind

    def line_and_column(self, node_id: int) -> tuple[int, int]:
        node = self.node(node_id)
        offset = node.start
        for token_index in range(node.token_start, node.token_end):
            token = self.document.tokens[token_index]
            if token.kind not in {TokenKind.WHITESPACE, TokenKind.COMMENT}:
                offset = token.start
                break
        line_index = max(0, bisect_right(self._line_starts, offset) - 1)
        return line_index + 1, offset - self._line_starts[line_index] + 1

    def reference_for_node(self, node_id: int) -> ThreeDReference | None:
        return self._references_by_node_id.get(node_id)

    def references_from(self, node_id: int) -> tuple[ThreeDReference, ...]:
        """Return references textually contained by a node, without traversal."""
        node = self.node(node_id)
        left = bisect_left(self._reference_starts, node.start)
        right = bisect_right(self._reference_starts, node.end)
        return tuple(
            ref for ref in self.document.references[left:right]
            if ref.start >= node.start and ref.end <= node.end
        )

    def reverse_references(self, node_id: int) -> tuple[ThreeDReference, ...]:
        """Return direct source references targeting this definition NodeID."""
        return self._reverse_references.get(node_id, ())

    def source_page(
        self,
        node_id: int,
        page_index: int = 0,
        page_chars: int = SOURCE_PAGE_CHARS,
    ) -> SourcePage:
        if page_chars < 1:
            raise ValueError("page_chars must be positive")
        node = self.node(node_id)
        length = max(0, node.end - node.start)
        page_count = max(1, (length + page_chars - 1) // page_chars)
        page_index = min(max(0, page_index), page_count - 1)
        start = node.start + page_index * page_chars
        end = min(node.end, start + page_chars)
        return SourcePage(
            self.document.source_text[start:end], start, end,
            node.start, node.end, page_index, page_count,
        )

    def diagnostic_source_page(
        self,
        diagnostic: ThreeDDiagnostic,
        context_chars: int = 2_000,
    ) -> SourcePage:
        start = max(0, diagnostic.start - context_chars // 2)
        end = min(len(self.document.source_text), max(diagnostic.end, diagnostic.start + 1) + context_chars // 2)
        return SourcePage(
            self.document.source_text[start:end], start, end,
            start, end, 0, 1,
        )

    def properties(self, node_id: int) -> tuple[tuple[str, str], ...]:
        node = self.node(node_id)
        line, column = self.line_and_column(node_id)
        values = [
            ("NodeID", str(node.node_id)),
            ("Kind", node.kind),
            ("Name", node.name or ""),
            ("Command", node.command or ""),
            ("Source span", f"{node.start}–{node.end}"),
            ("Line / column", f"{line}:{column}"),
            ("Structural children", str(len(node.children))),
            ("Syntax parent NodeID", "" if node.parent_id is None else str(node.parent_id)),
        ]
        ref = self.reference_for_node(node_id)
        if ref is not None:
            if ref.target_node_id is not None:
                target = str(ref.target_node_id)
            elif ref.ambiguous:
                target = "ambiguous"
            else:
                target = "unresolved"
            values.append(("Reference target", target))
        editable = editable_values(self.document, node_id)
        if editable is not None:
            values.extend(
                (component.label, component.spelling)
                for component in editable.components
            )
        return tuple(values)

    def search(
        self,
        query: str,
        *,
        kind_filter: str = "All",
        limit: int = SEARCH_RESULT_LIMIT,
    ) -> tuple[InspectorSearchResult, ...]:
        """Return a capped structural search result set without GUI expansion."""
        needle = query.strip().casefold()
        if not needle:
            return ()
        results: list[InspectorSearchResult] = []
        for node_id in sorted(self.document.nodes_by_id):
            node = self.node(node_id)
            if not self._matches_search_kind(node_id, kind_filter):
                continue
            label = self.label(node_id)
            haystack_parts = [
                label,
                node.kind,
                node.name or "",
                node.command or "",
                str(node.node_id),
            ]
            reference = self.reference_for_node(node_id)
            if reference is not None:
                haystack_parts.append(reference.name)
                if reference.target_node_id is not None:
                    target = self.node(reference.target_node_id)
                    haystack_parts.append(target.name or "")
                    haystack_parts.append(str(reference.target_node_id))
            haystack = "\n".join(haystack_parts).casefold()
            if needle not in haystack:
                continue
            line, _ = self.line_and_column(node_id)
            results.append(
                InspectorSearchResult(
                    node_id=node_id,
                    label=label,
                    kind=self._display_kind(node_id),
                    line=line,
                    detail=self._search_detail(node_id),
                )
            )
            if len(results) >= limit:
                break
        return tuple(results)

    def _display_kind(self, node_id: int) -> str:
        node = self.node(node_id)
        if node.kind == "command" and node.command:
            return node.command
        return node.kind

    def _matches_search_kind(self, node_id: int, kind_filter: str) -> bool:
        if kind_filter == "All":
            return True
        node = self.node(node_id)
        if kind_filter == "Definitions":
            return node.kind == "definition"
        if kind_filter == "Commands":
            return node.kind == "command"
        if kind_filter == "References":
            return node.kind == "reference"
        if kind_filter == "Editable Values":
            return editable_values(self.document, node_id) is not None
        if kind_filter == "Diagnostics":
            return False
        return False

    def _search_detail(self, node_id: int) -> str:
        node = self.node(node_id)
        if node.kind == "reference":
            reference = self.reference_for_node(node_id)
            if reference is None:
                return ""
            if reference.target_node_id is not None:
                target = self.node(reference.target_node_id)
                target_name = target.name or f"Node {reference.target_node_id}"
                return f"targets {target_name}"
            return "ambiguous" if reference.ambiguous else "unresolved"
        if node.kind == "definition" and node.name:
            return node.name
        if node.kind == "command" and node.command:
            return node.command
        editable = editable_values(self.document, node_id)
        if editable is not None:
            return ", ".join(
                f"{component.label}={component.spelling}"
                for component in editable.components
            )
        return ""
