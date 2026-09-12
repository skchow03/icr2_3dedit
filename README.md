# ICR2 3D Editor

An early, structure-aware editor for the textual Papyrus `.3D` format used by
IndyCar Racing II tools. The first milestone intentionally behaves like a text
editor with navigation and analysis rather than a general-purpose CAD program.

## Current features

- Lossless loading and saving of `.3D` source text
- Statement outline with definition names and inferred kinds
- Definition/reference navigation
- Inspector showing a statement's source location and relationships
- Diagnostics for duplicate definitions, unresolved references, and unused items
- Source line numbers and syntax highlighting for definitions, commands, numbers,
  and full-line `%` comments
- Error diagnostics when `%` is used as an inline comment (unsupported by `.3D`)

The parser is deliberately conservative. It keeps the original source as the
authority and records source ranges instead of regenerating the document.

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
python -m unittest discover -s tests -v
```

## Next milestones

1. Resolve polygon vertices and calculate bounds, centers, normals, and winding.
2. Add safe structured operations such as rename, reverse winding, and translate.
3. Add a selectable 3D preview linked bidirectionally to the source editor.
4. Model Papyrus list and BSP nodes explicitly and visualize their traversal.
