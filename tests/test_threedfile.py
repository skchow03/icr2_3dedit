from pathlib import Path
from icr2_3dedit.threedfile import ThreeDFile

def test_byte_exact_round_trip():
    raw=b"3D VERSION 3.0;\r\n\r\na: [<1.000, 2, -3>];\r\n% comment\r\nfoo: LIST { a };\r\n"; doc=ThreeDFile.from_bytes(raw); assert doc.to_bytes()==raw

def test_semicolonless_header_does_not_swallow_first_definition():
    raw=(b"3D VERSION 3.0\r\n" b"__TSO0: DYNAMIC -3614452, 2473032, 102000, 120, 0, 0, 1, EXTERN \"stand100\";\r\n" b"__TSO1: DYNAMIC -4468161, 2288751, 102000, 120, 0, 0, 1, EXTERN \"stand100\";\r\n" b"root: LIST { __TSO0, __TSO1 };\r\n")
    doc=ThreeDFile.from_bytes(raw); assert "__TSO0" in doc.symbols; assert [doc.nodes_by_id[n].name for n in doc.top_level_nodes]==["__TSO0","__TSO1","root"]
    ref=next(r for r in doc.references if r.name=="__TSO0"); assert ref.target_node_id==doc.symbols["__TSO0"][0]; assert not any(d.code=="unresolved-reference" and "__TSO0" in d.message for d in doc.diagnostics); assert doc.to_bytes()==raw

def test_papyrus_commands_are_not_references():
    raw=(b"3D VERSION 3.0;\n" b"nil: NIL;\n" b"a: [<0, 0, 0>];\n" b"b: [<1, 0, 0>];\n" b"c: [<0, 1, 0>];\n" b"p: POLY <1> {a,b,c};\n" b"face: FACE2 (a,b,c), p, p;\n" b"near: BSPN (a,b,c), face, p;\n" b"around: BSPA (a,b,c), p, face, near;\n" b"both: BSP2 (a,b,c), p, face, near;\n" b"front: BSPF (a,b,c), nil, p, both;\n")
    doc=ThreeDFile.from_bytes(raw); commands={"NIL","POLY","FACE2","BSPN","BSPA","BSP2","BSPF"}; assert not commands.intersection(r.name.upper() for r in doc.references); assert not [d for d in doc.diagnostics if d.code=="unresolved-reference"]; assert doc.to_bytes()==raw

def test_top_level_order_and_stable_internal_nodes():
    doc=ThreeDFile.from_bytes(b"3D VERSION 3.0;\nA: NIL;\nC: NIL;\nB: NIL;\n"); assert [doc.nodes_by_id[n].name for n in doc.top_level_nodes]==["A","C","B"]; assert len(set(doc.nodes_by_id))==len(doc.nodes_by_id)

def test_nested_commands_are_explicit_structural_nodes():
    raw=b"3D VERSION 3.0;\nbar: NIL;\nbaz: NIL;\nfoo: LIST { bar, LIST { baz } };\n"
    doc=ThreeDFile.from_bytes(raw); foo=doc.symbols["foo"][0]
    outer=next(doc.nodes_by_id[n] for n in doc.nodes_by_id[foo].children if doc.nodes_by_id[n].kind=="command" and doc.nodes_by_id[n].command=="LIST")
    outer_group=next(doc.nodes_by_id[n] for n in outer.children if doc.nodes_by_id[n].kind=="list-items")
    inner=next(doc.nodes_by_id[n] for n in outer_group.children if doc.nodes_by_id[n].kind=="command" and doc.nodes_by_id[n].command=="LIST")
    inner_group=next(doc.nodes_by_id[n] for n in inner.children if doc.nodes_by_id[n].kind=="list-items")
    bar_ref=next(doc.nodes_by_id[r.node_id] for r in doc.references if r.name=="bar"); baz_ref=next(doc.nodes_by_id[r.node_id] for r in doc.references if r.name=="baz")
    assert bar_ref.parent_id==outer_group.node_id; assert baz_ref.parent_id==inner_group.node_id; assert doc.to_bytes()==raw

