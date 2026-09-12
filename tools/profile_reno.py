"""Headless RENO pipeline benchmark; pass --tk to exercise widgets when displayed."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys
import time
import tracemalloc

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from icr2_3dedit.app import EditorWindow, _analyze_snapshot
from icr2_3dedit.document import SourceDocument
from icr2_3dedit.parser import parse_document
from icr2_3dedit.responsive import highlight_spans


def main() -> None:
    arguments = argparse.ArgumentParser()
    arguments.add_argument("--tk", action="store_true", help="open RENO and log the complete Tk refresh")
    arguments.add_argument("--disable-highlighting", action="store_true", help="isolate the old suspected stage")
    options = arguments.parse_args()
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(message)s")
    fixture = Path(__file__).parents[1] / "tests" / "fixtures" / "RENO.3D"
    if options.tk:
        window = EditorWindow()
        if options.disable_highlighting:
            window._highlight_source = lambda: None
        document = SourceDocument.load(fixture)
        window.document = document
        window._set_text(document.text)
        window._update_title()
        window.mainloop()
        return

    started = time.perf_counter()
    document = SourceDocument.load(fixture)
    read_time = time.perf_counter() - started
    tracemalloc.start()
    parse_started = time.perf_counter()
    parsed = parse_document(document.text)
    parse_time = time.perf_counter() - parse_started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del parsed
    generation, parsed, geometry, _graph, diagnostics, timings = _analyze_snapshot(1, document.text)
    timings["profiled parsing"] = parse_time
    spans = highlight_spans(document.text, 1, 50, parsed=parsed)
    print(f"read/decode={read_time:.3f}s")
    print(", ".join(f"{name}={elapsed:.3f}s" for name, elapsed in timings.items()))
    print(f"definitions={len(parsed.definitions)}, vertices={len(geometry.vertices)}, diagnostics={len(diagnostics)}")
    print(f"initial_highlight_spans={len(spans)}, maximum={1200}, Tk tag_add calls<=4")
    print(f"tracemalloc_peak={peak / 1024 / 1024:.1f} MiB, generation={generation}")


if __name__ == "__main__":
    main()
