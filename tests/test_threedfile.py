from pathlib import Path

from icr2_3dedit.threedfile import ThreeDFile


def test_byte_exact_round_trip():
    raw = b"3D VERSION 3.0;\r\n\r\na: [<1.000, 2, -3>];\r\n% comment\r\nfoo: LIST { a };\r\n"
    doc = ThreeDFile.from_bytes(raw)
    assert doc.to_bytes() == raw


def test_semicolonless_header_does_not_swallow_first_definition():
    raw = (
        b"3D VERSION 3.0\r\n"
        b"__TSO0: DYNAMIC -3614452, 2473032, 102000, 120, 0, 0, 1, EXTERN \"stand100\";\r\n"
        b"__TSO1: DYNAMIC -4468161, 2288751, 102000, 120, 0, 0, 1, EXTERN \"stand100\";\r\n"
        b"root: LIST { __TSO0, __TSO1 };\r\n"
    )
    doc = ThreeDFile.from_bytes(raw)
    assert "__TSO0" in doc.symbols
    assert "__TSO1" in doc.symbols
    assert [doc.nodes_by_id[n].name for n in doc.top_level_nodes] == ["__TSO0", "__TSO1", "root"]
    tso0_ref = next(r for r in doc.references if r.name == "__TSO0")
    assert tso0_ref.target_node_id == doc.symbols["__TSO0"][0]
    assert not any(d.code == "unresolved-reference" and "__TSO0" in d.message for d in doc.diagnostics)
    assert doc.to_bytes() == raw


def test_top_level_order_and_stable_internal_nodes():
    doc = ThreeDFile.from_bytes(b"3D VERSION 3.0;\nA: NIL;\nC: NIL;\nB: NIL;\n")
    assert [doc.nodes_by_id[n].name for n in doc.top_level_nodes] == ["A", "C", "B"]
    assert len(set(doc.nodes_by_id)) == len(doc.nodes_by_id)


def test_nested_constructs_get_nodes_and_parentage():
    raw = b"3D VERSION 3.0;\nbar: NIL;\nbaz: NIL;\nfoo: LIST { bar, LIST { baz } };\n"
    doc = ThreeDFile.from_bytes(raw)
    foo = doc.symbols["foo"][0]
    groups = [n for n in doc.nodes_by_id.values() if n.kind == "group" and n.parent_id == foo]
    assert groups
    nested = [n for n in doc.nodes_by_id.values() if n.kind == "group" and n.parent_id in {g.node_id for g in groups}]
    assert nested
    refs = {r.name: r for r in doc.references}
    assert refs["bar"].target_node_id == doc.symbols["bar"][0]
    assert refs["baz"].target_node_id == doc.symbols["baz"][0]


def test_forward_reference_resolves_without_expansion():
    doc = ThreeDFile.from_bytes(b"3D VERSION 3.0;\nfoo: LIST { later };\nlater: NIL;\n")
    ref = next(r for r in doc.references if r.name == "later")
    assert ref.target_node_id == doc.symbols["later"][0]
    assert doc.nodes_by_id[ref.node_id].kind == "reference"


def test_duplicate_and_unresolved_are_diagnostics_not_parse_failures():
    raw = b"3D VERSION 3.0;\na: NIL;\na: NIL;\nfoo: LIST { missing, a };\n"
    doc = ThreeDFile.from_bytes(raw)
    assert len(doc.symbols["a"]) == 2
    codes = {d.code for d in doc.diagnostics}
    assert "duplicate-symbol" in codes
    assert "unresolved-reference" in codes
    assert "ambiguous-reference" in codes
    assert doc.to_bytes() == raw


def test_comments_whitespace_and_number_spelling_survive():
    raw = b"3D VERSION 3.0;\n\n% hello\npoint:\t[<+1.000, .5, -0>];   % tail\n"
    doc = ThreeDFile.from_bytes(raw)
    assert doc.to_bytes() == raw
    assert "+1.000" in doc.source_text
    assert "% tail" in doc.source_text


def test_deep_nesting_does_not_use_python_recursion():
    depth = 1500
    raw = ("3D VERSION 3.0;\nfoo: " + "LIST{" * depth + "NIL" + "}" * depth + ";\n").encode()
    doc = ThreeDFile.from_bytes(raw)
    assert doc.to_bytes() == raw
    assert doc.max_nesting_depth >= depth


def test_real_fixtures_round_trip_when_present():
    fixture_dir = Path(__file__).parent / "fixtures"
    for name in ("roadcar.3d", "RENO.3D"):
        path = fixture_dir / name
        if path.exists():
            raw = path.read_bytes()
            doc = ThreeDFile.from_bytes(raw)
            assert doc.to_bytes() == raw
            assert doc.top_level_nodes
