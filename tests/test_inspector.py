from __future__ import annotations

from pathlib import Path
from time import perf_counter

from icr2_3dedit.app import (
    EditorWindow,
    LazyStructureTree,
    StructuralSelectionAnchor,
    capture_selection_anchor,
    resolve_selection_anchor,
)
from icr2_3dedit.editing import ThreeDEditSession
from icr2_3dedit.inspector import ThreeDInspectorModel
from icr2_3dedit.threedfile import ThreeDFile
from icr2_3dedit.values import editable_values


FIXTURES = Path(__file__).parent / "fixtures"


class FakeTree:
    """Small Treeview subset for display-free lazy-materialization tests."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.children: dict[str, list[str]] = {"": []}
        self.selected: tuple[str, ...] = ()
        self.selection_set_calls = 0
        self.seen: list[str] = []

    def insert(self, parent, _index, *, iid, text, values=(), tags=()):
        assert iid not in self.nodes
        self.nodes[iid] = {
            "parent": parent,
            "text": text,
            "values": values,
            "tags": tags,
        }
        self.children.setdefault(parent, []).append(iid)
        self.children.setdefault(iid, [])
        return iid

    def get_children(self, parent=""):
        return tuple(self.children.get(parent, ()))

    def delete(self, *items):
        for item in items:
            for child in tuple(self.children.get(item, ())):
                self.delete(child)
            node = self.nodes.pop(item, None)
            if node is not None:
                self.children[node["parent"]].remove(item)
            self.children.pop(item, None)

    def exists(self, item):
        return item in self.nodes

    def selection(self):
        return self.selected

    def selection_set(self, item):
        self.selection_set_calls += 1
        self.selected = (item,)

    def see(self, item):
        self.seen.append(item)

    def item(self, item, option=None, **kwargs):
        if kwargs:
            self.nodes[item].update(kwargs)
        if option is not None:
            return self.nodes[item].get(option, "")
        return self.nodes[item]


class NavigationHarness:
    """Display-free host for EditorWindow's navigation-history methods."""

    navigate_to = EditorWindow.navigate_to
    navigate_back = EditorWindow.navigate_back
    navigate_forward = EditorWindow.navigate_forward
    _navigate_history = EditorWindow._navigate_history

    def __init__(self, document: ThreeDFile, selected_node_id: int) -> None:
        self.document = document
        self.lazy_tree = self
        self._selected_node_id = selected_node_id
        self._navigation_back: list[StructuralSelectionAnchor] = []
        self._navigation_forward: list[StructuralSelectionAnchor] = []
        self.revealed: list[int] = []

    def reveal_node(self, node_id: int) -> None:
        self.revealed.append(node_id)

    def inspect_node(self, node_id: int) -> None:
        self._selected_node_id = node_id

    def _update_command_states(self) -> None:
        pass


def test_inspector_reports_source_references_and_reverse_references_without_expansion():
    document = ThreeDFile.from_bytes(
        b"3D VERSION 3.0;\npoint: [<1,2,3>];\nroot: LIST { point };\n"
    )
    model = ThreeDInspectorModel(document)
    root = document.symbols["root"][0]
    point = document.symbols["point"][0]

    references = model.references_from(root)
    assert [ref.name for ref in references] == ["point"]
    assert references[0].target_node_id == point
    assert model.reverse_references(point) == references
    assert model.source_page(root).text == document.node_text(root)
    assert model.line_and_column(root) == (3, 1)


def test_large_node_source_is_paged_into_bounded_exact_slices():
    body = ",".join("point" for _ in range(100))
    document = ThreeDFile.from_bytes(
        f"3D VERSION 3.0;\npoint: NIL;\nroot: LIST {{{body}}};\n".encode()
    )
    model = ThreeDInspectorModel(document)
    root = document.symbols["root"][0]
    pages = [model.source_page(root, index, page_chars=50) for index in range(20)]
    pages = pages[:pages[0].page_count]

    assert all(len(page.text) <= 50 for page in pages)
    assert "".join(page.text for page in pages) == document.node_text(root)


def test_coordinate_properties_expose_exact_component_spellings():
    document = ThreeDFile.from_bytes(
        b"3D VERSION 3.0;\npoint: [<+1.000, -.25, 3e2>];\n"
    )
    model = ThreeDInspectorModel(document)
    coordinate_id = next(
        node.node_id for node in document.nodes_by_id.values()
        if node.kind == "coordinate"
    )
    properties = dict(model.properties(coordinate_id))
    assert properties["X"] == "+1.000"
    assert properties["Y"] == "-.25"
    assert properties["Z"] == "3e2"


