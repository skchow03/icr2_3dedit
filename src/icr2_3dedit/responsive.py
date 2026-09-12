"""Pure helpers for responsive analysis and viewport syntax highlighting."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from .parser import ParsedDocument
from .syntax import COMMANDS, TokenKind, tokenize


HIGHLIGHT_MARGIN_LINES = 30
HIGHLIGHT_OPERATION_BUDGET = 1200
_TAG_PRIORITY = ("definition", "command", "comment", "number")


@dataclass(frozen=True, slots=True)
class HighlightSpan:
    tag: str
    start: int
    end: int


def viewport_line_range(first: int, last: int, total: int, margin: int = HIGHLIGHT_MARGIN_LINES) -> tuple[int, int]:
    """Return an inclusive, clamped viewport range with surrounding context."""
    if total < 1:
        return (1, 1)
    return max(1, first - margin), min(total, max(first, last) + margin)


def line_offsets(source: str) -> tuple[int, ...]:
    """Return the start offset of every source line, plus an end sentinel."""
    starts = [0]
    position = source.find("\n")
    while position >= 0:
        starts.append(position + 1)
        position = source.find("\n", position + 1)
    starts.append(len(source))
    return tuple(starts)


def offsets_for_lines(offsets: tuple[int, ...], first: int, last: int) -> tuple[int, int]:
    line_count = max(1, len(offsets) - 1)
    first = min(max(1, first), line_count)
    last = min(max(first, last), line_count)
    return offsets[first - 1], offsets[last]


def highlight_spans(
    source: str,
    first_line: int,
    last_line: int,
    *,
    parsed: ParsedDocument | None = None,
    margin: int = HIGHLIGHT_MARGIN_LINES,
    budget: int = HIGHLIGHT_OPERATION_BUDGET,
    cached_line_offsets: tuple[int, ...] | None = None,
    cached_token_starts: tuple[int, ...] | None = None,
) -> tuple[HighlightSpan, ...]:
    """Select only visible syntax spans, with deterministic priority/budgeting."""
    offsets = cached_line_offsets or line_offsets(source)
    first, last = viewport_line_range(first_line, last_line, len(offsets) - 1, margin)
    start, end = offsets_for_lines(offsets, first, last)
    candidates: dict[str, list[HighlightSpan]] = {tag: [] for tag in _TAG_PRIORITY}

    if parsed is not None and parsed.source == source:
        token_starts = cached_token_starts or tuple(token.start for token in parsed.tokens)
        left = max(0, bisect_left(token_starts, start) - 1)
        right = bisect_right(token_starts, end)
        for token in parsed.tokens[left:right]:
            if token.end <= start or token.start >= end:
                continue
            if token.kind is TokenKind.COMMENT:
                tag = "comment"
            elif token.kind is TokenKind.NUMBER:
                tag = "number"
            elif token.kind is TokenKind.IDENTIFIER and token.text.upper() in COMMANDS:
                tag = "command"
            else:
                continue
            candidates[tag].append(HighlightSpan(tag, token.start, token.end))
        for statement in parsed.statements:
            if statement.name_start is not None and start <= statement.name_start < end:
                candidates["definition"].append(
                    HighlightSpan("definition", statement.name_start, statement.name_end or statement.name_start)
                )
    else:
        # Tokenize only the bounded viewport while the matching parse is pending.
        initial_line = source.count("\n", 0, start) + 1
        for token in tokenize(source[start:end], offset=start, line=initial_line):
            if token.kind is TokenKind.COMMENT:
                tag = "comment"
            elif token.kind is TokenKind.NUMBER:
                tag = "number"
            elif token.kind is TokenKind.IDENTIFIER and token.text.upper() in COMMANDS:
                tag = "command"
            else:
                continue
            candidates[tag].append(HighlightSpan(tag, token.start, token.end))
        # Definitions need one bounded regular expression, independent of a parse.
        import re
        pattern = re.compile(r"(?m)^\s*([A-Za-z_][A-Za-z0-9_]*(?:-[A-Za-z0-9_]+)*)\s*:")
        for match in pattern.finditer(source, start, end):
            candidates["definition"].append(HighlightSpan("definition", match.start(1), match.end(1)))

    selected: list[HighlightSpan] = []
    for tag in _TAG_PRIORITY:
        remaining = max(0, budget - len(selected))
        selected.extend(candidates[tag][:remaining])
        if not remaining or len(selected) >= budget:
            break
    return tuple(selected)


class GenerationGuard:
    """Monotonic document identity used to reject stale worker results."""

    def __init__(self) -> None:
        self.generation = 0
        self.closed = False

    def invalidate(self) -> int:
        self.generation += 1
        return self.generation

    def accepts(self, generation: int) -> bool:
        return not self.closed and generation == self.generation

    def close(self) -> None:
        self.closed = True
        self.generation += 1


class CoalescingRequest:
    """Tiny testable latest-request slot; repeated schedules overwrite pending work."""

    def __init__(self) -> None:
        self.pending: object | None = None

    def schedule(self, value: object) -> None:
        self.pending = value

    def take(self) -> object | None:
        value, self.pending = self.pending, None
        return value