def test_command_nodes_identify_bsp_and_face_constructs():
    raw=b"3D VERSION 3.0;\na: NIL;\nb: NIL;\nc: NIL;\np: FACE2 (a,b,c), a, b;\nroot: BSPN (a,b,c), p, b;\n"
    doc=ThreeDFile.from_bytes(raw); commands={n.command for n in doc.nodes_by_id.values() if n.kind=="command"}; assert {"FACE2","BSPN"}<=commands; assert not doc.diagnostics; assert doc.to_bytes()==raw

def test_inline_point_is_distinct_from_named_definition():
    raw=b"3D VERSION 3.0;\nnamed: [<1,2,3>];\nface: FACE ([<4,5,6>], [<7,8,9>], named), named;\n"
    doc=ThreeDFile.from_bytes(raw)
    assert "named" in doc.symbols
    inline=[n for n in doc.nodes_by_id.values() if n.kind=="inline-point"]
    assert len(inline)==3
    assert all(n.name is None for n in inline)
    assert doc.to_bytes()==raw

def test_face_plane_owns_all_three_inline_points():
    raw=b"3D VERSION 3.0;\nface: FACE ([<1,2,3>], [<4,5,6>], [<7,8,9>]), NIL;\n"
    doc=ThreeDFile.from_bytes(raw); face=doc.symbols["face"][0]
    cmd=next(doc.nodes_by_id[n] for n in doc.nodes_by_id[face].children if doc.nodes_by_id[n].kind=="command")
    plane=next(doc.nodes_by_id[n] for n in cmd.children if doc.nodes_by_id[n].kind=="plane")
    assert [doc.nodes_by_id[n].kind for n in plane.children]==["inline-point","inline-point","inline-point"]
    assert all([doc.nodes_by_id[c].kind for c in doc.nodes_by_id[n].children]==["coordinate"] for n in plane.children)

def test_poly_owns_all_of_its_argument_groups():
    raw=b"3D VERSION 3.0;\na: NIL;\nb: NIL;\nc: NIL;\np: POLY [T] <2> {a,b,c};\n"
    doc=ThreeDFile.from_bytes(raw); p=doc.symbols["p"][0]
    poly=next(doc.nodes_by_id[n] for n in doc.nodes_by_id[p].children if doc.nodes_by_id[n].kind=="command" and doc.nodes_by_id[n].command=="POLY")
    child_kinds=[doc.nodes_by_id[n].kind for n in poly.children]
    assert child_kinds==["record","tuple","poly-items"]
    assert {r.name for r in doc.references if doc.nodes_by_id[r.node_id].parent_id in poly.children}=={"a","b","c"}
    assert doc.to_bytes()==raw

def test_trk23d_textured_vertices_are_single_records():
    raw=(b"3D VERSION 3.0;\n"
         b"__dirt__: NIL;\n"
         b"p: POLY [T] __dirt__.c {"
         b"[<1,2,3>, t=<10,20>],"
         b"[<4,5,6>, t=<30,40>],"
         b"[<7,8,9>, t=<50,60>]};\n")
    doc=ThreeDFile.from_bytes(raw); p=doc.symbols["p"][0]
    poly=next(doc.nodes_by_id[n] for n in doc.nodes_by_id[p].children if doc.nodes_by_id[n].kind=="command")
    items=next(doc.nodes_by_id[n] for n in poly.children if doc.nodes_by_id[n].kind=="poly-items")
    vertices=[doc.nodes_by_id[n] for n in items.children if doc.nodes_by_id[n].kind=="textured-vertex"]
    assert len(vertices)==3
    for vertex in vertices:
        assert [doc.nodes_by_id[n].kind for n in vertex.children]==["coordinate","texcoord"]
    assert doc.to_bytes()==raw

def test_children_remain_in_source_order_after_references_are_added():
    raw=b"3D VERSION 3.0;\na: NIL;\nb: NIL;\nroot: LIST { a, LIST { b }, a };\n"
    doc=ThreeDFile.from_bytes(raw); root=doc.symbols["root"][0]
    outer=next(doc.nodes_by_id[n] for n in doc.nodes_by_id[root].children if doc.nodes_by_id[n].kind=="command")
    items=next(doc.nodes_by_id[n] for n in outer.children if doc.nodes_by_id[n].kind=="list-items")
    children=[doc.nodes_by_id[n] for n in items.children]
    assert [n.kind for n in children]==["reference","command","reference"]
    assert [n.start for n in children]==sorted(n.start for n in children)