def test_inspector_search_returns_capped_structural_rows_without_tree_expansion():
    definitions = "\n".join(f"point_{index}: NIL;" for index in range(20))
    document = ThreeDFile.from_bytes(
        f"3D VERSION 3.0;\n{definitions}\nroot: LIST {{ point_3, point_13 }};\n".encode()
    )
    model = ThreeDInspectorModel(document)

    results = model.search("point_1", kind_filter="Definitions", limit=3)

    assert len(results) == 3
    assert all(document.nodes_by_id[result.node_id].kind == "definition" for result in results)
    assert [result.label for result in results] == ["point_1", "point_10", "point_11"]


def test_inspector_search_can_find_references_by_target_name():
    document = ThreeDFile.from_bytes(
        b"3D VERSION 3.0;\nfinish_line: NIL;\nroot: LIST { finish_line };\n"
    )
    model = ThreeDInspectorModel(document)

    results = model.search("finish", kind_filter="References")

    assert len(results) == 1
    assert results[0].kind == "reference"
    assert results[0].detail == "targets finish_line"


def test_named_textured_vertex_exposes_xyzuv_without_coordinate_drilldown():
    document = ThreeDFile.from_bytes(
        b"3D VERSION 3.0;\nvertex: [<+1, 2, 3>, T=<4, 5>];\n"
    )
    definition_id = document.symbols["vertex"][0]
    editable = editable_values(document, definition_id)
    assert editable is not None
    assert tuple(component.label for component in editable.components) == (
        "X", "Y", "Z", "U", "V",
    )
    assert editable.spellings == ("+1", "2", "3", "4", "5")
    properties = dict(ThreeDInspectorModel(document).properties(definition_id))
    assert tuple(properties[label] for label in ("X", "Y", "Z", "U", "V")) == editable.spellings


def test_face_definition_does_not_guess_values_from_descendant_plane_points():
    document = ThreeDFile.from_bytes(
        b"3D VERSION 3.0;\nroot: FACE ([<0,0,0>], [<1,0,0>], [<0,1,0>]) NIL;\n"
    )
    assert editable_values(document, document.symbols["root"][0]) is None


def test_tree_initially_materializes_only_top_level_structural_nodes():
    document = ThreeDFile.from_bytes(
        b"3D VERSION 3.0;\na: NIL;\nb: NIL;\nroot: LIST { a, LIST { b } };\n"
    )
    model = ThreeDInspectorModel(document)
    tree = FakeTree()
    lazy = LazyStructureTree(tree, model)
    lazy.populate_roots()

    structural_items = [item for item in tree.nodes if item.startswith("node:")]
    assert len(structural_items) == len(document.top_level_nodes)
    assert len(structural_items) < len(document.nodes_by_id)

    root = document.symbols["root"][0]
    lazy.materialize(lazy.node_item(root))
    materialized = {
        int(item.split(":", 1)[1])
        for item in tree.nodes
        if item.startswith("node:")
    }
    assert set(model.children(root)) <= materialized
    assert any(
        child not in materialized
        for direct in model.children(root)
        for child in model.children(direct)
    )


def test_selecting_an_already_selected_node_does_not_retrigger_tree_selection():
    document = ThreeDFile.from_bytes(b"3D VERSION 3.0;\nroot: NIL;\n")
    model = ThreeDInspectorModel(document)
    tree = FakeTree()
    lazy = LazyStructureTree(tree, model)
    lazy.populate_roots()
    root = document.symbols["root"][0]

    lazy.select_node(root)
    lazy.select_node(root)

    assert tree.selected == (lazy.node_item(root),)
    assert tree.selection_set_calls == 1
    assert tree.seen == [lazy.node_item(root), lazy.node_item(root)]


def test_reveal_node_materializes_only_its_ancestor_path():
    document = ThreeDFile.from_bytes(
        b"3D VERSION 3.0;\na: NIL;\nb: NIL;\nroot: LIST { LIST { a }, b };\n"
    )
    model = ThreeDInspectorModel(document)
    reference_id = next(ref.node_id for ref in document.references if ref.name == "a")
    tree = FakeTree()
    lazy = LazyStructureTree(tree, model)
    lazy.populate_roots()
    initial_structural = sum(item.startswith("node:") for item in tree.nodes)

    lazy.reveal_node(reference_id)

    path_length = 0
    current_id = reference_id
    while document.nodes_by_id[current_id].parent_id is not None:
        path_length += 1
        current_id = document.nodes_by_id[current_id].parent_id
    structural = [item for item in tree.nodes if item.startswith("node:")]
    assert lazy.node_item(reference_id) in tree.nodes
    assert len(structural) <= initial_structural + path_length
    assert len(structural) < len(document.nodes_by_id)


