from __future__ import annotations

from pathlib import Path
from time import perf_counter

from icr2_3dedit.app import LazyStructureTree
from icr2_3dedit.inspector import ThreeDInspectorModel
from icr2_3dedit.threedfile import ThreeDFile


FIXTURES = Path(__file__).parent / "fixtures"


class FakeTree:
    """Small Treeview subset for display-free lazy-materialization tests."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.children: dict[str, list[str]] = {"": []}

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
