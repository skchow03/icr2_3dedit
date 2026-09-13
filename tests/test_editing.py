from pathlib import Path

import pytest

from icr2_3dedit.editing import ThreeDEditSession
from icr2_3dedit.serializer import ThreeDSerializer, ThreeDSourceEdit
from icr2_3dedit.threedfile import ThreeDFile


def test_serializer_copies_untouched_source_and_builds_inverse_edits():
    source = "a:\t[<+1.000, 2, -0>];\r\n% exact comment\r\nroot: LIST { a };\r\n"
    start = source.index("root")
    result = ThreeDSerializer.apply(source, [ThreeDSourceEdit(start, start + 4, "main_root")])
    assert result.text == source[:start] + "main_root" + source[start + 4:]
    restored = ThreeDSerializer.apply(result.text, result.inverse_edits)
    assert restored.text == source


def test_serializer_rejects_overlapping_and_out_of_bounds_edits():
    with pytest.raises(ValueError, match="overlap"):
        ThreeDSerializer.apply("abcdef", [
            ThreeDSourceEdit(1, 4, "x"), ThreeDSourceEdit(3, 5, "y"),
        ])
    with pytest.raises(ValueError, match="beyond"):
        ThreeDSerializer.apply("abc", [ThreeDSourceEdit(1, 4, "x")])


def test_multiple_length_changing_edits_are_exactly_reversible():
    source = "abcdefghij"
    edits = [
        ThreeDSourceEdit(1, 2, "LONG"),
        ThreeDSourceEdit(5, 7, ""),
        ThreeDSourceEdit(9, 9, "INSERT"),
    ]
    result = ThreeDSerializer.apply(source, edits)
    assert result.text == "aLONGcdehiINSERTj"
    assert ThreeDSerializer.apply(result.text, result.inverse_edits).text == source


def test_rename_updates_only_resolved_references_and_is_exactly_reversible():
    raw = (
        b"3D VERSION 3.0;\r\n"
        b"point:\t[<+1.000, 2, -0>]; % keep me\r\n"
        b"root: LIST { point, point };\r\n"
    )
    session = ThreeDEditSession(ThreeDFile.from_bytes(raw))
    point_id = session.document.symbols["point"][0]
    renamed_id = session.rename_definition(point_id, "front_point")

    assert session.document.dirty
    assert session.document.nodes_by_id[renamed_id].name == "front_point"
    assert [ref.name for ref in session.document.references] == ["front_point", "front_point"]
    assert b"\t[<+1.000, 2, -0>]; % keep me\r\n" in session.document.to_bytes()
    assert session.can_undo and not session.can_redo

    session.undo()
    assert session.document.to_bytes() == raw
    assert not session.document.dirty
    assert session.can_redo

    session.redo()
    assert session.document.to_bytes().count(b"front_point") == 3
    assert session.document.dirty


def test_new_edit_after_undo_discards_redo_history():
    raw = b"3D VERSION 3.0;\na: NIL;\nb: LIST { a };\n"
    session = ThreeDEditSession(ThreeDFile.from_bytes(raw))
    session.rename_definition(session.document.symbols["a"][0], "first")
    session.undo()
    session.rename_definition(session.document.symbols["a"][0], "second")
    assert not session.can_redo
    assert b"second" in session.document.to_bytes()


def test_rename_rejects_invalid_reserved_duplicate_and_non_definition_names():
    doc = ThreeDFile.from_bytes(b"3D VERSION 3.0;\na: NIL;\nb: LIST { a };\n")
    for invalid in ("", "two words", "1point", "LIST"):
        session = ThreeDEditSession(doc)
        with pytest.raises(ValueError):
            session.rename_definition(doc.symbols["a"][0], invalid)
    session = ThreeDEditSession(doc)
    with pytest.raises(ValueError, match="already exists"):
        session.rename_definition(doc.symbols["a"][0], "b")
    reference_id = next(ref.node_id for ref in doc.references)
    with pytest.raises(ValueError, match="named definition"):
        session.rename_definition(reference_id, "renamed")


def test_renaming_duplicate_definition_does_not_guess_at_ambiguous_references():
    raw = b"3D VERSION 3.0;\na: NIL;\na: NIL;\nroot: LIST { a };\n"
    session = ThreeDEditSession(ThreeDFile.from_bytes(raw))
    session.rename_definition(session.document.symbols["a"][0], "first_a")
    assert b"root: LIST { a };" in session.document.to_bytes()
    assert session.document.symbols["a"]
    assert session.document.symbols["first_a"]


def test_cp1252_and_utf8_bom_survive_edits():
    cp1252 = "3D VERSION 3.0;\r\na: DATA \"café\";\r\nroot: LIST { a };\r\n".encode("cp1252")
    cp_session = ThreeDEditSession(ThreeDFile.from_bytes(cp1252))
    cp_session.rename_definition(cp_session.document.symbols["a"][0], "accented")
    assert "café".encode("cp1252") in cp_session.document.to_bytes()
    assert cp_session.document.encoding == "cp1252"

    bom = b"\xef\xbb\xbf3D VERSION 3.0;\nroot: NIL;\n"
    bom_session = ThreeDEditSession(ThreeDFile.from_bytes(bom))
    bom_session.rename_definition(bom_session.document.symbols["root"][0], "main")
    assert bom_session.document.to_bytes().startswith(b"\xef\xbb\xbf")


def test_session_save_sets_new_baseline_for_dirty_tracking(tmp_path: Path):
    raw = b"3D VERSION 3.0;\na: NIL;\nroot: LIST { a };\n"
    session = ThreeDEditSession(ThreeDFile.from_bytes(raw))
    session.rename_definition(session.document.symbols["a"][0], "point")
    destination = tmp_path / "edited.3D"
    session.save(destination)
    saved = destination.read_bytes()
    assert saved == session.document.to_bytes()
    assert not session.document.dirty
    assert ThreeDFile.load(destination).to_bytes() == saved

    session.undo()
    assert session.document.dirty
    session.redo()
    assert not session.document.dirty


@pytest.mark.parametrize("fixture_name", ["roadcar.3d", "RENO.3D"])
def test_real_fixture_localized_rename_saves_and_reopens_losslessly(
    fixture_name: str,
    tmp_path: Path,
):
    path = Path(__file__).parent / "fixtures" / fixture_name
    raw = path.read_bytes()
    session = ThreeDEditSession(ThreeDFile.from_bytes(raw))
    reference = next(ref for ref in session.document.references if ref.target_node_id is not None)
    target = session.document.nodes_by_id[reference.target_node_id]
    new_name = f"{target.name}_EDIT_TEST"
    session.rename_definition(target.node_id, new_name)

    destination = tmp_path / fixture_name
    session.save(destination)
    edited = destination.read_bytes()
    reopened = ThreeDFile.load(destination)
    assert reopened.to_bytes() == edited
    assert new_name in reopened.symbols
    assert target.name not in reopened.symbols
    assert all(ref.name != target.name for ref in reopened.references)