def test_back_and_forward_restore_source_node_selections():
    document = ThreeDFile.from_bytes(
        b"3D VERSION 3.0;\na: NIL;\nb: NIL;\nroot: LIST { a, b };\n"
    )
    a_id = document.symbols["a"][0]
    root_id = document.symbols["root"][0]
    harness = NavigationHarness(document, a_id)

    harness.navigate_to(root_id)
    assert harness._selected_node_id == root_id
    assert len(harness._navigation_back) == 1
    harness.navigate_back()
    assert harness._selected_node_id == a_id
    assert len(harness._navigation_forward) == 1
    harness.navigate_forward()
    assert harness._selected_node_id == root_id


def test_selection_anchor_restores_nested_source_location_after_rename():
    document = ThreeDFile.from_bytes(
        b"3D VERSION 3.0;\npoint: NIL;\nroot: LIST { point };\n"
    )
    root = document.symbols["root"][0]
    reference_id = next(ref.node_id for ref in document.references)
    anchor = capture_selection_anchor(document, reference_id)
    session = ThreeDEditSession(document)
    session.rename_definition(root, "renamed_root")

    restored = resolve_selection_anchor(session.document, anchor)
    assert restored is not None
    assert session.document.nodes_by_id[restored].kind == "reference"
    assert session.document.nodes_by_id[restored].name == "point"


def test_invalid_selection_anchors_fail_without_guessing():
    document = ThreeDFile.from_bytes(b"3D VERSION 3.0;\nroot: NIL;\n")
    assert capture_selection_anchor(document, None) is None
    assert capture_selection_anchor(document, 999_999) is None
    assert resolve_selection_anchor(document, StructuralSelectionAnchor(-1, ())) is None
    assert resolve_selection_anchor(document, StructuralSelectionAnchor(0, (99,))) is None


def test_wide_children_are_materialized_in_explicit_batches():
    definitions = "\n".join(f"p{i}: NIL;" for i in range(600))
    names = ",".join(f"p{i}" for i in range(600))
    document = ThreeDFile.from_bytes(
        f"3D VERSION 3.0;\n{definitions}\nroot: LIST {{{names}}};\n".encode()
    )
    model = ThreeDInspectorModel(document)
    tree = FakeTree()
    lazy = LazyStructureTree(tree, model, batch_size=25)
    lazy.populate_roots()
    root = document.symbols["root"][0]
    command = model.children(root)[0]

    lazy.materialize(lazy.node_item(root))
    lazy.materialize(lazy.node_item(command))
    list_items = next(
        node_id for node_id in model.children(command)
        if model.node(node_id).kind == "list-items"
    )
    lazy.materialize(lazy.node_item(list_items))

    structural_children = [
        item for item in tree.get_children(lazy.node_item(list_items))
        if item.startswith("node:")
    ]
    more = [
        item for item in tree.get_children(lazy.node_item(list_items))
        if item.startswith("more:")
    ]
    assert len(structural_children) == 25
    assert len(more) == 1


def test_reparsed_edit_repopulates_only_top_level_tree_rows():
    definitions = "\n".join(f"p{i}: NIL;" for i in range(600))
    names = ",".join(f"p{i}" for i in range(600))
    document = ThreeDFile.from_bytes(
        f"3D VERSION 3.0;\n{definitions}\nroot: LIST {{{names}}};\n".encode()
    )
    session = ThreeDEditSession(document)
    session.rename_definition(document.symbols["p0"][0], "first_point")
    model = ThreeDInspectorModel(session.document)
    tree = FakeTree()
    lazy = LazyStructureTree(tree, model)
    lazy.populate_roots()

    structural_items = [item for item in tree.nodes if item.startswith("node:")]
    assert len(structural_items) == len(session.document.top_level_nodes)
    assert len(structural_items) * 2 < len(session.document.nodes_by_id)
    assert lazy.node_item(session.document.symbols["first_point"][0]) in tree.nodes


def test_reno_inspector_projection_does_not_duplicate_the_structural_tree():
    document = ThreeDFile.load(FIXTURES / "RENO.3D")
    started = perf_counter()
    model = ThreeDInspectorModel(document)
    elapsed = perf_counter() - started
    tree = FakeTree()
    lazy = LazyStructureTree(tree, model)
    lazy.populate_roots()

    structural_items = [item for item in tree.nodes if item.startswith("node:")]
    assert len(document.nodes_by_id) > 90_000
    assert len(model.root_node_ids) == 4_413
    assert len(structural_items) == 4_413
    assert len(structural_items) * 10 < len(document.nodes_by_id)
    assert elapsed < 1.0
