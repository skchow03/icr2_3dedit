"""Initial Tk desktop shell for the ICR2 .3D editor."""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .analysis import analyze
from .document import SourceDocument
from .parser import ParsedDocument, Statement, parse_document
from .semantics import build_reference_graph
from .geometry import GeometryModel, VertexDefinition, build_geometry_model
from .responsive import (GenerationGuard, HIGHLIGHT_OPERATION_BUDGET,
                         highlight_spans, line_offsets, offsets_for_lines,
                         viewport_line_range)


OUTLINE_KINDS = ("All", "Vertex", "POLY", "LIST", "BSPF", "DYNAMIC", "SUPEROBJ", "Other")
LOGGER = logging.getLogger(__name__)


def _timed(timings: dict[str, float], name: str, function, *args):
    started = time.perf_counter()
    value = function(*args)
    timings[name] = time.perf_counter() - started
    return value


def _analyze_snapshot(generation: int, source: str):
    """Perform every widget-free analysis stage on an immutable snapshot."""
    timings: dict[str, float] = {}
    parsed = _timed(timings, "parsing", parse_document, source)
    geometry = _timed(timings, "geometry model", build_geometry_model, parsed)
    graph = _timed(timings, "reference graph", build_reference_graph, parsed)
    diagnostics = _timed(timings, "diagnostics analysis", analyze, parsed, geometry)
    return generation, parsed, geometry, graph, diagnostics, timings


def statement_matches_filter(statement: Statement, name_filter: str, kind_filter: str) -> bool:
    """Display-only outline predicate; it never changes the parsed model."""
    if statement.name is None or name_filter.casefold() not in statement.name.casefold():
        return False
    normalized = "Vertex" if statement.kind == "vertex" else statement.kind.upper()
    if kind_filter == "All":
        return True
    if kind_filter == "Other":
        return normalized not in OUTLINE_KINDS[1:-1]
    return normalized == kind_filter


class EditorWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ICR2 3D Editor")
        self.geometry("1200x760")
        self.minsize(850, 520)
        self.document = SourceDocument("")
        self.parsed = parse_document("")
        self.geometry_model = build_geometry_model(self.parsed)
        self.reference_graph = build_reference_graph(self.parsed)
        self._refresh_job: str | None = None
        self._highlight_job: str | None = None
        self._guard = GenerationGuard()
        self._parsed_generation = -1
        self._closing = False
        self._line_offsets = line_offsets("")
        self._token_starts: tuple[int, ...] = ()
        self._analysis_condition = threading.Condition()
        self._pending_analysis: tuple[int, str] | None = None
        self._analysis_results: queue.Queue = queue.Queue()
        self._worker = threading.Thread(target=self._analysis_worker, name="3d-analysis", daemon=True)
        self._worker.start()
        self._statement_by_item: dict[str, Statement] = {}
        self._diagnostic_by_item: dict[str, object] = {}
        self._build_menu()
        self._build_ui()
        self._configure_highlighting()
        self._set_text("3D VERSION 3.0;\n\nnil: NIL;\n")
        self.document = SourceDocument(self.editor.get("1.0", "end-1c"))
        self._update_title()
        self.protocol("WM_DELETE_WINDOW", self.exit_editor)
        self.after(50, self._poll_analysis_results)

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="New", accelerator="Ctrl+N", command=self.new_file)
        file_menu.add_command(label="Open…", accelerator="Ctrl+O", command=self.open_file)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_file)
        file_menu.add_command(label="Save As…", accelerator="Ctrl+Shift+S", command=self.save_file_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.exit_editor)
        menu.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="Find…", accelerator="Ctrl+F", command=self.find_dialog)
        edit_menu.add_command(label="Find Next", accelerator="F3", command=self.find_next)
        edit_menu.add_command(label="Find Previous", accelerator="Shift+F3", command=lambda: self.find_next(backwards=True))
        edit_menu.add_command(label="Go to Line…", accelerator="Ctrl+G", command=self.go_to_line)
        edit_menu.add_separator()
        edit_menu.add_command(label="Go to Definition", accelerator="F12", command=self.go_to_definition)
        edit_menu.add_command(label="List References", accelerator="Shift+F12", command=self.list_references)
        menu.add_cascade(label="Edit", menu=edit_menu)

        tools_menu = tk.Menu(menu, tearoff=False)
        tools_menu.add_command(label="Analyze", accelerator="F7", command=self.refresh_analysis)
        menu.add_cascade(label="Tools", menu=tools_menu)
        self.config(menu=menu)
        self.bind_all("<Control-n>", lambda _event: self.new_file())
        self.bind_all("<Control-o>", lambda _event: self.open_file())
        self.bind_all("<Control-s>", lambda _event: self.save_file())
        self.bind_all("<Control-Shift-S>", lambda _event: self.save_file_as())
        self.bind_all("<F7>", lambda _event: self.refresh_analysis())
        self.bind_all("<Control-f>", lambda _event: self.find_dialog())
        self.bind_all("<F3>", lambda _event: self.find_next())
        self.bind_all("<Shift-F3>", lambda _event: self.find_next(backwards=True))
        self.bind_all("<Control-g>", lambda _event: self.go_to_line())
        self.bind_all("<F12>", lambda _event: self.go_to_definition())
        self.bind_all("<Shift-F12>", lambda _event: self.list_references())

    def _build_ui(self) -> None:
        outer = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(outer, padding=4)
        center = ttk.Frame(outer, padding=4)
        right = ttk.Frame(outer, padding=4)
        outer.add(left, weight=1)
        outer.add(center, weight=4)
        outer.add(right, weight=2)

        ttk.Label(left, text="Document outline").pack(anchor=tk.W)
        filters = ttk.Frame(left)
        filters.pack(fill=tk.X, pady=(2, 4))
        self.outline_filter = tk.StringVar()
        filter_entry = ttk.Entry(filters, textvariable=self.outline_filter)
        filter_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.outline_kind = tk.StringVar(value="All")
        ttk.Combobox(filters, textvariable=self.outline_kind, values=OUTLINE_KINDS, state="readonly", width=10).pack(side=tk.LEFT, padx=(4, 0))
        self.outline_filter.trace_add("write", lambda *_args: self._populate_outline())
        self.outline_kind.trace_add("write", lambda *_args: self._populate_outline())
        outline_frame = ttk.Frame(left)
        outline_frame.pack(fill=tk.BOTH, expand=True)
        self.outline = ttk.Treeview(outline_frame, columns=("kind", "line"), show="tree headings")
        self.outline.heading("#0", text="Name")
        self.outline.heading("kind", text="Kind")
        self.outline.heading("line", text="Line")
        self.outline.column("#0", width=150)
        self.outline.column("kind", width=75, stretch=False)
        self.outline.column("line", width=45, stretch=False)
        outline_scroll = ttk.Scrollbar(outline_frame, orient=tk.VERTICAL, command=self.outline.yview)
        self.outline.configure(yscrollcommand=outline_scroll.set)
        self.outline.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        outline_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.outline.bind("<<TreeviewSelect>>", self._outline_selected)

        ttk.Label(center, text="Source").pack(anchor=tk.W)
        editor_frame = ttk.Frame(center)
        editor_frame.pack(fill=tk.BOTH, expand=True)
        self.editor = tk.Text(
            editor_frame,
            undo=True,
            wrap=tk.NONE,
            font=("Consolas", 11),
            tabs=(32,),
        )
        self.line_numbers = tk.Canvas(
            editor_frame,
            width=36,
            highlightthickness=0,
            background="#f2f2f2",
        )
        vertical = ttk.Scrollbar(editor_frame, orient=tk.VERTICAL, command=self.editor.yview)
        horizontal = ttk.Scrollbar(editor_frame, orient=tk.HORIZONTAL, command=self.editor.xview)
        self.editor.configure(
            yscrollcommand=lambda first, last: self._editor_scrolled(vertical, first, last),
            xscrollcommand=horizontal.set,
        )
        self.line_numbers.grid(row=0, column=0, sticky="ns")
        self.editor.grid(row=0, column=1, sticky="nsew")
        vertical.grid(row=0, column=2, sticky="ns")
        horizontal.grid(row=1, column=1, sticky="ew")
        editor_frame.rowconfigure(0, weight=1)
        editor_frame.columnconfigure(1, weight=1)
        self.editor.bind("<<Modified>>", self._text_modified)
        self.editor.bind("<ButtonRelease-1>", self._cursor_changed)
        self.editor.bind("<KeyRelease>", self._cursor_changed)
        self.editor.bind("<Configure>", self._viewport_changed, add=True)

        notebook = ttk.Notebook(right)
        notebook.pack(fill=tk.BOTH, expand=True)
        inspector_tab = ttk.Frame(notebook, padding=6)
        diagnostics_tab = ttk.Frame(notebook, padding=6)
        geometry_tab = ttk.Frame(notebook, padding=6)
        notebook.add(inspector_tab, text="Inspector")
        notebook.add(diagnostics_tab, text="Diagnostics")
        notebook.add(geometry_tab, text="Geometry")

        self.inspector = tk.Text(inspector_tab, wrap=tk.WORD, state=tk.DISABLED, width=32)
        self.inspector.pack(fill=tk.BOTH, expand=True)
        self.diagnostics = ttk.Treeview(
            diagnostics_tab,
            columns=("severity", "line"),
            show="tree headings",
        )
        self.diagnostics.heading("#0", text="Message")
        self.diagnostics.heading("severity", text="Level")
        self.diagnostics.heading("line", text="Line")
        self.diagnostics.column("severity", width=65, stretch=False)
        self.diagnostics.column("line", width=45, stretch=False)
        self.diagnostics.pack(fill=tk.BOTH, expand=True)
        self.diagnostics.bind("<Double-1>", self._diagnostic_selected)
        self.geometry_summary = ttk.Label(geometry_tab, anchor=tk.NW, justify=tk.LEFT)
        self.geometry_summary.pack(fill=tk.BOTH, expand=True)

        self.status = ttk.Label(self, text="Ready", anchor=tk.W, relief=tk.SUNKEN)
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

    def _configure_highlighting(self) -> None:
        self.editor.tag_configure("definition", foreground="#005a9c", font=("Consolas", 11, "bold"))
        self.editor.tag_configure("command", foreground="#7a3e9d")
        self.editor.tag_configure("number", foreground="#a04400")
        self.editor.tag_configure("comment", foreground="#238636", font=("Consolas", 11, "italic"))
        self.editor.tag_configure("selected_statement", background="#fff4c2")

    def _set_text(self, text: str) -> None:
        started = time.perf_counter()
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", text)
        LOGGER.info("open stage insertion into Text: %.3fs", time.perf_counter() - started)
        self.editor.edit_modified(False)
        generation = self._guard.invalidate()
        self._line_offsets = line_offsets(text)
        self._parsed_generation = -1
        self.status.configure(text="Loading source…")
        self._schedule_highlight()
        # Let Tk paint and accept input before structural work begins.
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
        self._refresh_job = self.after_idle(lambda: self._begin_analysis(generation, text))

    def _text_modified(self, _event: tk.Event) -> None:
        if not self.editor.edit_modified():
            return
        self.editor.edit_modified(False)
        self.document.text = self.editor.get("1.0", "end-1c")
        self._line_offsets = line_offsets(self.document.text)
        self._guard.invalidate()
        self._parsed_generation = -1
        self._update_title()
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
        generation, source = self._guard.generation, self.document.text
        self._refresh_job = self.after(250, lambda: self._begin_analysis(generation, source))
        self._redraw_line_numbers()
        self._schedule_highlight()

    def _editor_scrolled(
        self,
        scrollbar: ttk.Scrollbar,
        first: str,
        last: str,
    ) -> None:
        scrollbar.set(first, last)
        self._redraw_line_numbers()
        self._schedule_highlight()

    def _viewport_changed(self, event: tk.Event | None = None) -> None:
        self._redraw_line_numbers(event)
        self._schedule_highlight()

    def _redraw_line_numbers(self, _event: tk.Event | None = None) -> None:
        """Draw numbers beside each source line currently visible in the editor."""

        started = time.perf_counter()
        self.line_numbers.delete("all")
        index = self.editor.index("@0,0")
        while True:
            display = self.editor.dlineinfo(index)
            if display is None:
                break
            y = display[1]
            line = index.split(".", 1)[0]
            self.line_numbers.create_text(
                self.line_numbers.winfo_width() - 6,
                y,
                anchor="ne",
                text=line,
                fill="#666666",
                font=("Consolas", 10),
            )
            index = self.editor.index(f"{index}+1line")

        digits = max(2, len(self.editor.index("end-1c").split(".", 1)[0]))
        self.line_numbers.configure(width=12 + digits * 8)
        LOGGER.debug("refresh stage line numbers: %.3fs", time.perf_counter() - started)

    def _refresh_model(self) -> None:
        """Compatibility entry point: enqueue, rather than blocking Tk."""
        self._refresh_job = None
        text = self.editor.get("1.0", "end-1c")
        self.document.text = text
        generation = self._guard.invalidate()
        self._line_offsets = line_offsets(text)
        self._begin_analysis(generation, text)

    def _begin_analysis(self, generation: int, source: str) -> None:
        self._refresh_job = None
        if not self._guard.accepts(generation):
            return
        self.status.configure(text="Analyzing…")
        with self._analysis_condition:
            self._pending_analysis = (generation, source)
            self._analysis_condition.notify()

    def _analysis_worker(self) -> None:
        while True:
            with self._analysis_condition:
                while self._pending_analysis is None and not self._closing:
                    self._analysis_condition.wait()
                if self._closing:
                    return
                request, self._pending_analysis = self._pending_analysis, None
            try:
                self._analysis_results.put(("ok", _analyze_snapshot(*request)))
            except Exception:
                self._analysis_results.put(("error", request[0], traceback.format_exc()))

    def _poll_analysis_results(self) -> None:
        if self._closing:
            return
        try:
            while True:
                result = self._analysis_results.get_nowait()
                if result[0] == "error":
                    if self._guard.accepts(result[1]):
                        LOGGER.error("Deferred analysis failed:\n%s", result[2])
                        messagebox.showerror("Analysis failed", "Analysis failed; details were written to the log.")
                    continue
                _, payload = result
                self._apply_analysis_result(*payload)
        except queue.Empty:
            pass
        except Exception:
            LOGGER.exception("Deferred Tk callback failed")
            messagebox.showerror("Refresh failed", "The editor refresh failed; details were written to the log.")
        if not self._closing:
            self.after(50, self._poll_analysis_results)

    def _apply_analysis_result(self, generation, parsed, geometry, graph, diagnostics, timings) -> None:
        if not self._guard.accepts(generation):
            return
        self.parsed, self.geometry_model, self.reference_graph = parsed, geometry, graph
        self._parsed_generation = generation
        self._token_starts = tuple(token.start for token in parsed.tokens)
        started = time.perf_counter()
        self._populate_outline()
        timings["outline population"] = time.perf_counter() - started
        started = time.perf_counter()
        self._show_geometry_summary()
        timings["geometry summary"] = time.perf_counter() - started
        started = time.perf_counter()
        self._populate_diagnostics(diagnostics)
        timings["diagnostics population"] = time.perf_counter() - started
        self._highlight_source()
        self.status.configure(text=f"{len(parsed.definitions)} definitions, {len(parsed.statements)} statements")
        LOGGER.info("refresh timings: %s", ", ".join(f"{name}={elapsed:.3f}s" for name, elapsed in timings.items()))

    def _populate_outline(self) -> None:
        selected_names = [self._statement_by_item[item].name for item in self.outline.selection() if item in self._statement_by_item]
        yview = self.outline.yview()
        self.outline.delete(*self.outline.get_children())
        self._statement_by_item.clear()
        for statement in self.parsed.statements:
            if not statement_matches_filter(statement, self.outline_filter.get(), self.outline_kind.get()):
                continue
            item = self.outline.insert(
                "", tk.END,
                text=statement.name,
                values=(statement.kind, statement.line),
            )
            self._statement_by_item[item] = statement
            if statement.name in selected_names:
                self.outline.selection_add(item)
        if yview:
            self.outline.yview_moveto(yview[0])

    def _highlight_source(self) -> None:
        self._highlight_job = None
        started = time.perf_counter()
        first = int(self.editor.index("@0,0").split(".")[0])
        last = int(self.editor.index(f"@0,{max(0, self.editor.winfo_height() - 1)}").split(".")[0])
        bounded = viewport_line_range(first, last, len(self._line_offsets) - 1)
        start, end = offsets_for_lines(self._line_offsets, *bounded)
        parsed = self.parsed if self._parsed_generation == self._guard.generation else None
        spans = highlight_spans(self.document.text, first, last, parsed=parsed,
                                budget=HIGHLIGHT_OPERATION_BUDGET,
                                cached_line_offsets=self._line_offsets,
                                cached_token_starts=self._token_starts if parsed else None)
        for tag in ("definition", "command", "number", "comment"):
            self.editor.tag_remove(tag, self._offset_index(start), self._offset_index(end))
            ranges = [(self._offset_index(span.start), self._offset_index(span.end)) for span in spans if span.tag == tag]
            if ranges:
                flat = [index for pair in ranges for index in pair]
                self.editor.tk.call(self.editor._w, "tag", "add", tag, *flat)
        LOGGER.debug("refresh stage viewport highlighting: %.3fs, %d spans, <=4 add operations",
                     time.perf_counter() - started, len(spans))

    def _schedule_highlight(self) -> None:
        if self._highlight_job is not None:
            self.after_cancel(self._highlight_job)
        self._highlight_job = self.after(40, self._safe_highlight)

    def _safe_highlight(self) -> None:
        try:
            self._highlight_source()
        except Exception:
            self._highlight_job = None
            LOGGER.exception("Deferred syntax highlighting failed")
            messagebox.showerror("Highlighting failed", "Syntax highlighting failed; details were written to the log.")

    def refresh_analysis(self) -> None:
        self._refresh_model()

    def _populate_diagnostics(self, diagnostics) -> None:
        self.diagnostics.delete(*self.diagnostics.get_children())
        self._diagnostic_by_item.clear()
        for diagnostic in diagnostics[:500]:
            item = self.diagnostics.insert(
                "", tk.END,
                text=diagnostic.message,
                values=(diagnostic.severity.value, diagnostic.line),
            )
            self._diagnostic_by_item[item] = diagnostic

    def _outline_selected(self, _event: tk.Event) -> None:
        selected = self.outline.selection()
        if not selected:
            return
        statement = self._statement_by_item[selected[0]]
        self._select_statement(statement)

    def _diagnostic_selected(self, _event: tk.Event) -> None:
        selected = self.diagnostics.selection()
        if not selected:
            return
        diagnostic = self._diagnostic_by_item.get(selected[0])
        if diagnostic is not None:
            start = diagnostic.start if diagnostic.start is not None else self._line_offset(diagnostic.line)
            end = diagnostic.end if diagnostic.end is not None else start
            self._select_range(start, end)

    def _cursor_changed(self, _event: tk.Event) -> None:
        try:
            offset = int(self.editor.count("1.0", tk.INSERT, "chars")[0])
        except (tk.TclError, IndexError):
            return
        statement = self.parsed.statement_at(offset)
        if statement is not None:
            self._show_inspector(statement)

    def _select_statement(self, statement: Statement) -> None:
        start = self._offset_index(statement.start)
        end = self._offset_index(statement.end)
        self.editor.tag_remove("selected_statement", "1.0", tk.END)
        self.editor.tag_add("selected_statement", start, end)
        self.editor.mark_set(tk.INSERT, start)
        self.editor.see(start)
        self._schedule_highlight()
        self._show_inspector(statement)

    def _show_inspector(self, statement: Statement) -> None:
        vertex = self.geometry_model.vertices.get(statement.name or "")
        if vertex is not None:
            self._show_vertex_inspector(vertex)
            return
        lines = [
            f"Name: {statement.name or '(none)'}",
            f"Kind: {statement.kind}",
            f"Line: {statement.line}",
            "",
            "References:",
        ]
        graph = self.reference_graph
        if statement.name == graph.entry_point:
            lines.extend(("", f"Entry point: {graph.entry_point}" + (" (inferred)" if graph.inferred_entry_point else " (explicit)")))
        lines.extend(f"  {name}" for name in statement.references)
        if not statement.references:
            lines.append("  (none resolved)")
        if statement.name:
            users = self.parsed.references_to(statement.name)
            lines.extend(("", "Referenced by:"))
            lines.extend(f"  {item.name or 'statement'} (line {item.line})" for item in users)
            if not users:
                lines.append("  (none)")
        self.inspector.configure(state=tk.NORMAL)
        self.inspector.delete("1.0", tk.END)
        self.inspector.insert("1.0", "\n".join(lines))
        self.inspector.configure(state=tk.DISABLED)

    def _show_vertex_inspector(self, vertex: VertexDefinition) -> None:
        def coordinate(axis: str, value: float, raw: str) -> str:
            formatted = format(value, "g")
            suffix = f" (original: {raw})" if raw != formatted else ""
            return f"{axis}: {formatted}{suffix}"

        users = self.parsed.references_to(vertex.name)
        user_names = [item.name or f"statement on line {item.line}" for item in users]
        coincident = self.geometry_model.coincident_names(vertex)
        lines = [
            f"Name: {vertex.name}", "Kind: Vertex", f"Line: {vertex.statement.line}", "",
            coordinate("X", vertex.x, vertex.raw_x),
            coordinate("Y", vertex.y, vertex.raw_y),
            coordinate("Z", vertex.z, vertex.raw_z),
            f"Distance from origin: {vertex.distance_from_origin:g} source units", "",
            f"Referenced by: {len(users)}",
            *(f"  {name}" for name in user_names),
            "", "Identical coordinates:",
            *(f"  {name}" for name in coincident),
        ]
        if not coincident:
            lines.append("  (none)")
        lines.extend(("", f"Reachable from root: {'Yes' if vertex.name in self.reference_graph.reachable else 'No'}"))
        self.inspector.configure(state=tk.NORMAL)
        self.inspector.delete("1.0", tk.END)
        self.inspector.insert("1.0", "\n".join(lines))
        self.inspector.configure(state=tk.DISABLED)

    def _show_geometry_summary(self) -> None:
        bounds = self.geometry_model.bounds
        if bounds is None:
            text = "No valid vertices found.\n\nBounds are unavailable."
        else:
            cx, cy, cz = bounds.center
            text = (
                f"Vertices: {len(self.geometry_model.vertices)}\n\n"
                f"X: min {bounds.min_x:g}  max {bounds.max_x:g}  size {bounds.size_x:g}\n"
                f"Y: min {bounds.min_y:g}  max {bounds.max_y:g}  size {bounds.size_y:g}\n"
                f"Z: min {bounds.min_z:g}  max {bounds.max_z:g}  size {bounds.size_z:g}\n\n"
                "Bounding-box center (source units):\n"
                f"X {cx:g}\nY {cy:g}\nZ {cz:g}"
            )
        if self.geometry_model.unsupported_constructs:
            text += (
                "\n\nPreserved but not geometrically analyzed: "
                + ", ".join(self.geometry_model.unsupported_constructs)
            )
        self.geometry_summary.configure(text=text)

    def _offset_index(self, offset: int) -> str:
        return f"1.0+{offset}c"

    def _update_title(self) -> None:
        name = self.document.path.name if self.document.path else "Untitled"
        self.title(f"ICR2 3D Editor — {name}{'*' if self.document.dirty else ''}")

    def _confirm_discard(self) -> bool:
        self.document.text = self.editor.get("1.0", "end-1c")
        if not self.document.dirty:
            return True
        choice = messagebox.askyesnocancel("Unsaved changes", "Save changes before continuing?")
        if choice is None:
            return False
        return self.save_file() if choice else True

    def new_file(self) -> None:
        if not self._confirm_discard():
            return
        self.document = SourceDocument("3D VERSION 3.0;\n\n")
        self._set_text(self.document.text)
        self._update_title()

    def open_file(self) -> None:
        if not self._confirm_discard():
            return
        filename = filedialog.askopenfilename(
            title="Open Papyrus .3D file",
            filetypes=(("Papyrus 3D source", "*.3d *.3D"), ("All files", "*.*")),
        )
        if not filename:
            return
        try:
            self.status.configure(text="Loading source…")
            started = time.perf_counter()
            self.document = SourceDocument.load(filename)
            LOGGER.info("open stage file reading and decoding: %.3fs", time.perf_counter() - started)
            self._set_text(self.document.text)
            self._update_title()
        except OSError as error:
            messagebox.showerror("Open failed", str(error))

    def save_file(self) -> bool:
        if self.document.path is None:
            return self.save_file_as()
        self.document.text = self.editor.get("1.0", "end-1c")
        try:
            self.document.save()
            self.status.configure(text=f"Saved {self.document.path}")
            self._update_title()
            return True
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Save failed", str(error))
            return False

    def save_file_as(self) -> bool:
        filename = filedialog.asksaveasfilename(
            title="Save Papyrus .3D file",
            defaultextension=".3D",
            filetypes=(("Papyrus 3D source", "*.3d *.3D"), ("All files", "*.*")),
        )
        if not filename:
            return False
        self.document.text = self.editor.get("1.0", "end-1c")
        try:
            self.document.save(filename)
            self._update_title()
            self.status.configure(text=f"Saved {filename}")
            return True
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Save failed", str(error))
            return False

    def exit_editor(self) -> None:
        if self._confirm_discard():
            self._closing = True
            self._guard.close()
            with self._analysis_condition:
                self._pending_analysis = None
                self._analysis_condition.notify_all()
            self.destroy()

    def _line_offset(self, line: int) -> int:
        lines = self.document.text.splitlines(keepends=True)
        return sum(map(len, lines[:max(0, line - 1)]))

    def _select_range(self, start: int, end: int) -> None:
        first, last = self._offset_index(start), self._offset_index(max(start, end))
        self.editor.tag_remove(tk.SEL, "1.0", tk.END)
        if end > start:
            self.editor.tag_add(tk.SEL, first, last)
        self.editor.mark_set(tk.INSERT, first)
        self.editor.see(first)
        self.editor.focus_set()
        self._schedule_highlight()

    def find_dialog(self) -> None:
        query = simpledialog.askstring("Find", "Text to find:", parent=self)
        if query:
            self._find_query = query
            self.find_next()

    def find_next(self, backwards: bool = False) -> None:
        query = getattr(self, "_find_query", "")
        if not query:
            self.find_dialog()
            return
        start = self.editor.index("insert-1c" if backwards else "insert+1c")
        position = self.editor.search(query, start, stopindex="1.0" if backwards else tk.END, backwards=backwards, nocase=True)
        if not position:
            position = self.editor.search(query, tk.END if backwards else "1.0", stopindex="1.0" if backwards else tk.END, backwards=backwards, nocase=True)
        if position:
            offset = int(self.editor.count("1.0", position, "chars")[0])
            self._select_range(offset, offset + len(query))

    def go_to_line(self) -> None:
        line = simpledialog.askinteger("Go to Line", "Line number:", parent=self, minvalue=1)
        if line is not None:
            self.editor.mark_set(tk.INSERT, f"{line}.0")
            self.editor.see(tk.INSERT)
            self._schedule_highlight()

    def _identifier_at_cursor(self) -> str | None:
        if self.editor.tag_ranges(tk.SEL):
            value = self.editor.get(tk.SEL_FIRST, tk.SEL_LAST)
            return value if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) else None
        return self.editor.get("insert wordstart", "insert wordend") or None

    def go_to_definition(self) -> None:
        statement = self.parsed.definitions.get(self._identifier_at_cursor() or "")
        if statement is not None:
            self._select_range(statement.name_start or statement.start, statement.name_end or statement.end)

    def list_references(self) -> None:
        name = self._identifier_at_cursor()
        tokens = self.parsed.reference_tokens_to(name or "")
        if not tokens:
            messagebox.showinfo("References", f"No references to {name or 'selection'}.")
            return
        choices = "\n".join(f"{index + 1}: line {self.document.text.count(chr(10), 0, token.start) + 1}" for index, token in enumerate(tokens))
        selected = simpledialog.askinteger("References", f"References to {name}:\n{choices}\n\nNavigate to number:", parent=self, minvalue=1, maxvalue=len(tokens))
        if selected:
            token = tokens[selected - 1]
            self._select_range(token.start, token.end)


def main() -> None:
    EditorWindow().mainloop()
