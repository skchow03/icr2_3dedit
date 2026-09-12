from pathlib import Path

import pytest

from icr2_3dedit.analysis import Severity, analyze
from icr2_3dedit.geometry import build_geometry_model
from icr2_3dedit.parser import parse_document


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0", 0.0), ("-12", -12.0), ("1.25", 1.25), (".5", .5), ("-.5", -.5), ("+3", 3.0), ("1e2", 100.0)],
)
def test_supported_number_forms(raw: str, expected: float) -> None:
    source = f"3D VERSION 3.0;\nv: [<{raw}, 0, 0>];\n"
    vertex = build_geometry_model(parse_document(source)).vertices["v"]
    assert vertex.x == expected
    assert vertex.raw_x == raw


def test_exact_coordinate_spans_and_multiline_definition() -> None:
    source = "3D VERSION 3.0;\nv: [< .5,\n -02.50,\n +3 >];\n"
    vertex = build_geometry_model(parse_document(source)).vertices["v"]
    assert source[vertex.x_span.start:vertex.x_span.end] == ".5"
    assert source[vertex.y_span.start:vertex.y_span.end] == "-02.50"
    assert source[vertex.z_span.start:vertex.z_span.end] == "+3"


@pytest.mark.parametrize(
    ("coordinates", "code"),
    [("1, 2", "missing-coordinate"), ("1, 2, 3, 4", "extra-coordinate"),
     ("1, nope, 3", "non-numeric-coordinate"), ("1, inf, 3", "non-finite-coordinate"),
     ("1, NaN, 3", "non-finite-coordinate")],
)
def test_malformed_vertices(coordinates: str, code: str) -> None:
    model = build_geometry_model(parse_document(f"3D VERSION 3.0;\nbad: [<{coordinates}>];\n"))
    assert not model.vertices
    assert code in [issue.code for issue in model.issues]
    diagnostic = next(d for d in analyze(parse_document(f"3D VERSION 3.0;\nbad: [<{coordinates}>];\n")) if code.split("-")[0] in d.message.lower() or code == "non-finite-coordinate")
    assert diagnostic.severity is Severity.ERROR
    assert diagnostic.start is not None


def test_no_vertices_has_no_bounds_and_ordinary_value_is_not_malformed() -> None:
    model = build_geometry_model(parse_document("3D VERSION 3.0;\nroot: LIST {NIL};\n"))
    assert model.bounds is None
    assert model.issues == ()


def test_bounds_positive_negative_and_one_vertex() -> None:
    model = build_geometry_model(parse_document("3D VERSION 3.0;\na: [<-4,2,-8>];\nb: [<6,-3,2>];"))
    assert model.bounds is not None
    assert (model.bounds.min_x, model.bounds.max_x, model.bounds.size_x) == (-4, 6, 10)
    assert model.bounds.center == (1, -.5, -3)
    one = build_geometry_model(parse_document("3D VERSION 3.0;\na: [<2.5,-3,9>];"))
    assert one.bounds is not None
    assert one.bounds.center == (2.5, -3, 9)
    assert (one.bounds.size_x, one.bounds.size_y, one.bounds.size_z) == (0, 0, 0)


def test_duplicate_coordinate_is_informational() -> None:
    parsed = parse_document("3D VERSION 3.0;\na: [<1,2,3>];\nb: [<1,2,3>];\nroot: LIST {a,b};")
    model = build_geometry_model(parsed)
    assert model.coincident_names(model.vertices["a"]) == ("b",)
    duplicate = next(d for d in analyze(parsed, model) if "identical coordinates" in d.message)
    assert duplicate.severity is Severity.INFO


def test_synthetic_fixture_parses_texture_suffix() -> None:
    source = (FIXTURES / "vertices_synthetic.3d").read_text()
    model = build_geometry_model(parse_document(source))
    assert set(model.vertices) == {"integer_vertex", "decimal_vertex", "leading_decimal_vertex", "textured_vertex"}
    assert model.vertices["textured_vertex"].coordinates == (10, 20, 30)


def test_roadcar_fixture_count_bounds_and_unchanged_bytes() -> None:
    path = FIXTURES / "roadcar.3d"
    before = path.read_bytes()
    source = before.decode("ascii")
    model = build_geometry_model(parse_document(source))
    analyze(parse_document(source), model)
    assert len(model.vertices) == 325
    assert model.bounds is not None
    assert (model.bounds.min_x, model.bounds.max_x) == (-47082, 57171)
    assert (model.bounds.min_y, model.bounds.max_y) == (-19998, 19998)
    assert (model.bounds.min_z, model.bounds.max_z) == (-8501, 10334)
    assert path.read_bytes() == before
