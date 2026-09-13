"""Command-based source editing for the authoritative :class:`ThreeDFile`."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .document import atomic_write
from .serializer import ThreeDSerializer, ThreeDSourceEdit
from .syntax import RESERVED_WORDS, TokenKind, tokenize
from .threedfile import ThreeDFile
from .values import numeric_tuple, validate_numeric_literal


@dataclass(frozen=True, slots=True)
class ThreeDEditCommand:
    """One reversible edit transaction."""

    description: str
    edits: tuple[ThreeDSourceEdit, ...]
    inverse_edits: tuple[ThreeDSourceEdit, ...]


class ThreeDEditSession:
    """Own a current document and a linear, command-based undo history.

    Source edits are applied only when a command is committed.  The resulting
    bytes are reparsed once to refresh syntax, symbols, references, and
    diagnostics.  No reference graph is expanded by this process.
    """

    def __init__(self, document: ThreeDFile) -> None:
        self.document = document
        self._clean_bytes = document.to_bytes()
        self._undo_stack: list[ThreeDEditCommand] = []
        self._redo_stack: list[ThreeDEditCommand] = []

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    @property
    def undo_description(self) -> str | None:
        return self._undo_stack[-1].description if self._undo_stack else None

    @property
    def redo_description(self) -> str | None:
        return self._redo_stack[-1].description if self._redo_stack else None

    def execute(
        self,
        description: str,
        edits: Iterable[ThreeDSourceEdit],
    ) -> ThreeDFile:
        edit_tuple = tuple(edits)
        if not edit_tuple:
            return self.document
        result = ThreeDSerializer.apply(self.document.source_text, edit_tuple)
        if result.text == self.document.source_text:
            return self.document
        command = ThreeDEditCommand(description, edit_tuple, result.inverse_edits)
        self._replace_document(result.text)
        self._undo_stack.append(command)
        self._redo_stack.clear()
        return self.document

    def undo(self) -> ThreeDFile:
        if not self._undo_stack:
            return self.document
        command = self._undo_stack.pop()
        result = ThreeDSerializer.apply(self.document.source_text, command.inverse_edits)
        self._replace_document(result.text)
        self._redo_stack.append(command)
        return self.document

    def redo(self) -> ThreeDFile:
        if not self._redo_stack:
            return self.document
        command = self._redo_stack.pop()
        result = ThreeDSerializer.apply(self.document.source_text, command.edits)
        self._replace_document(result.text)
        self._undo_stack.append(command)
        return self.document

    def rename_definition(self, node_id: int, new_name: str) -> int:
        """Rename one definition and references resolved to that exact NodeID.

        Ambiguous and unresolved references are intentionally untouched.  The
        returned NodeID belongs to the newly parsed document instance.
        """
        node = self.document.nodes_by_id.get(node_id)
        if node is None or node.kind != "definition" or node.name is None:
            raise ValueError("node_id must identify a named definition")
        old_name = node.name
        self._validate_identifier(new_name)
        if new_name == old_name:
            return node_id
        if new_name in self.document.symbols:
            raise ValueError(f"definition {new_name!r} already exists")

        name_token = next(
            (
                token for token in self.document.tokens[node.token_start:node.token_end]
                if token.kind is TokenKind.IDENTIFIER and token.text == old_name
            ),
            None,
        )
        if name_token is None:
            raise ValueError("definition name token could not be located")

        edits = [ThreeDSourceEdit(name_token.start, name_token.end, new_name)]
        edits.extend(
            ThreeDSourceEdit(reference.start, reference.end, new_name)
            for reference in self.document.references
            if reference.target_node_id == node_id
        )
        self.execute(f"Rename {old_name} to {new_name}", edits)
        renamed = self.document.symbols.get(new_name, [])
        if len(renamed) != 1:
            raise RuntimeError("renamed definition did not reparse uniquely")
        return renamed[0]

    def edit_numeric_tuple(self, node_id: int, values: Iterable[str]) -> int:
        """Edit a coordinate/texcoord by replacing only its number tokens.

        All changed components are committed as one undoable transaction.  The
        returned NodeID belongs to the freshly parsed document.
        """
        editable = numeric_tuple(self.document, node_id)
        if editable is None:
            raise ValueError("node_id must identify a valid coordinate or texcoord")
        replacements = tuple(values)
        if len(replacements) != len(editable.components):
            raise ValueError(
                f"{editable.kind} requires {len(editable.components)} values"
            )
        for replacement in replacements:
            validate_numeric_literal(replacement)
        edits = tuple(
            ThreeDSourceEdit(component.start, component.end, replacement)
            for component, replacement in zip(editable.components, replacements)
            if replacement != component.spelling
        )
        self.execute(f"Edit {editable.kind} values", edits)
        reparsed = numeric_tuple(self.document, node_id)
        if reparsed is None:
            raise RuntimeError("edited numeric tuple did not reparse at its source location")
        return reparsed.node_id

    def save(self, path: str | Path | None = None) -> Path:
        destination = Path(path) if path is not None else self.document.path
        if destination is None:
            raise ValueError("A destination is required")
        data = self.document.to_bytes()
        atomic_write(destination, data)
        self.document.path = destination
        self._clean_bytes = data
        self.document.dirty = False
        return destination

    def _replace_document(self, text: str) -> None:
        current = self.document
        raw = ThreeDSerializer.encode(text, current.encoding, current.has_utf8_bom)
        replacement = ThreeDFile.from_bytes(raw)
        replacement.path = current.path
        replacement.dirty = raw != self._clean_bytes
        self.document = replacement

    @staticmethod
    def _validate_identifier(name: str) -> None:
        tokens = tokenize(name)
        if (
            len(tokens) != 1
            or tokens[0].kind is not TokenKind.IDENTIFIER
            or tokens[0].start != 0
            or tokens[0].end != len(name)
        ):
            raise ValueError(f"{name!r} is not a valid .3D identifier")
        if name.upper() in RESERVED_WORDS:
            raise ValueError(f"{name!r} is reserved by the .3D language")
