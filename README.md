# ICR2 3D Editor

An early, structure-aware editor for the textual Papyrus `.3D` format used by
IndyCar Racing II tools. The first milestone intentionally behaves like a text
editor with navigation and analysis rather than a general-purpose CAD program.

## Current features

- Byte-preserving UTF-8/UTF-8-BOM/CP1252 loading and atomic saving; edited files
  retain their original newline convention and encoding
- Dirty-state indication and Save/Discard/Cancel protection for New, Open, Exit,
  and window close
- Statement outline with definition names and inferred kinds
- Definition/reference navigation
- Inspector showing a statement's source location and relationships
- Diagnostics for headers, statement/quote termination, duplicate definitions,
  unknown commands, unresolved references, unreachable definitions, and cycles
- Root-based reference-graph analysis (or an explicitly displayed inferred root)
- Source line numbers and syntax highlighting for definitions, commands, numbers,
  and full-line `%` comments
- Error diagnostics when `%` is used as an inline comment (unsupported by `.3D`)

The parser is deliberately conservative. It keeps the original source as the
authority and records source ranges instead of regenerating the document.
Percent comments are recognized only when `%` is the first non-whitespace
character on a line. Command recognition is centralized, but command argument
shapes remain intentionally untyped because the complete Papyrus grammar has
not yet been established.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+N / Ctrl+O | New / Open |
| Ctrl+S / Ctrl+Shift+S | Save / Save As |
| Ctrl+F | Find |
| F3 / Shift+F3 | Find next / previous |
| Ctrl+G | Go to line |
| F12 | Go from the selected/current identifier to its definition |
| Shift+F12 | List and navigate references to the identifier |
| F7 | Re-run analysis |

## Run

Python 3.10 or newer is recommended. The interface uses `tkinter`, included with
normal Windows Python installations.

```bash
python -m pip install -e .
python -m icr2_3dedit
```

From a source checkout without installing:

```bash
python run_editor.py
```

After the editable install above, run the standard-library tests with:

```bash
python -m pytest
```

## Next milestones

1. Add typed vertex and polygon argument parsing on top of the existing exact
   token spans, then calculate bounds, centers, normals, and winding.
2. Add safe structured operations such as rename, reverse winding, and translate.
3. Add a selectable 3D preview linked bidirectionally to the source editor.
4. Model Papyrus list and BSP nodes explicitly and visualize their traversal.