def test_polygon_is_not_a_reserved_command_alias():
    doc=ThreeDFile.from_bytes(b"3D VERSION 3.0;\nPOLYGON: NIL;\nroot: LIST { POLYGON };\n")
    assert "POLYGON" in doc.symbols
    ref=next(r for r in doc.references if r.name=="POLYGON")
    assert ref.target_node_id==doc.symbols["POLYGON"][0]

def test_forward_reference_resolves_without_expansion():
    doc=ThreeDFile.from_bytes(b"3D VERSION 3.0;\nfoo: LIST { later };\nlater: NIL;\n"); ref=next(r for r in doc.references if r.name=="later"); assert ref.target_node_id==doc.symbols["later"][0]; assert doc.nodes_by_id[ref.node_id].kind=="reference"

def test_duplicate_and_unresolved_are_diagnostics_not_parse_failures():
    raw=b"3D VERSION 3.0;\na: NIL;\na: NIL;\nfoo: LIST { missing, a };\n"; doc=ThreeDFile.from_bytes(raw); assert len(doc.symbols["a"])==2; codes={d.code for d in doc.diagnostics}; assert {"duplicate-symbol","unresolved-reference","ambiguous-reference"}<=codes; assert doc.to_bytes()==raw

def test_comments_whitespace_and_number_spelling_survive():
    raw=b"3D VERSION 3.0;\n\n% hello\npoint:\t[<+1.000, .5, -0>];   % tail\n"; doc=ThreeDFile.from_bytes(raw); assert doc.to_bytes()==raw; assert "+1.000" in doc.source_text; assert "% tail" in doc.source_text

def test_deep_nesting_does_not_use_python_recursion():
    depth=1500; raw=("3D VERSION 3.0;\nfoo: "+"LIST{"*depth+"NIL"+"}"*depth+";\n").encode(); doc=ThreeDFile.from_bytes(raw); assert doc.to_bytes()==raw; assert doc.max_nesting_depth>=depth

def test_real_fixtures_round_trip_when_present():
    fixture_dir=Path(__file__).parent/"fixtures"
    for name in ("roadcar.3d","RENO.3D"):
        path=fixture_dir/name
        if path.exists():
            raw=path.read_bytes(); doc=ThreeDFile.from_bytes(raw); assert doc.to_bytes()==raw; assert doc.top_level_nodes; assert not doc.diagnostics

def _command(doc, parent_id, name):
    return next(
        doc.nodes_by_id[n]
        for n in doc.nodes_by_id[parent_id].children
        if doc.nodes_by_id[n].kind=="command" and doc.nodes_by_id[n].command==name
    )

def test_face_owns_its_child_expression():
    raw=(b"3D VERSION 3.0;\n"
         b"root: FACE ([<0,0,0>], [<1,0,0>], [<0,1,0>]), "
         b"LIST { NIL };\n")
    doc=ThreeDFile.from_bytes(raw); root=doc.symbols["root"][0]
    face=_command(doc,root,"FACE")
    assert [doc.nodes_by_id[n].kind for n in face.children]==["plane","command"]
    child=doc.nodes_by_id[face.children[1]]
    assert child.command=="LIST"
    assert child.parent_id==face.node_id
    assert doc.node_text(face.node_id).lstrip().startswith("FACE")
    assert "LIST { NIL }" in doc.node_text(face.node_id)

def test_face_and_bsp_fixed_arity_children_nest_in_source_order():
    cases={
        "FACE": 1,
        "FACE2": 2,
        "BSPF": 3,
        "BSPA": 3,
        "BSP2": 4,
        "BSPN": 2,
    }
    for command,arity in cases.items():
        children=", ".join("NIL" for _ in range(arity))
        raw=f"3D VERSION 3.0;\nroot: {command} ([<0,0,0>], [<1,0,0>], [<0,1,0>]), {children};\n".encode()
        doc=ThreeDFile.from_bytes(raw); root=doc.symbols["root"][0]
        node=_command(doc,root,command)
        assert doc.nodes_by_id[node.children[0]].kind=="plane"
        owned=[doc.nodes_by_id[n] for n in node.children[1:]]
        assert len(owned)==arity
        assert all(child.command=="NIL" and child.parent_id==node.node_id for child in owned)
        assert [child.start for child in owned]==sorted(child.start for child in owned)

