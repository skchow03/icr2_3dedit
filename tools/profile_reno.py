"""Profile the lossless parser and inspector projection with the RENO fixture."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from icr2_3dedit.app import EditorWindow
from icr2_3dedit.inspector import ThreeDInspectorModel
from icr2_3dedit.threedfile import ThreeDFile


def main() -> None:
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--tk", action="store_true", help="open RENO in the lazy inspector")
    options = arguments.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    fixture = Path(__file__).parents[1] / "tests" / "fixtures" / "RENO.3D"
    if options.tk:
        window = EditorWindow()
        window.after_idle(lambda: window.load_file(fixture))
        window.mainloop()
        return

    tracemalloc.start()
    started = time.perf_counter()
    document = ThreeDFile.load(fixture)
    parse_time = time.perf_counter() - started
    projection_started = time.perf_counter()
    model = ThreeDInspectorModel(document)
    projection_time = time.perf_counter() - projection_started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    expandable_roots = sum(bool(model.children(node_id)) for node_id in model.root_node_ids)
    print(f"parse={parse_time:.3f}s, inspector_projection={projection_time:.3f}s")
    print(
        f"definitions={len(model.root_node_ids):,}, nodes={len(document.nodes_by_id):,}, "
        f"references={len(document.references):,}, diagnostics={len(document.diagnostics):,}"
    )
    print(
        f"initial_structural_rows={len(model.root_node_ids):,}, "
        f"expansion_placeholders={expandable_roots:,}"
    )
    print(f"tracemalloc_peak={peak / 1024 / 1024:.1f} MiB")


if __name__ == "__main__":
    main()
