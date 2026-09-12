from icr2_3dedit.app import statement_matches_filter
from icr2_3dedit.parser import parse_document


def test_outline_name_and_kind_filters_are_case_insensitive() -> None:
    parsed = parse_document("3D VERSION 3.0;\nFrontWheel: [<0,0,0>];\nbody: POLY {FrontWheel};\nmisc: DATA 1;")
    vertex = parsed.definitions["FrontWheel"]
    assert statement_matches_filter(vertex, "wheel", "All")
    assert statement_matches_filter(vertex, "FRONT", "Vertex")
    assert not statement_matches_filter(vertex, "rear", "Vertex")
    assert statement_matches_filter(parsed.definitions["misc"], "", "Other")