def test_nested_bsp_material_and_poly_form_expression_tree():
    raw=(b"3D VERSION 3.0;\n"
         b"color: [<0,0,0>, c=<32>];\n"
         b"root: BSPA ([<0,0,0>], [<1,0,0>], [<0,1,0>]), "
         b"BSPA ([<0,0,0>], [<1,0,0>], [<0,1,0>]), "
         b"LIST { NIL }, MATERIAL GROUP=2, POLY color.c { [<0,0,0>] }, NIL, "
         b"NIL, LIST { NIL };\n")
    doc=ThreeDFile.from_bytes(raw); root=doc.symbols["root"][0]
    outer=_command(doc,root,"BSPA")
    outer_children=[doc.nodes_by_id[n] for n in outer.children if doc.nodes_by_id[n].kind=="command"]
    assert [n.command for n in outer_children]==["BSPA","NIL","LIST"]
    inner=outer_children[0]
    inner_children=[doc.nodes_by_id[n] for n in inner.children if doc.nodes_by_id[n].kind=="command"]
    assert [n.command for n in inner_children]==["LIST","MATERIAL","NIL"]
    material=inner_children[1]
    assert _command(doc,material.node_id,"POLY").parent_id==material.node_id

def test_material_dynamic_and_superobj_own_their_expression_arguments():
    raw=(b"3D VERSION 3.0;\n"
         b"point: NIL;\n"
         b"panel: MATERIAL GROUP=2, MIP=\"wall\", point;\n"
         b"placed: DYNAMIC 0,0,0,0,0,0,1, EXTERN \"stand\";\n"
         b"root: SUPEROBJ panel, {placed, point};\n")
    doc=ThreeDFile.from_bytes(raw)
    material=_command(doc,doc.symbols["panel"][0],"MATERIAL")
    assert [doc.nodes_by_id[n].name for n in material.children if doc.nodes_by_id[n].kind=="reference"]==["point"]
    dynamic=_command(doc,doc.symbols["placed"][0],"DYNAMIC")
    assert _command(doc,dynamic.node_id,"EXTERN").parent_id==dynamic.node_id
    superobj=_command(doc,doc.symbols["root"][0],"SUPEROBJ")
    assert [doc.nodes_by_id[n].kind for n in superobj.children]==["reference","superobj-items"]
    items=doc.nodes_by_id[superobj.children[1]]
    assert [doc.nodes_by_id[n].name for n in items.children]==["placed","point"]

def test_collection_and_switch_groups_have_specific_structural_kinds():
    raw=(b"3D VERSION 3.0;\n"
         b"a: NIL;\n"
         b"line: LINE <32> {a,a};\n"
         b"data: DATA {1,2,3,4};\n"
         b"dyno: DYNO {1,2,3,4};\n"
         b"lod: SWITCH DISTANCE ([<0,0,0>]) > {(100 ? NIL), (0 ? a)};\n")
    doc=ThreeDFile.from_bytes(raw)
    expected={"line":"line-items","data":"data-values","dyno":"dyno-values"}
    for definition,kind in expected.items():
        command=next(doc.nodes_by_id[n] for n in doc.nodes_by_id[doc.symbols[definition][0]].children if doc.nodes_by_id[n].kind=="command")
        assert any(doc.nodes_by_id[n].kind==kind for n in command.children)
    switch=_command(doc,doc.symbols["lod"][0],"SWITCH")
    assert [doc.nodes_by_id[n].kind for n in switch.children]==["switch-origin","switch-cases"]
    cases=doc.nodes_by_id[switch.children[1]]
    assert [doc.nodes_by_id[n].kind for n in cases.children]==["switch-case","switch-case"]
