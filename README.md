# ICR2 3D Editor

An early, structure-aware editor for the textual Papyrus `.3D` format used by
IndyCar Racing II tools. The first milestone intentionally behaves like a text
editor with navigation and analysis rather than a general-purpose CAD program.

## Current features

- Byte-preserving UTF-8/UTF-8-BOM/CP1252 loading and atomic saving; edited files
  retain their original newline convention and encoding
- Dirty-state indication and Save/Discard/Cancel protection for New, Open, Exit,
  and window close
- Nesting-aware statement outline with definition names (including generated
  hyphenated names), exact source spans, and conservatively inferred kinds
- Case-insensitive outline name filtering, kind filtering, and scrolling
- Definition/reference navigation
- Typed, read-only vertex parsing with exact coordinate source spans and original
  numeric spelling retained
- Geometry summary with vertex count, axis-aligned bounds, extents, and bounding-box
  center, all explicitly described in **source units**
- Vertex inspector with coordinates, origin distance, references, reachability, and
  coincident-vertex information
- Diagnostics for headers, statement/quote termination, duplicate definitions,
  unknown commands, unresolved references, unreachable definitions, and cycles
- Root-based reference-graph analysis (or an explicitly displayed inferred root)
- Source line numbers and syntax highlighting for definitions, commands, numbers,
  and full-line `%` comments
- Error diagnostics when `%` is used as an inline comment (unsupported by `.3D`)

The parser is deliberately conservative. A tolerant tokenizer retains every
character (including whitespace, comments, and original numeric spelling), and
a concrete syntax layer balances nested `{}`, `()`, `[]`, and `<>` groups. The
original source remains authoritative: statements, tokens, and groups point at
source ranges instead of regenerating the document. Both semicolon and
line-terminated `3D VERSION 3.0` headers are accepted.
Percent comments are recognized only when `%` is the first non-whitespace
character on a line. Command recognition is centralized, but command argument
shapes remain intentionally untyped because the complete Papyrus grammar has
not yet been established. Vertex coordinates support signed integers, decimals,
leading decimals (such as `.5` and `-.5`), and scientific notation for editor
analysis. Scientific notation's acceptance by the Papyrus compiler has not been
verified.

The typed geometry layer understands the Wasp/roadcar-style optional texture
suffix after a vertex position (for example, `, T=<u, v>`), while treating only
the first `<x, y, z>` tuple as position. Attribute-bearing records such as
`[<0,0,0>, c=<248>]` are preserved but are not guessed to be spatial vertices.
Values are not assigned an assumed
physical unit: the interface calls them source units until conversion behavior
is explicitly configured.

## Known limitations

- `FACE`, BSP, polygon, and line geometry are preserved and labeled but are not
  typed or included in geometry calculations yet.
- Coordinate modification and structured geometry editing are not implemented.
- There is no graphical model preview or OpenGL integration.
- Scientific notation is accepted for analysis only; compiler compatibility is
  an open grammar question.
- Optional vertex metadata beyond the observed texture-coordinate suffix remains
  conservatively preserved but untyped.

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

1. Add typed, span-preserving `POLY` parsing that resolves vertex references but
   still leaves source text authoritative.
2. Add polygon-derived calculations only after winding and argument grammar are
   verified against user-authored fixtures.
3. Add safe structured operations such as rename, reverse winding, and translate.
4. Add a selectable 3D preview linked bidirectionally to the source editor.
