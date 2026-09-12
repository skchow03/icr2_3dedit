"""Initial Tk desktop shell for the ICR2 .3D editor."""

from __future__ import annotations

from pathlib import Path
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .analysis import analyze
from .document import SourceDocument
from .parser import ParsedDocument, Statement, parse_document


class EditorWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("ICR2 3D Editor")
        self.geometry("1200x760")
        self.minsize(850, 520)
        self.document = SourceDocument("")
        self.parsed = parse_document("")
        self._refresh_job: str | None = None
        self._statement_by_item: dict[str, Statement] = {}
        self._build_menu()
        self._build_ui()
        self._configure_highlighting()
        self._set_text("3D VERSION 3.0;\n\nnil: NIL;\n")

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Open…", accelerator="Ctrl+O", command=self.open_file)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save_file)
        file_menu.add_command(label="Save As…", accelerator="Ctrl+Shift+S", command=self.save_file_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.destroy)
        menu.add_cascade(label="File", menu=file_menu)

        tools_menu = tk.Menu(menu, tearoff=False)
        tools_menu.add_command(label="Analyze", accelerator="F7", command=self.refresh_analysis)
        menu.add_cascade(label="Tools", menu=tools_menu)
        self.config(menu=menu)
        self.bind_all("<Control-o>", lambda _event: self.open_file())
        self.bind_all("<Control-s>", lambda _event: self.save_file())
        self.bind_all("<Control-Shift-S>", lambda _event: self.save_file_as())
        self.bind_all("<F7>", lambda _event: self.refresh_analysis())

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
        self.outline = ttk.Treeview(left, columns=("kind", "line"), show="tree headings")
        self.outline.heading("#0", text="Name")
        self.outline.heading("kind", text="Kind")
        self.outline.heading("line", text="Line")
        self.outline.column("#0", width=150)
        self.outline.column("kind", width=75, stretch=False)
        self.outline.column("line", width=45, stretch=False)
        self.outline.pack(fill=tk.BOTH, expand=True)
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
        self.editor.bind("<Configure>", self._redraw_line_numbers, add=True)

        notebook = ttk.Notebook(right)
        notebook.pack(fill=tk.BOTH, expand=True)
        inspector_tab = ttk.Frame(notebook, padding=6)
        diagnostics_tab = ttk.Frame(notebook, padding=6)
        notebook.add(inspector_tab, text="Inspector")
        notebook.add(diagnostics_tab, text="Diagnostics")

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

        self.status = ttk.Label(self, text="Ready", anchor=tk.W, relief=tk.SUNKEN)
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

    def _configure_highlighting(self) -> None:
        self.editor.tag_configure("definition", foreground="#005a9c", font=("Consolas", 11, "bold"))
        self.editor.tag_configure("command", foreground="#7a3e9d")
        self.editor.tag_configure("number", foreground="#a04400")
        self.editor.tag_configure("comment", foreground="#238636", font=("Consolas", 11, "italic"))
        self.editor.tag_configure("selected_statement", background="#fff4c2")

    def _set_text(self, text: str) -> None:
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", text)
        self.editor.edit_modified(False)
        self._refresh_model()

    def _text_modified(self, _event: tk.Event) -> None:
        if not self.editor.edit_modified():
            return
        self.editor.edit_modified(False)
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
        self._refresh_job = self.after(250, self._refresh_model)
        self._redraw_line_numbers()

    def _editor_scrolled(
        self,
        scrollbar: ttk.Scrollbar,
        first: str,
        last: str,
    ) -> None:
        scrollbar.set(first, last)
        self._redraw_line_numbers()

    def _redraw_line_numbers(self, _event: tk.Event | None = None) -> None:
        """Draw numbers beside each source line currently visible in the editor."""

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

    def _refresh_model(self) -> None:
        self._refresh_job = None
        text = self.editor.get("1.0", "end-1c")
        self.document.text = text
        self.parsed = parse_document(text)
        self._populate_outline()
        self._highlight_source()
        self.refresh_analysis()
        self.status.configure(text=f"{len(self.parsed.definitions)} definitions, {len(self.parsed.statements)} statements")

    def _populate_outline(self) -> None:
        self.outline.delete(*self.outline.get_children())
        self._statement_by_item.clear()
        for statement in self.parsed.statements:
            if statement.name is None:
                continue
            item = self.outline.insert(
                "", tk.END,
                text=statement.name,
                values=(statement.kind, statement.line),
            )
            self._statement_by_item[item] = statement

    def _highlight_source(self) -> None:
        for tag in ("definition", "command", "number", "comment"):
            self.editor.tag_remove(tag, "1.0", tk.END)
        patterns = {
            "definition": r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:",
            "command": r"\b(?:NIL|POLY|POLYGON|LIST|BSP|DYNAMIC|SUPEROBJ|SWITCH)\b",
            "number": r"(?<![A-Za-z_])[-+]?(?:\d+\.\d*|\.\d+|\d+)(?![A-Za-z_])",
            "comment": r"(?m)^[ \t]*%[^\r\n]*",
        }
        source = self.document.text
        for tag, pattern in patterns.items():
            for match in re.finditer(pattern, source, re.IGNORECASE):
                group = 1 if tag == "definition" else 0
                self.editor.tag_add(tag, self._offset_index(match.start(group)), self._offset_index(match.end(group)))

    def refresh_analysis(self) -> None:
        self.diagnostics.delete(*self.diagnostics.get_children())
        for diagnostic in analyze(self.parsed):
            self.diagnostics.insert(
                "", tk.END,
                text=diagnostic.message,
                values=(diagnostic.severity.value, diagnostic.line),
                tags=(str(diagnostic.line),),
            )

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
        values = self.diagnostics.item(selected[0], "values")
        if values:
            self.editor.mark_set(tk.INSERT, f"{values[1]}.0")
            self.editor.see(tk.INSERT)

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
        self._show_inspector(statement)

    def _show_inspector(self, statement: Statement) -> None:
        lines = [
            f"Name: {statement.name or '(none)'}",
            f"Kind: {statement.kind}",
            f"Line: {statement.line}",
            "",
            "References:",
        ]
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

    def _offset_index(self, offset: int) -> str:
        return f"1.0+{offset}c"

    def open_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="Open Papyrus .3D file",
            filetypes=(("Papyrus 3D source", "*.3d *.3D"), ("All files", "*.*")),
        )
        if not filename:
            return
        try:
            self.document = SourceDocument.load(filename)
            self._set_text(self.document.text)
            self.title(f"ICR2 3D Editor — {Path(filename).name}")
        except OSError as error:
            messagebox.showerror("Open failed", str(error))

    def save_file(self) -> None:
        if self.document.path is None:
            self.save_file_as()
            return
        self.document.text = self.editor.get("1.0", "end-1c")
        try:
            self.document.save()
            self.status.configure(text=f"Saved {self.document.path}")
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Save failed", str(error))

    def save_file_as(self) -> None:
        filename = filedialog.asksaveasfilename(
            title="Save Papyrus .3D file",
            defaultextension=".3D",
            filetypes=(("Papyrus 3D source", "*.3d *.3D"), ("All files", "*.*")),
        )
        if not filename:
            return
        self.document.text = self.editor.get("1.0", "end-1c")
        try:
            self.document.save(filename)
            self.title(f"ICR2 3D Editor — {Path(filename).name}")
            self.status.configure(text=f"Saved {filename}")
        except (OSError, UnicodeError) as error:
            messagebox.showerror("Save failed", str(error))


def main() -> None:
    EditorWindow().mainloop()
