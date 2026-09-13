# ICR2 3D Editor

An early, structure-aware editor for the textual Papyrus `.3D` format used by
IndyCar Racing II tools. The current milestone is a read-only document inspector
for the lossless `ThreeDFile` source model rather than a CAD program.

## Current features

- Lossless `ThreeDFile` parsing with stable NodeIDs, source spans, named symbols,
  structural children, references, reverse references, and diagnostics
- Background file loading so parsing a large track does not block Tk's event loop
- A definition/structure explorer that creates only top-level definition rows at
  open time; descendants are requested when their parent is expanded
- Batches of at most 250 rows for unusually wide syntax nodes
- Node properties including kind, command, source span, source location, syntax
  parent, and reference target
- Direct references from a selected node and reverse references to a selected
  definition, without recursively expanding the pointer graph
- Read-only, exact source slices for the selected NodeID; very large spans are
  paged in 100,000-character chunks rather than copied wholesale into a widget
- Parser diagnostics with source context
- No geometry construction, BSP interpretation, rendering, or Papyrus traversal
  during file open

The parser is deliberately conservative. A tolerant tokenizer retains every
character, including whitespace, comments, line endings, and original numeric
spelling. Definitions and nested commands are structural nodes; named references
remain cheap links to NodeIDs. The inspector does not treat successful round-trip
reconstruction as proof that every command's semantics are understood.

## Known limitations

- Modified-document serialization and structured editing are not implemented.
- Command semantics, geometry caches, and Papyrus-compatible traversal are not
  implemented.
- There is no graphical model preview or OpenGL integration.
- Unknown syntax is preserved and may remain structurally unclassified.

Double-click a reference to inspect its resolved definition. Double-click a
reverse-reference row to inspect that reference node. Expand a structure row to
request its direct children; use the explicit **Load next** row when a construct
has more than 250 direct children.

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

### Large-file acceptance test

The checked-in RENO regression fixture exercises the roughly 99,000-node track
case in the automated inspector tests:

```bash
python -m pytest tests/test_inspector.py
```

After the editable install above, run the standard-library tests with:

```bash
python -m pytest
```

## Next milestones

1. Add command-based editing and localized lossless serialization.
2. Add a separate semantic interpretation layer.
3. Add NodeID-addressable geometry caches and a convenient editor viewport.
4. Add Papyrus-compatible traversal, BSP visualization, and draw-order debugging.
