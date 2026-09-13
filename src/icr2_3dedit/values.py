"""Conservative structured access to editable numeric tuple nodes."""

from __future__ import annotations

from dataclasses import dataclass

from .syntax import Token, TokenKind, tokenize
from .threedfile import ThreeDFile


_TRIVIA = {TokenKind.WHITESPACE, TokenKind.COMMENT}
_TUPLE_LABELS = {
    "coordinate": ("X", "Y", "Z"),
    "texcoord": ("U", "V"),
}


@dataclass(frozen=True, slots=True)
class ThreeDNumericComponent:
    """One number token within a structurally verified tuple."""

    label: str
    spelling: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ThreeDNumericTuple:
    """An editable coordinate or texture-coordinate tuple."""

    node_id: int
    kind: str
    components: tuple[ThreeDNumericComponent, ...]

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(component.label for component in self.components)

    @property
    def spellings(self) -> tuple[str, ...]:
        return tuple(component.spelling for component in self.components)


@dataclass(frozen=True, slots=True)
class ThreeDEditableValues:
    """Numeric tuples exposed for one selected source object."""

    node_id: int
    kind: str
    tuples: tuple[ThreeDNumericTuple, ...]

    @property
    def components(self) -> tuple[ThreeDNumericComponent, ...]:
        return tuple(
            component
            for editable_tuple in self.tuples
            for component in editable_tuple.components
        )

    @property
    def spellings(self) -> tuple[str, ...]:
        return tuple(component.spelling for component in self.components)


def numeric_tuple(document: ThreeDFile, node_id: int) -> ThreeDNumericTuple | None:
    """Return an editable tuple only when its complete syntax is verified.

    This intentionally refuses generic ``tuple`` nodes and malformed coordinate
    shapes.  It does not infer geometry or follow references.
    """
    node = document.nodes_by_id.get(node_id)
    if node is None or node.kind not in _TUPLE_LABELS:
        return None
    significant = tuple(
        token
        for token in document.tokens[node.token_start:node.token_end]
        if token.kind not in _TRIVIA
    )
    labels = _TUPLE_LABELS[node.kind]
    if not _matches_numeric_tuple(significant, len(labels)):
        return None
    numbers = significant[1:-1:2]
    return ThreeDNumericTuple(
        node_id,
        node.kind,
        tuple(
            ThreeDNumericComponent(label, token.text, token.start, token.end)
            for label, token in zip(labels, numbers)
        ),
    )


def editable_values(document: ThreeDFile, node_id: int) -> ThreeDEditableValues | None:
    """Project verified point values onto a convenient selected source object.

    Only direct, recognized wrappers are inspected.  This does not search a
    subtree, follow references, or infer that a FACE/BSP plane is one point.
    """
    node = document.nodes_by_id.get(node_id)
    if node is None:
        return None
    direct = numeric_tuple(document, node_id)
    if direct is not None:
        return ThreeDEditableValues(node_id, direct.kind, (direct,))

    wrapper_id = node_id
    if node.kind == "definition":
        wrappers = tuple(
            child_id for child_id in node.children
            if document.nodes_by_id[child_id].kind in {"inline-point", "textured-vertex"}
        )
        if len(wrappers) != 1 or len(node.children) != 1:
            return None
        wrapper_id = wrappers[0]
        node = document.nodes_by_id[wrapper_id]
    if node.kind not in {"inline-point", "textured-vertex"}:
        return None

    tuples = tuple(
        editable
        for child_id in node.children
        if (editable := numeric_tuple(document, child_id)) is not None
    )
    expected = (
        ("coordinate",)
        if node.kind == "inline-point"
        else ("coordinate", "texcoord")
    )
    if tuple(item.kind for item in tuples) != expected:
        return None
    return ThreeDEditableValues(node_id, node.kind, tuples)


def validate_numeric_literal(value: str) -> None:
    """Require exactly one Papyrus number token, with no surrounding trivia."""
    tokens = tokenize(value)
    if (
        len(tokens) != 1
        or tokens[0].kind is not TokenKind.NUMBER
        or tokens[0].start != 0
        or tokens[0].end != len(value)
    ):
        raise ValueError(f"{value!r} is not a valid .3D number")


def _matches_numeric_tuple(tokens: tuple[Token, ...], arity: int) -> bool:
    if len(tokens) != arity * 2 + 1:
        return False
    if (
        tokens[0].kind is not TokenKind.OPEN
        or tokens[0].text != "<"
        or tokens[-1].kind is not TokenKind.CLOSE
        or tokens[-1].text != ">"
    ):
        return False
    for index in range(1, len(tokens) - 1):
        expected = TokenKind.NUMBER if index % 2 else TokenKind.COMMA
        if tokens[index].kind is not expected:
            return False
    return True
