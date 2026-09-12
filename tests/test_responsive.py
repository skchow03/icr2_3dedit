from pathlib import Path

from icr2_3dedit.document import SourceDocument
from icr2_3dedit.geometry import build_geometry_model
from icr2_3dedit.parser import parse_document
from icr2_3dedit.responsive import (
    CoalescingRequest,
    GenerationGuard,
    HIGHLIGHT_OPERATION_BUDGET,
    highlight_spans,
)


FIXTURE = Path(__file__).parent / "fixtures" / "RENO.3D"


def test_full_reno_parse_geometry_and_lossless_round_trip(tmp_path: Path) -> None:
    document = SourceDocument.load(FIXTURE)
    parsed = parse_document(document.text)

    assert len(parsed.definitions) == 4413
    assert len(build_geometry_model(parsed).vertices) == 1928
    assert parsed.issues == ()

    destination = tmp_path / "RENO.3D"
    document.save(destination)
    assert destination.read_bytes() == FIXTURE.read_bytes()


def test_viewport_spans_are_bounded_to_range_and_budget() -> None:
    source = "3D VERSION 3.0;\n" + "\n".join(
        f"v{i}: POLY <{i}> {{v0}}; % comment {i}" for i in range(2000)
    )
    spans = highlight_spans(source, 1000, 1020, parsed=parse_document(source), margin=5)
    lines = [source.count("\n", 0, span.start) + 1 for span in spans]
    assert min(lines) >= 995
    assert max(lines) <= 1025
    assert len(spans) <= HIGHLIGHT_OPERATION_BUDGET


def test_small_file_retains_all_useful_highlight_classes() -> None:
    source = "3D VERSION 3.0;\n% note\npoint: [<1, 2, 3>];\nroot: LIST {point};\n"
    spans = highlight_spans(source, 1, 4, parsed=parse_document(source))
    assert {span.tag for span in spans} == {"definition", "command", "comment", "number"}


def test_highlight_fallback_is_bounded_without_completed_parse() -> None:
    source = "3D VERSION 3.0;\n" + "\n".join(f"v{i}: LIST <{i}>;" for i in range(5000))
    spans = highlight_spans(source, 1, 30, budget=75)
    assert len(spans) <= 75
    # Dense numeric highlighting is intentionally the first class shed at budget.
    assert {span.tag for span in spans} >= {"definition", "command"}


def test_scroll_requests_coalesce_to_latest() -> None:
    requests = CoalescingRequest()
    requests.schedule((1, 30))
    requests.schedule((800, 830))
    assert requests.take() == (800, 830)
    assert requests.take() is None


def test_generation_accepts_current_and_rejects_stale_or_closed() -> None:
    guard = GenerationGuard()
    first = guard.invalidate()
    assert guard.accepts(first)
    second = guard.invalidate()
    assert not guard.accepts(first)
    assert guard.accepts(second)
    guard.close()
    assert not guard.accepts(second)


def test_replacing_document_invalidates_pending_result() -> None:
    guard = GenerationGuard()
    pending = guard.invalidate()
    replacement = guard.invalidate()
    assert replacement > pending
    assert not guard.accepts(pending)
