"""Minimal, lazy document inspector for Papyrus .3D source files."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .inspector import TREE_CHILD_BATCH, ThreeDInspectorModel
from .parser import Statement
from .threedfile import ThreeDDiagnostic, ThreeDFile


LOGGER = logging.getLogger(__name__)
OUTLINE_KINDS = ("All", "Vertex", "POLY", "LIST", "BSPF", "DYNAMIC", "SUPEROBJ", "Other")


def statement_matches_filter(statement: Statement, name_filter: str, kind_filter: str) -> bool:
    """Retained for callers of the former outline helper."""
    if statement.name is None or name_filter.casefold() not in statement.name.casefold():
        return False
    normalized = "Vertex" if statement.kind == "vertex" else statement.kind.upper()
    if kind_filter == "All":
        return True
    if kind_filter == "Other":
        return normalized not in OUTLINE_KINDS[1:-1]
    return normalized == kind_filter


class LazyStructureTree:
    """Materialize structural children only when their parent is expanded."""

    PLACEHOLDER_TAG = "__placeholder__"
    MORE_TAG = "__more__"

    def __init__(
        self,
        tree: ttk.Treeview,
        model: ThreeDInspectorModel,
        batch_size: int = TREE_CHILD_BATCH,
    ) -> None:
        self.tree = tree
        self.model = model
        self.batch_size = batch_size
        self._more: dict[str, tuple[int, int]] = {}

    @staticmethod
    def node_item(node_id: int) -> str:
        return f"node:{node_id}"

    def clear(self) -> None:
        roots = self.tree.get_children("")
        if roots:
            self.tree.delete(*roots)
        self._more.clear()

    def populate_roots(self) -> None:
        self.clear()
        for node_id in self.model.root_node_ids:
            self._insert_node("", node_id)

    def _insert_node(self, parent_item: str, node_id: int) -> str:
        node = self.model.node(node_id)
        line, _ = self.model.line_and_column(node_id)
        item = self.node_item(node_id)
        self.tree.insert(
            parent_item,
            tk.END,
            iid=item,
            text=self.model.label(node_id),
            values=(node.kind, line, node_id),
        )
        # One cheap sentinel gives Treeview an expansion affordance. It is not
        # a structural-node widget and never recursively seeds descendants.
        if node.children:
            self.tree.insert(
                item,
                tk.END,
                iid=f"placeholder:{node_id}",
                text="",
                tags=(self.PLACEHOLDER_TAG,),
            )
        return item

    def materialize(self, item: str) -> None:
        if not item.startswith("node:"):
            return
        node_id = int(item.split(":", 1)[1])
        placeholder = f"placeholder:{node_id}"
        if self.tree.exists(placeholder):
            self.tree.delete(placeholder)
            self._insert_child_batch(item, node_id, 0)

    def _insert_child_batch(self, parent_item: str, parent_node_id: int, offset: int) -> None:
        children = self.model.children(parent_node_id)
        stop = min(len(children), offset + self.batch_size)
        for node_id in children[offset:stop]:
            self._insert_node(parent_item, node_id)
        if stop < len(children):
            more_item = f"more:{parent_node_id}:{stop}"
            remaining = len(children) - stop
            self.tree.insert(
                parent_item,
                tk.END,
                iid=more_item,
                text=f"Load next {min(self.batch_size, remaining)}… ({remaining} remaining)",
                values=("", "", ""),
                tags=(self.MORE_TAG,),
            )
            self._more[more_item] = (parent_node_id, stop)

    def load_more(self, item: str) -> bool:
        request = self._more.pop(item, None)
        if request is None:
            return False
        parent_node_id, offset = request
        parent_item = self.node_item(parent_node_id)
        self.tree.delete(item)
        self._insert_child_batch(parent_item, parent_node_id, offset)
        return True


class EditorWindow(tk.Tk):
    """Read-only structural browser backed exclusively by ThreeDFile."""

    def __init__(self) -> None:
        super().__init__()
        self.title("ICR2 3D Document Inspector")
        self.geometry("1320x800")
        self.minsize(920, 580)

        self.document: ThreeDFile | None = None
        self.model: ThreeDInspectorModel | None = None
        self.lazy_tree: LazyStructureTree | None = None
        self._load_generation = 0
        self._load_results: queue.Queue = queue.Queue()
        self._selected_node_id: int | None = None
        self._source_page_index = 0
        self._reference_rows = ()
        self._reverse_rows = ()
        self._diagnostic_by_item: dict[str, ThreeDDiagnostic] = {}
        self._closing = False

        self._build_menu()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.exit_inspector)
        self.after(50, self._poll_load_results)

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Open…", accelerator="Ctrl+O", command=self.open_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.exit_inspector)
        menu.add_cascade(label="File", menu=file_menu)
        self.config(menu=menu)
        self.bind_all("<Control-o>", lambda _event: self.open_file())

    def _build_ui(self) -> None:
        outer = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True)

        structure_frame = ttk.Frame(outer, padding=6)
        detail_frame = ttk.Frame(outer, padding=6)
        outer.add(structure_frame, weight=2)
        outer.add(detail_frame, weight=5)

        ttk.Label(structure_frame, text="Definition / structure explorer").pack(anchor=tk.W)
        tree_frame = ttk.Frame(structure_frame)
        tree_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.structure = ttk.Treeview(
            tree_frame,
            columns=("kind", "line", "node"),
            show="tree headings",
            selectmode="browse",
        )
        self.structure.heading("#0", text="Source object")
        self.structure.heading("kind", text="Kind")
        self.structure.heading("line", text="Line")
        self.structure.heading("node", text="NodeID")
        self.structure.column("#0", width=210)
        self.structure.column("kind", width=95, stretch=False)
        self.structure.column("line", width=55, stretch=False)
        self.structure.column("node", width=70, stretch=False)
        tree_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.structure.yview)
        tree_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self.structure.xview)
        self.structure.configure(yscrollcommand=tree_y.set, xscrollcommand=tree_x.set)
        self.structure.grid(row=0, column=0, sticky="nsew")
        tree_y.grid(row=0, column=1, sticky="ns")
        tree_x.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.structure.bind("<<TreeviewOpen>>", self._tree_opened)
        self.structure.bind("<<TreeviewSelect>>", self._tree_selected)
        self.structure.bind("<Double-1>", self._tree_double_clicked, add=True)
        self.structure.bind("<Return>", self._tree_activate, add=True)

        vertical = ttk.Panedwindow(detail_frame, orient=tk.VERTICAL)
        vertical.pack(fill=tk.BOTH, expand=True)
        top = ttk.Frame(vertical)
        source = ttk.Frame(vertical)
        vertical.add(top, weight=3)
        vertical.add(source, weight=2)

        notebook = ttk.Notebook(top)
        notebook.pack(fill=tk.BOTH, expand=True)
        properties_tab = ttk.Frame(notebook, padding=6)
        references_tab = ttk.Frame(notebook, padding=6)
        reverse_tab = ttk.Frame(notebook, padding=6)
        diagnostics_tab = ttk.Frame(notebook, padding=6)
        notebook.add(properties_tab, text="Node")
        notebook.add(references_tab, text="References from")
        notebook.add(reverse_tab, text="Referenced by")
        notebook.add(diagnostics_tab, text="Diagnostics")

        self.properties = ttk.Treeview(
            properties_tab, columns=("value",), show="tree headings", selectmode="none"
        )
        self.properties.heading("#0", text="Property")
        self.properties.heading("value", text="Value")
        self.properties.column("#0", width=155, stretch=False)
        self.properties.pack(fill=tk.BOTH, expand=True)

        self.references = tk.Listbox(references_tab, activestyle="dotbox")
        self.references.pack(fill=tk.BOTH, expand=True)
        self.references.bind("<Double-1>", self._reference_activated)
        self.reverse_references = tk.Listbox(reverse_tab, activestyle="dotbox")
        self.reverse_references.pack(fill=tk.BOTH, expand=True)
        self.reverse_references.bind("<Double-1>", self._reverse_reference_activated)

        self.diagnostics = ttk.Treeview(
            diagnostics_tab,
            columns=("severity", "line", "code"),
            show="tree headings",
        )
        self.diagnostics.heading("#0", text="Message")
        self.diagnostics.heading("severity", text="Level")
        self.diagnostics.heading("line", text="Line")
        self.diagnostics.heading("code", text="Code")
        self.diagnostics.column("severity", width=70, stretch=False)
        self.diagnostics.column("line", width=55, stretch=False)
        self.diagnostics.column("code", width=150, stretch=False)
        self.diagnostics.pack(fill=tk.BOTH, expand=True)
        self.diagnostics.bind("<Double-1>", self._diagnostic_activated)

        source_bar = ttk.Frame(source)
        source_bar.pack(fill=tk.X)
        self.source_label = ttk.Label(source_bar, text="Source for selected NodeID")
        self.source_label.pack(side=tk.LEFT)
        self.next_page = ttk.Button(source_bar, text="Next", width=7, command=lambda: self._change_source_page(1))
        self.next_page.pack(side=tk.RIGHT)
        self.previous_page = ttk.Button(source_bar, text="Previous", width=9, command=lambda: self._change_source_page(-1))
        self.previous_page.pack(side=tk.RIGHT, padx=(0, 4))

        source_frame = ttk.Frame(source)
        source_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.source = tk.Text(
            source_frame,
            wrap=tk.NONE,
            state=tk.DISABLED,
            font=("Consolas", 10),
            tabs=(32,),
        )
        source_y = ttk.Scrollbar(source_frame, orient=tk.VERTICAL, command=self.source.yview)
        source_x = ttk.Scrollbar(source_frame, orient=tk.HORIZONTAL, command=self.source.xview)
        self.source.configure(yscrollcommand=source_y.set, xscrollcommand=source_x.set)
        self.source.grid(row=0, column=0, sticky="nsew")
        source_y.grid(row=0, column=1, sticky="ns")
        source_x.grid(row=1, column=0, sticky="ew")
        source_frame.rowconfigure(0, weight=1)
        source_frame.columnconfigure(0, weight=1)

        self.status = ttk.Label(
            self,
            text="Open a Papyrus .3D source file to inspect it.",
            anchor=tk.W,
            relief=tk.SUNKEN,
        )
        self.status.pack(fill=tk.X, side=tk.BOTTOM)
        self._update_page_buttons(0, 1)

    def open_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="Open Papyrus .3D file",
            filetypes=(("Papyrus 3D source", "*.3d *.3D"), ("All files", "*.*")),
        )
        if filename:
            self.load_file(filename)

    def load_file(self, filename: str | Path) -> None:
        path = Path(filename)
        self._load_generation += 1
        generation = self._load_generation
        self.status.configure(text=f"Parsing {path.name}…")
        self.title(f"ICR2 3D Document Inspector — {path.name}")
        self._clear_document_views()

        def worker() -> None:
            try:
                document = ThreeDFile.load(path)
                model = ThreeDInspectorModel(document)
                self._load_results.put(("ok", generation, document, model))
            except Exception as error:
                LOGGER.exception("Could not load %s", path)
                self._load_results.put(("error", generation, path, error))

        threading.Thread(target=worker, name="3d-file-loader", daemon=True).start()

    def _poll_load_results(self) -> None:
        if self._closing:
            return
        try:
            while True:
                result = self._load_results.get_nowait()
                if result[1] != self._load_generation:
                    continue
                if result[0] == "error":
                    _, _, path, error = result
                    messagebox.showerror("Open failed", f"{path}\n\n{error}")
                    self.status.configure(text="Open failed.")
                else:
                    _, _, document, model = result
                    self._apply_document(document, model)
        except queue.Empty:
            pass
        if not self._closing:
            self.after(50, self._poll_load_results)

    def _apply_document(self, document: ThreeDFile, model: ThreeDInspectorModel) -> None:
        self.document = document
        self.model = model
        self.lazy_tree = LazyStructureTree(self.structure, model)
        self.lazy_tree.populate_roots()
        self._populate_diagnostics()
        self.status.configure(
            text=(
                f"{len(document.top_level_nodes):,} definitions · "
                f"{len(document.nodes_by_id):,} structural nodes · "
                f"{len(document.references):,} references · "
                f"{len(document.diagnostics):,} diagnostics · "
                f"parsed in {document.parse_seconds:.2f}s"
            )
        )

    def _clear_document_views(self) -> None:
        roots = self.structure.get_children("")
        if roots:
            self.structure.delete(*roots)
        for tree in (self.properties, self.diagnostics):
            rows = tree.get_children("")
            if rows:
                tree.delete(*rows)
        self.references.delete(0, tk.END)
        self.reverse_references.delete(0, tk.END)
        self._set_source_text("")
        self._diagnostic_by_item.clear()
        self.document = None
        self.model = None
        self.lazy_tree = None
        self._selected_node_id = None

    def _tree_opened(self, _event: tk.Event) -> None:
        if self.lazy_tree is not None:
            self.lazy_tree.materialize(self.structure.focus())

    def _tree_selected(self, _event: tk.Event) -> None:
        selected = self.structure.selection()
        if not selected or self.lazy_tree is None:
            return
        item = selected[0]
        if self.lazy_tree.load_more(item):
            return
        if item.startswith("node:"):
            self.inspect_node(int(item.split(":", 1)[1]))

    def _tree_double_clicked(self, event: tk.Event) -> None:
        item = self.structure.identify_row(event.y)
        if item and self.lazy_tree is not None:
            self.lazy_tree.load_more(item)

    def _tree_activate(self, _event: tk.Event) -> None:
        selected = self.structure.selection()
        if selected and self.lazy_tree is not None:
            self.lazy_tree.load_more(selected[0])

    def inspect_node(self, node_id: int) -> None:
        if self.model is None:
            return
        self._selected_node_id = node_id
        self._source_page_index = 0
        self._populate_properties(node_id)
        self._populate_references(node_id)
        self._show_node_source()
        item = LazyStructureTree.node_item(node_id)
        if self.structure.exists(item):
            self.structure.selection_set(item)
            self.structure.see(item)

    def _populate_properties(self, node_id: int) -> None:
        rows = self.properties.get_children("")
        if rows:
            self.properties.delete(*rows)
        assert self.model is not None
        for key, value in self.model.properties(node_id):
            self.properties.insert("", tk.END, text=key, values=(value,))

    def _populate_references(self, node_id: int) -> None:
        assert self.model is not None
        self.references.delete(0, tk.END)
        self._reference_rows = self.model.references_from(node_id)
        for ref in self._reference_rows:
            target = (
                f"Node {ref.target_node_id}"
                if ref.target_node_id is not None
                else "ambiguous" if ref.ambiguous else "unresolved"
            )
            line, _ = self.model.line_and_column(ref.node_id)
            self.references.insert(tk.END, f"{ref.name} → {target}  (line {line})")
        if not self._reference_rows:
            self.references.insert(tk.END, "(none)")

        self.reverse_references.delete(0, tk.END)
        self._reverse_rows = self.model.reverse_references(node_id)
        for ref in self._reverse_rows:
            line, _ = self.model.line_and_column(ref.node_id)
            self.reverse_references.insert(tk.END, f"Node {ref.node_id}  (line {line})")
        if not self._reverse_rows:
            self.reverse_references.insert(tk.END, "(none)")

    def _reference_activated(self, _event: tk.Event) -> None:
        selected = self.references.curselection()
        if not selected or selected[0] >= len(self._reference_rows):
            return
        ref = self._reference_rows[selected[0]]
        self.inspect_node(ref.target_node_id if ref.target_node_id is not None else ref.node_id)

    def _reverse_reference_activated(self, _event: tk.Event) -> None:
        selected = self.reverse_references.curselection()
        if selected and selected[0] < len(self._reverse_rows):
            self.inspect_node(self._reverse_rows[selected[0]].node_id)

    def _show_node_source(self) -> None:
        if self.model is None or self._selected_node_id is None:
            return
        page = self.model.source_page(self._selected_node_id, self._source_page_index)
        self._source_page_index = page.page_index
        self._set_source_text(page.text)
        self.source_label.configure(
            text=(
                f"Exact source · chars {page.absolute_start:,}–{page.absolute_end:,} "
                f"of Node {self._selected_node_id} "
                f"· page {page.page_index + 1}/{page.page_count}"
            )
        )
        self._update_page_buttons(page.page_index, page.page_count)

    def _change_source_page(self, delta: int) -> None:
        if self._selected_node_id is not None:
            self._source_page_index += delta
            self._show_node_source()

    def _set_source_text(self, text: str) -> None:
        self.source.configure(state=tk.NORMAL)
        self.source.delete("1.0", tk.END)
        if text:
            self.source.insert("1.0", text)
        self.source.configure(state=tk.DISABLED)

    def _update_page_buttons(self, page_index: int, page_count: int) -> None:
        self.previous_page.configure(state=tk.NORMAL if page_index > 0 else tk.DISABLED)
        self.next_page.configure(state=tk.NORMAL if page_index + 1 < page_count else tk.DISABLED)

    def _populate_diagnostics(self) -> None:
        assert self.document is not None
        rows = self.diagnostics.get_children("")
        if rows:
            self.diagnostics.delete(*rows)
        self._diagnostic_by_item.clear()
        for diagnostic in self.document.diagnostics:
            item = self.diagnostics.insert(
                "",
                tk.END,
                text=diagnostic.message,
                values=(diagnostic.severity, diagnostic.line, diagnostic.code),
            )
            self._diagnostic_by_item[item] = diagnostic

    def _diagnostic_activated(self, _event: tk.Event) -> None:
        selected = self.diagnostics.selection()
        if not selected or self.model is None:
            return
        diagnostic = self._diagnostic_by_item.get(selected[0])
        if diagnostic is None:
            return
        page = self.model.diagnostic_source_page(diagnostic)
        self._selected_node_id = None
        self._set_source_text(page.text)
        self.source_label.configure(
            text=f"Diagnostic context · exact source chars {page.absolute_start:,}–{page.absolute_end:,}"
        )
        self._update_page_buttons(0, 1)

    def exit_inspector(self) -> None:
        self._closing = True
        self._load_generation += 1
        self.destroy()


def main() -> None:
    EditorWindow().mainloop()
