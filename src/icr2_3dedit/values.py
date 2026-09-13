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
