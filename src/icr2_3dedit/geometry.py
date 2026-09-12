"""Typed, read-only geometry layered on the lossless statement parser."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re

from .parser import ParsedDocument, Statement


NUMBER_RE = re.compile(r"[+-]?(?:(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|inf(?:inity)?|nan)\Z", re.IGNORECASE)
VERTEX_START_RE = re.compile(r"\s*\[\s*<", re.DOTALL)


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class VertexDefinition:
    name: str
    x: float
    y: float
    z: float
    statement: Statement
    x_span: SourceSpan
    y_span: SourceSpan
    z_span: SourceSpan
    raw_x: str
    raw_y: str
    raw_z: str

    @property
    def coordinates(self) -> tuple[float, float, float]:
        return self.x, self.y, self.z

    @property
    def distance_from_origin(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)


@dataclass(frozen=True, slots=True)
class Bounds3D:
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    min_z: float
    max_z: float

    @property
    def size_x(self) -> float:
        return self.max_x - self.min_x

    @property
    def size_y(self) -> float:
        return self.max_y - self.min_y

    @property
    def size_z(self) -> float:
        return self.max_z - self.min_z

    @property
    def center(self) -> tuple[float, float, float]:
        return (
            (self.min_x + self.max_x) / 2,
            (self.min_y + self.max_y) / 2,
            (self.min_z + self.max_z) / 2,
        )


@dataclass(frozen=True, slots=True)
class GeometryIssue:
    code: str
    message: str
    statement: Statement
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class GeometryModel:
    vertices: dict[str, VertexDefinition]
    bounds: Bounds3D | None
    issues: tuple[GeometryIssue, ...] = field(default_factory=tuple)

    def coincident_names(self, vertex: VertexDefinition) -> tuple[str, ...]:
        return tuple(
            name for name, other in self.vertices.items()
            if name != vertex.name and other.coordinates == vertex.coordinates
        )


def build_geometry_model(document: ParsedDocument) -> GeometryModel:
    """Parse vertex definitions without changing or regenerating source text."""
    vertices: dict[str, VertexDefinition] = {}
    issues: list[GeometryIssue] = []
    for statement in document.statements:
        parsed, statement_issues = _parse_vertex(statement)
        issues.extend(statement_issues)
        if parsed is not None and parsed.name not in vertices:
            vertices[parsed.name] = parsed

    by_coordinates: dict[tuple[float, float, float], VertexDefinition] = {}
    for vertex in vertices.values():
        previous = by_coordinates.get(vertex.coordinates)
        if previous is not None:
            issues.append(GeometryIssue(
                "duplicate-coordinate",
                f"Vertices {previous.name} and {vertex.name} use identical coordinates",
                vertex.statement,
                SourceSpan(vertex.statement.name_start or vertex.statement.start,
                           vertex.statement.name_end or vertex.statement.end),
            ))
        else:
            by_coordinates[vertex.coordinates] = vertex

    bounds = None
    if vertices:
        values = tuple(vertices.values())
        bounds = Bounds3D(
            min(v.x for v in values), max(v.x for v in values),
            min(v.y for v in values), max(v.y for v in values),
            min(v.z for v in values), max(v.z for v in values),
        )
    return GeometryModel(vertices, bounds, tuple(issues))


def _parse_vertex(statement: Statement) -> tuple[VertexDefinition | None, list[GeometryIssue]]:
    rhs = statement.rhs
    if statement.name is None or rhs is None or statement.rhs_start is None:
        return None, []
    opening = VERTEX_START_RE.match(rhs)
    if opening is None:
        return None, []
    close = rhs.find(">", opening.end())
    if close < 0:
        span = SourceSpan(statement.rhs_start + opening.end() - 1, statement.rhs_end or statement.end)
        return None, [GeometryIssue("malformed-vertex", "Malformed vertex definition: missing '>'", statement, span)]

    coordinate_text = rhs[opening.end():close]
    base = statement.rhs_start + opening.end()
    pieces = _comma_pieces(coordinate_text, base)
    issues: list[GeometryIssue] = []
    if len(pieces) < 3:
        position = statement.rhs_start + close
        issues.append(GeometryIssue("missing-coordinate", f"Vertex {statement.name} is missing a coordinate", statement, SourceSpan(position, position)))
    elif len(pieces) > 3:
        raw, start, end = pieces[3]
        issues.append(GeometryIssue("extra-coordinate", f"Vertex {statement.name} has an extra coordinate", statement, SourceSpan(start, end)))

    parsed: list[tuple[float, str, SourceSpan]] = []
    for index, (raw, start, end) in enumerate(pieces[:3]):
        axis = "XYZ"[index]
        if not raw or NUMBER_RE.fullmatch(raw) is None:
            issues.append(GeometryIssue("non-numeric-coordinate", f"Vertex {statement.name} has a non-numeric {axis} coordinate", statement, SourceSpan(start, end)))
            continue
        value = float(raw)
        if not math.isfinite(value):
            issues.append(GeometryIssue("non-finite-coordinate", f"Vertex {statement.name} has a non-finite {axis} coordinate", statement, SourceSpan(start, end)))
            continue
        parsed.append((value, raw, SourceSpan(start, end)))
    if issues or len(parsed) != 3:
        return None, issues
    (x, raw_x, x_span), (y, raw_y, y_span), (z, raw_z, z_span) = parsed
    return VertexDefinition(statement.name, x, y, z, statement, x_span, y_span, z_span, raw_x, raw_y, raw_z), []


def _comma_pieces(text: str, base: int) -> list[tuple[str, int, int]]:
    result = []
    cursor = 0
    for piece in text.split(","):
        left = len(piece) - len(piece.lstrip())
        right = len(piece.rstrip())
        result.append((piece[left:right], base + cursor + left, base + cursor + right))
        cursor += len(piece) + 1
    return result
