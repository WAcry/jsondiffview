"""Grapheme-safe, display-aware, deterministically bounded string diffs."""

from __future__ import annotations

from collections import Counter, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from enum import StrEnum
from typing import TypeAlias

import regex
from wcwidth import wcswidth

from .model import View

INLINE_TOKEN_UNIT_LIMIT = 2_048
INLINE_TOKEN_CELL_LIMIT = 1_000_000
MICRODIFF_GRAPHEME_LIMIT = 128
MICRODIFF_CELL_LIMIT = 16_384
MICRODIFF_SHARED_AFFIX = 3

BLOB_HARD_CODE_POINT_LIMIT = 512
BLOB_DENSE_CODE_POINT_LIMIT = 160
BLOB_OPAQUE_RUN_LIMIT = 96
BLOB_INTERIOR_CODE_POINT_LIMIT = 2_000_000
BLOB_MATCHER_UNIT_LIMIT = 16_384
BLOB_MATCHER_CELL_LIMIT = 16_000_000
BLOB_OPCODE_LIMIT = 4_096
BLOB_HUNK_LIMIT = 64
BLOB_MERGE_GAP_CELLS = 8

MULTILINE_MATCH_LINE_LIMIT = 50_000
MULTILINE_MATCH_CODE_POINT_LIMIT = 8_000_000
PATIENCE_LINE_VISIT_LIMIT = 2_000_000
SMALL_GAP_LINE_CELL_LIMIT = 4_000_000
SIMILAR_LINE_PAIR_CELL_LIMIT = 100_000
SIMILARITY_MATCHER_CELL_LIMIT = 8_000_000
SIMILARITY_LINE_CODE_POINT_LIMIT = 4_096
SIMILARITY_LINE_UNIT_LIMIT = 512
SIMILARITY_SCORE_THRESHOLD = 400

MULTILINE_DETAIL_ROW_LIMIT = 20_000
STRING_DETAIL_DISPLAY_CELL_LIMIT = 2_000_000

SUMMARY_CONTEXT_LINES = 1
REVIEW_CONTEXT_LINES = 2
SUMMARY_EXCERPT_CELLS = 48
REVIEW_EXCERPT_CELLS = 96
FULL_EXCERPT_CELLS = 160

_GRAPHEME_RE = regex.compile(r"\X")
_LINE_RE = regex.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$")
_IDENT_START_RE = regex.compile(r"\A\p{L}[\p{L}\p{M}\p{Nd}]*\Z")
_IDENT_CONTINUE_RE = regex.compile(r"\A[\p{L}\p{M}\p{Nd}]+\Z")
_NUMBER_RE = regex.compile(r"\A\p{Nd}+\Z")
_SPACE_RE = regex.compile(r"\A[^\S\r\n]+\Z")
_PUNCT_RE = regex.compile(r"\A[-./:_=+?&@#%|\\]+\Z")
_BLOB_SEPARATORS = frozenset("-./:_=+?&@#%|\\")


@dataclass(frozen=True, slots=True)
class StringBudgets:
    """All deterministic admission and materialization limits."""

    inline_units: int = INLINE_TOKEN_UNIT_LIMIT
    inline_cells: int = INLINE_TOKEN_CELL_LIMIT
    micro_graphemes: int = MICRODIFF_GRAPHEME_LIMIT
    micro_cells: int = MICRODIFF_CELL_LIMIT
    multiline_lines: int = MULTILINE_MATCH_LINE_LIMIT
    multiline_code_points: int = MULTILINE_MATCH_CODE_POINT_LIMIT
    patience_line_visits: int = PATIENCE_LINE_VISIT_LIMIT
    small_gap_line_cells: int = SMALL_GAP_LINE_CELL_LIMIT
    similar_line_pair_cells: int = SIMILAR_LINE_PAIR_CELL_LIMIT
    similarity_matcher_cells: int = SIMILARITY_MATCHER_CELL_LIMIT
    blob_interior_code_points: int = BLOB_INTERIOR_CODE_POINT_LIMIT
    blob_units: int = BLOB_MATCHER_UNIT_LIMIT
    blob_cells: int = BLOB_MATCHER_CELL_LIMIT
    blob_opcodes: int = BLOB_OPCODE_LIMIT
    blob_hunks: int = BLOB_HUNK_LIMIT
    detail_rows: int = MULTILINE_DETAIL_ROW_LIMIT
    detail_display_cells: int = STRING_DETAIL_DISPLAY_CELL_LIMIT


DEFAULT_STRING_BUDGETS = StringBudgets()


class StringMode(StrEnum):
    """View-neutral string analysis strategy."""

    INLINE = "inline"
    MULTILINE = "multiline"
    BLOB = "blob"


class FragmentKind(StrEnum):
    """Semantic role of raw text inside an annotated string."""

    UNCHANGED = "unchanged"
    REMOVED = "removed"
    ADDED = "added"


class TokenKind(StrEnum):
    """Unicode-aware token classes used by inline and similarity matching."""

    IDENT = "ident"
    NUMBER = "number"
    SPACE = "space"
    PUNCT = "punct"
    OTHER = "other"


class FallbackReason(StrEnum):
    """Typed reason why a more detailed deterministic path was declined."""

    INLINE_UNITS = "inline_units"
    INLINE_CELLS = "inline_cells"
    MULTILINE_LINES = "multiline_lines"
    MULTILINE_CODE_POINTS = "multiline_code_points"
    PATIENCE_WORK = "patience_work"
    SMALL_GAP_CELLS = "small_gap_cells"
    PAIRING_CELLS = "pairing_cells"
    SIMILARITY_CELLS = "similarity_cells"
    BLOB_CODE_POINTS = "blob_code_points"
    BLOB_UNITS = "blob_units"
    BLOB_CELLS = "blob_cells"
    BLOB_OPCODES = "blob_opcodes"
    BLOB_HUNKS = "blob_hunks"
    DETAIL_ROWS = "detail_rows"
    DETAIL_CELLS = "detail_cells"


class LineKind(StrEnum):
    """Semantic role of one projected multiline detail row."""

    UNCHANGED = "unchanged"
    REMOVED = "removed"
    ADDED = "added"
    OMITTED = "omitted"
    REMOVED_OMITTED = "removed_omitted"
    ADDED_OMITTED = "added_omitted"


@dataclass(frozen=True, slots=True)
class Grapheme:
    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class StringToken:
    kind: TokenKind
    text: str
    start: int
    end: int

    @property
    def signature(self) -> tuple[TokenKind, str]:
        return (self.kind, self.text)


@dataclass(frozen=True, slots=True)
class TextFragment:
    """One raw semantic span with exact source-side code-point ranges."""

    text: str
    kind: FragmentKind
    old_start: int | None = None
    old_end: int | None = None
    new_start: int | None = None
    new_end: int | None = None


@dataclass(frozen=True, slots=True)
class StringWorkCounters:
    """Portable work observations; elapsed time never affects these values."""

    patience_line_visits: int = 0
    small_gap_line_cells: int = 0
    similar_line_pair_cells: int = 0
    similarity_matcher_cells: int = 0
    blob_units: int = 0
    blob_matcher_cells: int = 0
    blob_opcodes: int = 0


@dataclass(frozen=True, slots=True)
class ShortStringDiff:
    fragments: tuple[TextFragment, ...]
    fallback_reason: FallbackReason | None = None


@dataclass(frozen=True, slots=True)
class LogicalLine:
    body: str
    terminator: str
    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class LineRow:
    kind: LineKind
    text: str = ""
    count: int = 0
    fragments: tuple[TextFragment, ...] = ()
    old_line: int | None = None
    new_line: int | None = None
    omitted_code_points: int = 0


@dataclass(frozen=True, slots=True)
class MultilineStringDiff:
    old_line_count: int
    new_line_count: int
    old_code_point_count: int
    new_code_point_count: int
    rows: tuple[LineRow, ...]
    old_lines: tuple[LogicalLine, ...] | None
    new_lines: tuple[LogicalLine, ...] | None
    old_preview: tuple[LogicalLine, ...] = ()
    new_preview: tuple[LogicalLine, ...] = ()
    fallback_reason: FallbackReason | None = None
    work: StringWorkCounters = StringWorkCounters()


@dataclass(frozen=True, slots=True)
class Excerpt:
    text: str
    omitted: int
    source_start: int = 0
    source_end: int = 0


@dataclass(frozen=True, slots=True)
class LongStringHunk:
    old_start: int
    old_end: int
    new_start: int
    new_end: int


@dataclass(frozen=True, slots=True)
class LongStringDiff:
    old_text: str
    new_text: str
    old_length: int
    new_length: int
    omitted_before: int
    omitted_after: int
    hunks: tuple[LongStringHunk, ...]
    fallback_reason: FallbackReason | None = None
    work: StringWorkCounters = StringWorkCounters()


@dataclass(frozen=True, slots=True)
class ProjectedLongStringHunk:
    old_start: int
    old_end: int
    new_start: int
    new_end: int
    old_excerpt: Excerpt
    new_excerpt: Excerpt


@dataclass(frozen=True, slots=True)
class ProjectedLongStringDiff:
    old_length: int
    new_length: int
    omitted_before: int
    omitted_after: int
    hunks: tuple[ProjectedLongStringHunk, ...]
    fallback_reason: FallbackReason | None
    work: StringWorkCounters


StringDiff: TypeAlias = ShortStringDiff | MultilineStringDiff | LongStringDiff
ProjectedStringDiff: TypeAlias = (
    ShortStringDiff | MultilineStringDiff | ProjectedLongStringDiff
)
Opcode: TypeAlias = tuple[str, int, int, int, int]
EscapeForWidth: TypeAlias = Callable[[str], str]


@dataclass(slots=True)
class _WorkLedger:
    patience_line_visits: int = 0
    small_gap_line_cells: int = 0
    similar_line_pair_cells: int = 0
    similarity_matcher_cells: int = 0

    def frozen(self, **changes: int) -> StringWorkCounters:
        values = {
            "patience_line_visits": self.patience_line_visits,
            "small_gap_line_cells": self.small_gap_line_cells,
            "similar_line_pair_cells": self.similar_line_pair_cells,
            "similarity_matcher_cells": self.similarity_matcher_cells,
            "blob_units": 0,
            "blob_matcher_cells": 0,
            "blob_opcodes": 0,
        }
        values.update(changes)
        return StringWorkCounters(**values)


@dataclass(frozen=True, slots=True)
class _LineScan:
    count: int
    code_point_count: int
    lines: tuple[LogicalLine, ...] | None
    preview: tuple[LogicalLine, ...]


@dataclass(frozen=True, slots=True)
class _RangeTask:
    old_start: int
    old_end: int
    new_start: int
    new_end: int


@dataclass(frozen=True, slots=True)
class _EmitTask:
    opcode: Opcode


@dataclass(frozen=True, slots=True)
class _Unit:
    signature: object
    start: int
    end: int


def split_graphemes(text: str) -> tuple[Grapheme, ...]:
    """Segment exact UAX #29 extended graphemes without normalization."""

    return tuple(
        Grapheme(match.group(), match.start(), match.end())
        for match in _GRAPHEME_RE.finditer(text)
    )


def tokenize_string(text: str) -> tuple[StringToken, ...]:
    """Tokenize a string without gaps and without splitting graphemes."""

    tokens = _tokenize_string_limited(text, None)
    assert tokens is not None
    return tokens


def _tokenize_string_limited(
    text: str,
    limit: int | None,
) -> tuple[StringToken, ...] | None:
    tokens: list[StringToken] = []
    current_kind: TokenKind | None = None
    continuation: Callable[[str], bool] = _never_continue
    token_start = 0
    token_end = 0
    for match in _GRAPHEME_RE.finditer(text):
        grapheme = match.group()
        if current_kind is not None and continuation(grapheme):
            token_end = match.end()
            continue
        if current_kind is not None:
            tokens.append(
                StringToken(
                    current_kind,
                    text[token_start:token_end],
                    token_start,
                    token_end,
                )
            )
            if limit is not None and len(tokens) > limit:
                return None
        current_kind, continuation = _token_class(grapheme)
        token_start = match.start()
        token_end = match.end()
    if current_kind is not None:
        tokens.append(
            StringToken(
                current_kind,
                text[token_start:token_end],
                token_start,
                token_end,
            )
        )
    if limit is not None and len(tokens) > limit:
        return None
    return tuple(tokens)


def _token_class(text: str) -> tuple[TokenKind, Callable[[str], bool]]:
    if _IDENT_START_RE.fullmatch(text):
        return TokenKind.IDENT, _is_identifier_continuation
    if _NUMBER_RE.fullmatch(text):
        return TokenKind.NUMBER, _is_number_grapheme
    if _SPACE_RE.fullmatch(text):
        return TokenKind.SPACE, _is_space_grapheme
    if _PUNCT_RE.fullmatch(text):
        return TokenKind.PUNCT, _is_punctuation_grapheme
    return TokenKind.OTHER, _never_continue


def _is_identifier_continuation(text: str) -> bool:
    return _IDENT_CONTINUE_RE.fullmatch(text) is not None


def _is_number_grapheme(text: str) -> bool:
    return _NUMBER_RE.fullmatch(text) is not None


def _is_space_grapheme(text: str) -> bool:
    return _SPACE_RE.fullmatch(text) is not None


def _is_punctuation_grapheme(text: str) -> bool:
    return _PUNCT_RE.fullmatch(text) is not None


def _never_continue(_text: str) -> bool:
    return False


def classify_string_mode(old: str, new: str) -> StringMode:
    """Classify symmetrically using exact multiline and adaptive blob rules."""

    if "\r" in old or "\n" in old or "\r" in new or "\n" in new:
        return StringMode.MULTILINE
    if _is_blob_candidate(old) or _is_blob_candidate(new):
        return StringMode.BLOB
    return StringMode.INLINE


def build_string_diff(
    old: str,
    new: str,
    *,
    budgets: StringBudgets = DEFAULT_STRING_BUDGETS,
) -> StringDiff:
    """Build one view-neutral string analysis."""

    mode = classify_string_mode(old, new)
    if mode is StringMode.MULTILINE:
        return _build_multiline_diff(old, new, budgets)
    if mode is StringMode.BLOB:
        return _build_long_diff(old, new, budgets)
    short, fallback = _build_short_diff(old, new, budgets)
    if short is not None:
        return short
    result = _build_long_diff(old, new, budgets)
    return replace(result, fallback_reason=fallback)


def project_string_diff(
    analysis: StringDiff,
    view: View,
    escape_for_width: EscapeForWidth,
    *,
    budgets: StringBudgets = DEFAULT_STRING_BUDGETS,
) -> ProjectedStringDiff:
    """Apply only view context and escaped display-width choices."""

    if isinstance(analysis, ShortStringDiff):
        return analysis
    if isinstance(analysis, MultilineStringDiff):
        return _project_multiline(
            analysis,
            view,
            escape_for_width,
            budgets,
        )
    return _project_long(analysis, view, escape_for_width)


def excerpt_cells_for_view(view: View) -> int:
    return {
        View.SUMMARY: SUMMARY_EXCERPT_CELLS,
        View.REVIEW: REVIEW_EXCERPT_CELLS,
        View.FULL: FULL_EXCERPT_CELLS,
    }[view]


def display_width(text: str) -> int:
    """Measure deterministic cells with ambiguous width fixed to one."""

    width = wcswidth(text, ambiguous_width=1)
    return width if width >= 0 else len(split_graphemes(text))


def bounded_excerpt(
    text: str,
    max_cells: int = REVIEW_EXCERPT_CELLS,
    escape_for_width: EscapeForWidth | None = None,
) -> Excerpt:
    """Clip escaped display cells without splitting an extended grapheme."""

    escaper = escape_for_width or _identity_text
    if _fits_display_cells(text, max_cells, escaper):
        return Excerpt(text, 0, 0, len(text))
    if not text:
        return Excerpt("", 0, 0, 0)
    if max_cells <= 1:
        return Excerpt("…", len(text), 0, len(text))

    inner = max_cells - display_width("…")
    left_budget = inner // 2
    right_budget = inner - left_budget
    left = _take_text_left(text, 0, len(text), left_budget, escaper)
    right = _take_text_right(text, 0, len(text), right_budget, escaper)
    while left and right and left[-1].end > right[0].start:
        right = right[1:]
    rendered = (
        "".join(item.text for item in left) + "…" + "".join(item.text for item in right)
    )
    while display_width(escaper(rendered)) > max_cells and (left or right):
        if _grapheme_text_width(left, escaper) >= _grapheme_text_width(
            right,
            escaper,
        ):
            left = left[:-1]
        else:
            right = right[1:]
        rendered = (
            "".join(item.text for item in left)
            + "…"
            + "".join(item.text for item in right)
        )
    shown = "".join(item.text for item in left) + "".join(item.text for item in right)
    return Excerpt(rendered, len(text) - len(shown), 0, len(text))


def _build_short_diff(
    old: str,
    new: str,
    budgets: StringBudgets,
) -> tuple[ShortStringDiff | None, FallbackReason | None]:
    old_tokens = tokenize_string(old)
    new_tokens = tokenize_string(new)
    unit_count = len(old_tokens) + len(new_tokens)
    if unit_count > budgets.inline_units:
        return None, FallbackReason.INLINE_UNITS
    if len(old_tokens) * len(new_tokens) > budgets.inline_cells:
        return None, FallbackReason.INLINE_CELLS
    return ShortStringDiff(_build_fragments(old, new, budgets)), None


def _build_fragments(
    old: str,
    new: str,
    budgets: StringBudgets,
) -> tuple[TextFragment, ...]:
    old_tokens = tokenize_string(old)
    new_tokens = tokenize_string(new)
    old_signatures = [token.signature for token in old_tokens]
    new_signatures = [token.signature for token in new_tokens]
    opcodes = SequenceMatcher(
        None,
        old_signatures,
        new_signatures,
        autojunk=False,
    ).get_opcodes()
    changed = [opcode for opcode in opcodes if opcode[0] != "equal"]
    micro_opcode = changed[0] if len(changed) == 1 else None
    fragments: list[TextFragment] = []

    for opcode in opcodes:
        tag, old_start, old_end, new_start, new_end = opcode
        old_range = _token_range(old_tokens, old_start, old_end, len(old))
        new_range = _token_range(new_tokens, new_start, new_end, len(new))
        old_text = old[old_range[0] : old_range[1]]
        new_text = new[new_range[0] : new_range[1]]
        if tag == "equal":
            fragments.append(
                TextFragment(
                    old_text,
                    FragmentKind.UNCHANGED,
                    *old_range,
                    *new_range,
                )
            )
        elif (
            opcode == micro_opcode
            and tag == "replace"
            and old_end - old_start == 1
            and new_end - new_start == 1
            and _can_microdiff(
                old_tokens[old_start],
                new_tokens[new_start],
                budgets,
            )
        ):
            fragments.extend(
                _microdiff_fragments(
                    old_tokens[old_start],
                    new_tokens[new_start],
                )
            )
        else:
            if old_text:
                fragments.append(
                    TextFragment(
                        old_text,
                        FragmentKind.REMOVED,
                        old_range[0],
                        old_range[1],
                    )
                )
            if new_text:
                fragments.append(
                    TextFragment(
                        new_text,
                        FragmentKind.ADDED,
                        None,
                        None,
                        new_range[0],
                        new_range[1],
                    )
                )
    return tuple(_merge_fragments(fragments))


def _token_range(
    tokens: Sequence[StringToken],
    start: int,
    end: int,
    text_length: int,
) -> tuple[int, int]:
    range_start = tokens[start].start if start < len(tokens) else text_length
    range_end = tokens[end - 1].end if end > start else range_start
    return range_start, range_end


def _can_microdiff(
    old: StringToken,
    new: StringToken,
    budgets: StringBudgets,
) -> bool:
    if old.kind is not new.kind or old.kind not in {TokenKind.IDENT, TokenKind.NUMBER}:
        return False
    old_graphemes = split_graphemes(old.text)
    new_graphemes = split_graphemes(new.text)
    if (
        len(old_graphemes) > budgets.micro_graphemes
        or len(new_graphemes) > budgets.micro_graphemes
        or len(old_graphemes) * len(new_graphemes) > budgets.micro_cells
    ):
        return False
    return (
        _shared_grapheme_affix(old_graphemes, new_graphemes) >= MICRODIFF_SHARED_AFFIX
    )


def _microdiff_fragments(
    old_token: StringToken,
    new_token: StringToken,
) -> list[TextFragment]:
    old_graphemes = split_graphemes(old_token.text)
    new_graphemes = split_graphemes(new_token.text)
    matcher = SequenceMatcher(
        None,
        [item.text for item in old_graphemes],
        [item.text for item in new_graphemes],
        autojunk=False,
    )
    result: list[TextFragment] = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        old_range = _grapheme_range(
            old_graphemes,
            old_start,
            old_end,
            len(old_token.text),
        )
        new_range = _grapheme_range(
            new_graphemes,
            new_start,
            new_end,
            len(new_token.text),
        )
        old_absolute = (
            old_token.start + old_range[0],
            old_token.start + old_range[1],
        )
        new_absolute = (
            new_token.start + new_range[0],
            new_token.start + new_range[1],
        )
        if tag == "equal":
            result.append(
                TextFragment(
                    old_token.text[old_range[0] : old_range[1]],
                    FragmentKind.UNCHANGED,
                    *old_absolute,
                    *new_absolute,
                )
            )
        else:
            if old_range[0] != old_range[1]:
                result.append(
                    TextFragment(
                        old_token.text[old_range[0] : old_range[1]],
                        FragmentKind.REMOVED,
                        *old_absolute,
                    )
                )
            if new_range[0] != new_range[1]:
                result.append(
                    TextFragment(
                        new_token.text[new_range[0] : new_range[1]],
                        FragmentKind.ADDED,
                        None,
                        None,
                        *new_absolute,
                    )
                )
    return result


def _grapheme_range(
    graphemes: Sequence[Grapheme],
    start: int,
    end: int,
    text_length: int,
) -> tuple[int, int]:
    range_start = graphemes[start].start if start < len(graphemes) else text_length
    range_end = graphemes[end - 1].end if end > start else range_start
    return range_start, range_end


def _shared_grapheme_affix(
    old: Sequence[Grapheme],
    new: Sequence[Grapheme],
) -> int:
    prefix = 0
    while (
        prefix < len(old) and prefix < len(new) and old[prefix].text == new[prefix].text
    ):
        prefix += 1
    suffix = 0
    while (
        suffix < len(old) - prefix
        and suffix < len(new) - prefix
        and old[-1 - suffix].text == new[-1 - suffix].text
    ):
        suffix += 1
    return prefix + suffix


def _merge_fragments(fragments: Sequence[TextFragment]) -> list[TextFragment]:
    result: list[TextFragment] = []
    for fragment in fragments:
        if not fragment.text:
            continue
        if result and result[-1].kind is fragment.kind:
            previous = result[-1]
            result[-1] = TextFragment(
                previous.text + fragment.text,
                fragment.kind,
                previous.old_start,
                fragment.old_end if fragment.old_end is not None else previous.old_end,
                previous.new_start,
                fragment.new_end if fragment.new_end is not None else previous.new_end,
            )
        else:
            result.append(fragment)
    return result


def _build_multiline_diff(
    old: str,
    new: str,
    budgets: StringBudgets,
) -> MultilineStringDiff:
    can_store = len(old) + len(new) <= budgets.multiline_code_points
    old_scan = _scan_lines(old, can_store, budgets.multiline_lines)
    new_scan = _scan_lines(new, can_store, budgets.multiline_lines)
    combined_lines = old_scan.count + new_scan.count
    if not can_store:
        return _coarse_multiline(
            old_scan,
            new_scan,
            FallbackReason.MULTILINE_CODE_POINTS,
        )
    if (
        combined_lines > budgets.multiline_lines
        or old_scan.lines is None
        or new_scan.lines is None
    ):
        return _coarse_multiline(
            old_scan,
            new_scan,
            FallbackReason.MULTILINE_LINES,
        )

    old_lines = old_scan.lines
    new_lines = new_scan.lines
    ledger = _WorkLedger()
    opcodes, fallback = _patience_opcodes(
        old_lines,
        new_lines,
        ledger,
        budgets,
    )
    rows: list[LineRow] = []
    for tag, old_start, old_end, new_start, new_end in opcodes:
        if tag == "equal":
            rows.extend(
                LineRow(
                    LineKind.UNCHANGED,
                    line.text,
                    old_line=old_start + offset,
                    new_line=new_start + offset,
                )
                for offset, line in enumerate(old_lines[old_start:old_end])
            )
        elif tag == "delete":
            rows.extend(
                LineRow(
                    LineKind.REMOVED,
                    line.text,
                    old_line=old_start + offset,
                )
                for offset, line in enumerate(old_lines[old_start:old_end])
            )
        elif tag == "insert":
            rows.extend(
                LineRow(
                    LineKind.ADDED,
                    line.text,
                    new_line=new_start + offset,
                )
                for offset, line in enumerate(new_lines[new_start:new_end])
            )
        else:
            paired, pair_fallback = _pair_replacement_lines(
                old_lines[old_start:old_end],
                new_lines[new_start:new_end],
                ledger,
                budgets,
            )
            fallback = fallback or pair_fallback
            rows.extend(
                _replacement_rows(
                    old_lines,
                    new_lines,
                    old_start,
                    old_end,
                    new_start,
                    new_end,
                    paired,
                    budgets,
                )
            )
    return MultilineStringDiff(
        len(old_lines),
        len(new_lines),
        len(old),
        len(new),
        tuple(rows),
        old_lines,
        new_lines,
        fallback_reason=fallback,
        work=ledger.frozen(),
    )


def _scan_lines(text: str, store: bool, line_limit: int) -> _LineScan:
    lines: list[LogicalLine] | None = [] if store else None
    head: list[LogicalLine] = []
    tail: list[LogicalLine] = []
    count = 0
    for match in _LINE_RE.finditer(text):
        raw = match.group()
        if raw.endswith("\r\n"):
            terminator = "\r\n"
        elif raw.endswith("\r"):
            terminator = "\r"
        elif raw.endswith("\n"):
            terminator = "\n"
        else:
            terminator = ""
        line = LogicalLine(
            raw[: len(raw) - len(terminator)] if terminator else raw,
            terminator,
            raw,
            match.start(),
            match.end(),
        )
        count += 1
        if len(head) < 2:
            head.append(line)
        tail.append(line)
        if len(tail) > 2:
            tail.pop(0)
        if lines is not None:
            if len(lines) < line_limit:
                lines.append(line)
            else:
                lines = None
    if count <= 2:
        preview = tuple(head)
    elif count == 3:
        preview = (*head, tail[-1])
    else:
        preview = (*head, *tail)
    return _LineScan(
        count,
        len(text),
        None if lines is None else tuple(lines),
        preview,
    )


def _coarse_multiline(
    old_scan: _LineScan,
    new_scan: _LineScan,
    reason: FallbackReason,
) -> MultilineStringDiff:
    return MultilineStringDiff(
        old_scan.count,
        new_scan.count,
        old_scan.code_point_count,
        new_scan.code_point_count,
        (),
        None,
        None,
        old_scan.preview,
        new_scan.preview,
        reason,
    )


def _patience_opcodes(
    old: Sequence[LogicalLine],
    new: Sequence[LogicalLine],
    ledger: _WorkLedger,
    budgets: StringBudgets,
) -> tuple[list[Opcode], FallbackReason | None]:
    tasks: list[_RangeTask | _EmitTask] = [_RangeTask(0, len(old), 0, len(new))]
    result: list[Opcode] = []
    fallback: FallbackReason | None = None

    while tasks:
        task = tasks.pop()
        if isinstance(task, _EmitTask):
            result.append(task.opcode)
            continue
        old_start, old_end = task.old_start, task.old_end
        new_start, new_end = task.new_start, task.new_end
        if old_start == old_end:
            if new_start != new_end:
                result.append(("insert", old_start, old_end, new_start, new_end))
            continue
        if new_start == new_end:
            result.append(("delete", old_start, old_end, new_start, new_end))
            continue

        prefix = 0
        while (
            old_start + prefix < old_end
            and new_start + prefix < new_end
            and old[old_start + prefix].text == new[new_start + prefix].text
        ):
            prefix += 1
        suffix = 0
        while (
            old_start + prefix < old_end - suffix
            and new_start + prefix < new_end - suffix
            and old[old_end - 1 - suffix].text == new[new_end - 1 - suffix].text
        ):
            suffix += 1

        middle_old_start = old_start + prefix
        middle_old_end = old_end - suffix
        middle_new_start = new_start + prefix
        middle_new_end = new_end - suffix
        pieces: list[_RangeTask | _EmitTask] = []
        if prefix:
            pieces.append(
                _EmitTask(
                    (
                        "equal",
                        old_start,
                        middle_old_start,
                        new_start,
                        middle_new_start,
                    )
                )
            )

        if middle_old_start != middle_old_end or middle_new_start != middle_new_end:
            visit_cost = (
                middle_old_end - middle_old_start + middle_new_end - middle_new_start
            )
            if ledger.patience_line_visits + visit_cost > budgets.patience_line_visits:
                fallback = fallback or FallbackReason.PATIENCE_WORK
                pieces.append(
                    _EmitTask(
                        (
                            "replace",
                            middle_old_start,
                            middle_old_end,
                            middle_new_start,
                            middle_new_end,
                        )
                    )
                )
            else:
                ledger.patience_line_visits += visit_cost
                anchors = _unique_line_anchors(
                    old,
                    new,
                    middle_old_start,
                    middle_old_end,
                    middle_new_start,
                    middle_new_end,
                )
                if anchors:
                    previous_old = middle_old_start
                    previous_new = middle_new_start
                    for old_anchor, new_anchor in anchors:
                        pieces.append(
                            _RangeTask(
                                previous_old,
                                old_anchor,
                                previous_new,
                                new_anchor,
                            )
                        )
                        pieces.append(
                            _EmitTask(
                                (
                                    "equal",
                                    old_anchor,
                                    old_anchor + 1,
                                    new_anchor,
                                    new_anchor + 1,
                                )
                            )
                        )
                        previous_old = old_anchor + 1
                        previous_new = new_anchor + 1
                    pieces.append(
                        _RangeTask(
                            previous_old,
                            middle_old_end,
                            previous_new,
                            middle_new_end,
                        )
                    )
                else:
                    old_size = middle_old_end - middle_old_start
                    new_size = middle_new_end - middle_new_start
                    cells = old_size * new_size
                    if (
                        ledger.small_gap_line_cells + cells
                        <= budgets.small_gap_line_cells
                    ):
                        ledger.small_gap_line_cells += cells
                        matcher = SequenceMatcher(
                            None,
                            [
                                line.text
                                for line in old[middle_old_start:middle_old_end]
                            ],
                            [
                                line.text
                                for line in new[middle_new_start:middle_new_end]
                            ],
                            autojunk=False,
                        )
                        for opcode in matcher.get_opcodes():
                            tag, a, b, c, d = opcode
                            pieces.append(
                                _EmitTask(
                                    (
                                        tag,
                                        middle_old_start + a,
                                        middle_old_start + b,
                                        middle_new_start + c,
                                        middle_new_start + d,
                                    )
                                )
                            )
                    else:
                        fallback = fallback or FallbackReason.SMALL_GAP_CELLS
                        pieces.append(
                            _EmitTask(
                                (
                                    "replace",
                                    middle_old_start,
                                    middle_old_end,
                                    middle_new_start,
                                    middle_new_end,
                                )
                            )
                        )

        if suffix:
            pieces.append(
                _EmitTask(
                    (
                        "equal",
                        middle_old_end,
                        old_end,
                        middle_new_end,
                        new_end,
                    )
                )
            )
        tasks.extend(reversed(pieces))
    return _coalesce_opcodes(result), fallback


def _unique_line_anchors(
    old: Sequence[LogicalLine],
    new: Sequence[LogicalLine],
    old_start: int,
    old_end: int,
    new_start: int,
    new_end: int,
) -> tuple[tuple[int, int], ...]:
    old_counts = Counter(line.text for line in old[old_start:old_end])
    new_counts = Counter(line.text for line in new[new_start:new_end])
    old_positions = {
        old[index].text: index
        for index in range(old_start, old_end)
        if old_counts[old[index].text] == 1
    }
    candidates = [
        (old_positions[new[index].text], index)
        for index in range(new_start, new_end)
        if new_counts[new[index].text] == 1 and old_counts.get(new[index].text) == 1
    ]
    if not candidates:
        return ()

    old_values = sorted({old_index for old_index, _ in candidates})
    rank_by_old = {value: rank + 1 for rank, value in enumerate(old_values)}
    tree = [0] * (len(old_values) + 1)
    lis_from = [0] * len(candidates)
    for index in range(len(candidates) - 1, -1, -1):
        rank = len(old_values) - rank_by_old[candidates[index][0]] + 1
        lis_from[index] = 1 + _list_fenwick_query(tree, rank - 1)
        _list_fenwick_update(tree, rank, lis_from[index])
    remaining = max(lis_from)
    last_old = -1
    selected: list[tuple[int, int]] = []
    for index, candidate in enumerate(candidates):
        if candidate[0] <= last_old or lis_from[index] < remaining:
            continue
        selected.append(candidate)
        last_old = candidate[0]
        remaining -= 1
        if remaining == 0:
            break
    return tuple(selected)


def _list_fenwick_query(tree: list[int], index: int) -> int:
    result = 0
    while index > 0:
        result = max(result, tree[index])
        index -= index & -index
    return result


def _list_fenwick_update(tree: list[int], index: int, value: int) -> None:
    while index < len(tree):
        tree[index] = max(tree[index], value)
        index += index & -index


def _coalesce_opcodes(opcodes: Sequence[Opcode]) -> list[Opcode]:
    result: list[Opcode] = []
    for opcode in opcodes:
        if (
            result
            and result[-1][0] == opcode[0]
            and result[-1][2] == opcode[1]
            and result[-1][4] == opcode[3]
        ):
            previous = result[-1]
            result[-1] = (
                previous[0],
                previous[1],
                opcode[2],
                previous[3],
                opcode[4],
            )
        elif opcode[1] != opcode[2] or opcode[3] != opcode[4]:
            result.append(opcode)
    return result


def _pair_replacement_lines(
    old: Sequence[LogicalLine],
    new: Sequence[LogicalLine],
    ledger: _WorkLedger,
    budgets: StringBudgets,
) -> tuple[tuple[tuple[int, int], ...], FallbackReason | None]:
    cells = len(old) * len(new)
    if ledger.similar_line_pair_cells + cells > budgets.similar_line_pair_cells:
        return (), FallbackReason.PAIRING_CELLS
    ledger.similar_line_pair_cells += cells
    if not old or not new:
        return (), None

    old_tokens = [_tokens_for_similarity(line) for line in old]
    new_tokens = [_tokens_for_similarity(line) for line in new]
    scores = [0] * cells
    similarity_cost = 0
    for old_index, old_line in enumerate(old):
        for new_index, new_line in enumerate(new):
            score, cost = _line_similarity_score(
                old_line,
                new_line,
                old_tokens[old_index],
                new_tokens[new_index],
            )
            similarity_cost += cost
            if (
                ledger.similarity_matcher_cells + similarity_cost
                > budgets.similarity_matcher_cells
            ):
                return (), FallbackReason.SIMILARITY_CELLS
            if score >= SIMILARITY_SCORE_THRESHOLD:
                scores[old_index * len(new) + new_index] = score
    ledger.similarity_matcher_cells += similarity_cost

    width = len(new) + 1
    size = (len(old) + 1) * width
    best_score = [0] * size
    best_count = [0] * size
    choice = bytearray(size)
    for old_index in range(len(old) - 1, -1, -1):
        for new_index in range(len(new) - 1, -1, -1):
            cell = old_index * width + new_index
            skip_old = (old_index + 1) * width + new_index
            skip_new = old_index * width + new_index + 1
            score_value = best_score[skip_old]
            count_value = best_count[skip_old]
            choice[cell] = 3
            if (best_score[skip_new], best_count[skip_new]) >= (
                score_value,
                count_value,
            ):
                score_value = best_score[skip_new]
                count_value = best_count[skip_new]
                choice[cell] = 2
            pair_score = scores[old_index * len(new) + new_index]
            if pair_score:
                diagonal = (old_index + 1) * width + new_index + 1
                pair_value = (
                    pair_score + best_score[diagonal],
                    1 + best_count[diagonal],
                )
                if pair_value >= (score_value, count_value):
                    score_value, count_value = pair_value
                    choice[cell] = 1
            best_score[cell] = score_value
            best_count[cell] = count_value

    pairs: list[tuple[int, int]] = []
    old_index = 0
    new_index = 0
    while old_index < len(old) and new_index < len(new):
        selected = choice[old_index * width + new_index]
        if selected == 1:
            pairs.append((old_index, new_index))
            old_index += 1
            new_index += 1
        elif selected == 2:
            new_index += 1
        else:
            old_index += 1
    return tuple(pairs), None


def _line_similarity_score(
    old: LogicalLine,
    new: LogicalLine,
    old_tokens: Sequence[StringToken] | None,
    new_tokens: Sequence[StringToken] | None,
) -> tuple[int, int]:
    if old.body == new.body and old.terminator != new.terminator:
        return 1_000, 0
    if (
        len(old.text) > SIMILARITY_LINE_CODE_POINT_LIMIT
        or len(new.text) > SIMILARITY_LINE_CODE_POINT_LIMIT
        or old_tokens is None
        or new_tokens is None
        or len(old_tokens) > SIMILARITY_LINE_UNIT_LIMIT
        or len(new_tokens) > SIMILARITY_LINE_UNIT_LIMIT
    ):
        return 0, 0
    if min(len(old.text), len(new.text)) * 4 < max(len(old.text), len(new.text), 1):
        return 0, 0

    old_signature = [token.signature for token in old_tokens]
    new_signature = [token.signature for token in new_tokens]
    cost = len(old_signature) * len(new_signature)
    blocks = SequenceMatcher(
        None,
        old_signature,
        new_signature,
        autojunk=False,
    ).get_matching_blocks()
    matches = sum(block.size for block in blocks)
    has_content_match = any(
        old_tokens[block.a + offset].kind not in {TokenKind.SPACE, TokenKind.PUNCT}
        for block in blocks
        for offset in range(block.size)
    )
    denominator = len(old_signature) + len(new_signature)
    score = 2 * matches * 1_000 // denominator if denominator else 1_000
    if score and has_content_match:
        return score, cost
    if len(old_tokens) != 1 or len(new_tokens) != 1:
        return 0, cost

    old_graphemes = split_graphemes(old.text)
    new_graphemes = split_graphemes(new.text)
    grapheme_cost = len(old_graphemes) * len(new_graphemes)
    if grapheme_cost > MICRODIFF_CELL_LIMIT:
        return 0, cost
    matches = sum(
        block.size
        for block in SequenceMatcher(
            None,
            [item.text for item in old_graphemes],
            [item.text for item in new_graphemes],
            autojunk=False,
        ).get_matching_blocks()
    )
    denominator = len(old_graphemes) + len(new_graphemes)
    return (
        (2 * matches * 1_000 // denominator if denominator else 1_000),
        cost + grapheme_cost,
    )


def _tokens_for_similarity(
    line: LogicalLine,
) -> tuple[StringToken, ...] | None:
    if len(line.text) > SIMILARITY_LINE_CODE_POINT_LIMIT:
        return None
    tokens = tokenize_string(line.body)
    return tokens if len(tokens) <= SIMILARITY_LINE_UNIT_LIMIT else None


def _replacement_rows(
    old_lines: Sequence[LogicalLine],
    new_lines: Sequence[LogicalLine],
    old_start: int,
    old_end: int,
    new_start: int,
    new_end: int,
    pairs: Sequence[tuple[int, int]],
    budgets: StringBudgets,
) -> list[LineRow]:
    result: list[LineRow] = []
    old_offset = 0
    new_offset = 0
    old_window = old_lines[old_start:old_end]
    new_window = new_lines[new_start:new_end]
    for paired_old, paired_new in pairs:
        while old_offset < paired_old:
            line = old_window[old_offset]
            result.append(
                LineRow(
                    LineKind.REMOVED,
                    line.text,
                    old_line=old_start + old_offset,
                )
            )
            old_offset += 1
        while new_offset < paired_new:
            line = new_window[new_offset]
            result.append(
                LineRow(
                    LineKind.ADDED,
                    line.text,
                    new_line=new_start + new_offset,
                )
            )
            new_offset += 1
        fragments = _paired_line_fragments(
            old_window[paired_old],
            new_window[paired_new],
            budgets,
        )
        result.append(
            LineRow(
                LineKind.REMOVED,
                old_window[paired_old].text,
                fragments=tuple(
                    fragment
                    for fragment in fragments
                    if fragment.kind is not FragmentKind.ADDED
                ),
                old_line=old_start + paired_old,
            )
        )
        result.append(
            LineRow(
                LineKind.ADDED,
                new_window[paired_new].text,
                fragments=tuple(
                    fragment
                    for fragment in fragments
                    if fragment.kind is not FragmentKind.REMOVED
                ),
                new_line=new_start + paired_new,
            )
        )
        old_offset = paired_old + 1
        new_offset = paired_new + 1
    while old_offset < len(old_window):
        line = old_window[old_offset]
        result.append(
            LineRow(
                LineKind.REMOVED,
                line.text,
                old_line=old_start + old_offset,
            )
        )
        old_offset += 1
    while new_offset < len(new_window):
        line = new_window[new_offset]
        result.append(
            LineRow(
                LineKind.ADDED,
                line.text,
                new_line=new_start + new_offset,
            )
        )
        new_offset += 1
    return result


def _paired_line_fragments(
    old: LogicalLine,
    new: LogicalLine,
    budgets: StringBudgets,
) -> tuple[TextFragment, ...]:
    if old.body != new.body or old.terminator == new.terminator:
        return _build_fragments(old.text, new.text, budgets)

    body_end = len(old.body)
    fragments: list[TextFragment] = []
    if old.body:
        fragments.append(
            TextFragment(
                old.body,
                FragmentKind.UNCHANGED,
                0,
                body_end,
                0,
                body_end,
            )
        )
    if old.terminator:
        fragments.append(
            TextFragment(
                old.terminator,
                FragmentKind.REMOVED,
                body_end,
                len(old.text),
            )
        )
    if new.terminator:
        fragments.append(
            TextFragment(
                new.terminator,
                FragmentKind.ADDED,
                None,
                None,
                body_end,
                len(new.text),
            )
        )
    return tuple(fragments)


def _project_multiline(
    analysis: MultilineStringDiff,
    view: View,
    escape_for_width: EscapeForWidth,
    budgets: StringBudgets,
) -> MultilineStringDiff:
    if analysis.old_lines is None or analysis.new_lines is None:
        rows: Sequence[LineRow] = _coarse_preview_rows(
            analysis.old_preview,
            analysis.new_preview,
            analysis.old_line_count,
            analysis.new_line_count,
            analysis.old_code_point_count,
            analysis.new_code_point_count,
        )
    elif view is View.FULL:
        rows = analysis.rows
    else:
        rows = _select_line_context(analysis.rows, view)

    excerpt_cells = excerpt_cells_for_view(view)
    projected, limit_reason = _project_multiline_rows(
        rows,
        excerpt_cells,
        escape_for_width,
        budgets,
    )

    fallback = analysis.fallback_reason
    if limit_reason is not None:
        fallback = limit_reason
        old_source = (
            analysis.old_lines
            if analysis.old_lines is not None
            else analysis.old_preview
        )
        new_source = (
            analysis.new_lines
            if analysis.new_lines is not None
            else analysis.new_preview
        )
        coarse_rows = _coarse_preview_rows(
            _edge_preview(old_source),
            _edge_preview(new_source),
            analysis.old_line_count,
            analysis.new_line_count,
            analysis.old_code_point_count,
            analysis.new_code_point_count,
        )
        projected, _unused = _project_multiline_rows(
            coarse_rows,
            excerpt_cells,
            escape_for_width,
            budgets,
            enforce_limits=False,
        )
    return replace(
        analysis,
        rows=tuple(projected),
        fallback_reason=fallback,
    )


def _project_multiline_rows(
    rows: Sequence[LineRow],
    excerpt_cells: int,
    escape_for_width: EscapeForWidth,
    budgets: StringBudgets,
    *,
    enforce_limits: bool = True,
) -> tuple[list[LineRow], FallbackReason | None]:
    projected: list[LineRow] = []
    used_cells = 0
    for row in rows:
        if row.kind in {
            LineKind.OMITTED,
            LineKind.REMOVED_OMITTED,
            LineKind.ADDED_OMITTED,
        }:
            clipped = row
            row_cells = 32
        else:
            excerpt = bounded_excerpt(row.text, excerpt_cells, escape_for_width)
            clipped = replace(
                row,
                text=excerpt.text,
                fragments=() if excerpt.omitted else row.fragments,
                omitted_code_points=excerpt.omitted,
            )
            row_cells = display_width(escape_for_width(excerpt.text))
        if enforce_limits and len(projected) >= budgets.detail_rows:
            return projected, FallbackReason.DETAIL_ROWS
        if enforce_limits and used_cells + row_cells > budgets.detail_display_cells:
            return projected, FallbackReason.DETAIL_CELLS
        projected.append(clipped)
        used_cells += row_cells
    return projected, None


def _select_line_context(
    rows: Sequence[LineRow],
    view: View,
) -> list[LineRow]:
    if view is View.FULL:
        return list(rows)
    context = SUMMARY_CONTEXT_LINES if view is View.SUMMARY else REVIEW_CONTEXT_LINES
    result: list[LineRow] = []
    index = 0
    while index < len(rows):
        if rows[index].kind is not LineKind.UNCHANGED:
            result.append(rows[index])
            index += 1
            continue
        end = index
        while end < len(rows) and rows[end].kind is LineKind.UNCHANGED:
            end += 1
        run = rows[index:end]
        before = index > 0
        after = end < len(rows)
        if before and after:
            first = run[:context]
            remaining_context = len(run) - len(first)
            keep_at_end = min(context, remaining_context)
            last = run[-keep_at_end:] if keep_at_end else ()
        elif before:
            first = run[:context]
            last = ()
        elif after:
            first = ()
            last = run[-context:]
        else:
            first = run[:context]
            last = ()
        kept = len(first) + len(last)
        result.extend(first)
        if len(run) > kept:
            result.append(LineRow(LineKind.OMITTED, count=len(run) - kept))
        result.extend(last)
        index = end
    return result


def _coarse_preview_rows(
    old_preview: Sequence[LogicalLine],
    new_preview: Sequence[LogicalLine],
    old_count: int,
    new_count: int,
    old_code_points: int,
    new_code_points: int,
) -> list[LineRow]:
    result: list[LineRow] = []
    old_head, old_tail = _split_preview(old_preview, old_count)
    new_head, new_tail = _split_preview(new_preview, new_count)
    result.extend(LineRow(LineKind.REMOVED, line.text) for line in old_head)
    old_omitted = old_count - len(old_head) - len(old_tail)
    if old_omitted:
        shown_code_points = sum(len(line.text) for line in (*old_head, *old_tail))
        result.append(
            LineRow(
                LineKind.REMOVED_OMITTED,
                count=old_omitted,
                omitted_code_points=old_code_points - shown_code_points,
            )
        )
    result.extend(LineRow(LineKind.REMOVED, line.text) for line in old_tail)
    result.extend(LineRow(LineKind.ADDED, line.text) for line in new_head)
    new_omitted = new_count - len(new_head) - len(new_tail)
    if new_omitted:
        shown_code_points = sum(len(line.text) for line in (*new_head, *new_tail))
        result.append(
            LineRow(
                LineKind.ADDED_OMITTED,
                count=new_omitted,
                omitted_code_points=new_code_points - shown_code_points,
            )
        )
    result.extend(LineRow(LineKind.ADDED, line.text) for line in new_tail)
    return result


def _split_preview(
    preview: Sequence[LogicalLine],
    total: int,
) -> tuple[Sequence[LogicalLine], Sequence[LogicalLine]]:
    if total <= 4:
        return preview, ()
    return preview[:2], preview[-2:]


def _edge_preview(lines: Sequence[LogicalLine]) -> tuple[LogicalLine, ...]:
    if len(lines) <= 4:
        return tuple(lines)
    return (*lines[:2], *lines[-2:])


def _build_long_diff(
    old: str,
    new: str,
    budgets: StringBudgets,
) -> LongStringDiff:
    prefix = _common_grapheme_prefix(old, new)
    suffix = _common_grapheme_suffix(old, new, prefix)
    old_end = len(old) - suffix if suffix else len(old)
    new_end = len(new) - suffix if suffix else len(new)
    old_middle = old[prefix:old_end]
    new_middle = new[prefix:new_end]
    combined_code_points = len(old_middle) + len(new_middle)
    if combined_code_points > budgets.blob_interior_code_points:
        return _coarse_long(
            old,
            new,
            prefix,
            suffix,
            FallbackReason.BLOB_CODE_POINTS,
        )

    old_units = _blob_units(old_middle, budgets.blob_units)
    new_units = _blob_units(new_middle, budgets.blob_units)
    if old_units is None or new_units is None:
        return _coarse_long(
            old,
            new,
            prefix,
            suffix,
            FallbackReason.BLOB_UNITS,
        )
    unit_count = len(old_units) + len(new_units)
    if unit_count > budgets.blob_units:
        return _coarse_long(
            old,
            new,
            prefix,
            suffix,
            FallbackReason.BLOB_UNITS,
        )
    cells = len(old_units) * len(new_units)
    if cells > budgets.blob_cells:
        return _coarse_long(
            old,
            new,
            prefix,
            suffix,
            FallbackReason.BLOB_CELLS,
            unit_count,
            cells,
        )

    opcodes = SequenceMatcher(
        None,
        [unit.signature for unit in old_units],
        [unit.signature for unit in new_units],
        autojunk=False,
    ).get_opcodes()
    if len(opcodes) > budgets.blob_opcodes:
        return _coarse_long(
            old,
            new,
            prefix,
            suffix,
            FallbackReason.BLOB_OPCODES,
            unit_count,
            cells,
            len(opcodes),
        )
    groups = _blob_change_groups(
        old_middle,
        new_middle,
        old_units,
        new_units,
        opcodes,
    )
    if len(groups) > budgets.blob_hunks:
        return _coarse_long(
            old,
            new,
            prefix,
            suffix,
            FallbackReason.BLOB_HUNKS,
            unit_count,
            cells,
            len(opcodes),
        )
    hunks = tuple(
        LongStringHunk(
            prefix + old_start,
            prefix + old_stop,
            prefix + new_start,
            prefix + new_stop,
        )
        for old_start, old_stop, new_start, new_stop in groups
    )
    return LongStringDiff(
        old,
        new,
        len(old),
        len(new),
        prefix,
        suffix,
        hunks,
        work=StringWorkCounters(
            blob_units=unit_count,
            blob_matcher_cells=cells,
            blob_opcodes=len(opcodes),
        ),
    )


def _coarse_long(
    old: str,
    new: str,
    prefix: int,
    suffix: int,
    reason: FallbackReason,
    units: int = 0,
    cells: int = 0,
    opcodes: int = 0,
) -> LongStringDiff:
    old_end = len(old) - suffix if suffix else len(old)
    new_end = len(new) - suffix if suffix else len(new)
    return LongStringDiff(
        old,
        new,
        len(old),
        len(new),
        prefix,
        suffix,
        (LongStringHunk(prefix, old_end, prefix, new_end),),
        reason,
        StringWorkCounters(
            blob_units=units,
            blob_matcher_cells=cells,
            blob_opcodes=opcodes,
        ),
    )


def _blob_units(text: str, limit: int) -> list[_Unit] | None:
    tokens = _tokenize_string_limited(text, limit)
    if tokens is None:
        return None
    if len(tokens) == 1 and tokens[0].kind in {TokenKind.IDENT, TokenKind.NUMBER}:
        units: list[_Unit] = []
        for match in _GRAPHEME_RE.finditer(text):
            if len(units) >= limit:
                return None
            units.append(_Unit(match.group(), match.start(), match.end()))
        return units
    return [_Unit(token.signature, token.start, token.end) for token in tokens]


def _blob_change_groups(
    old_text: str,
    new_text: str,
    old_units: Sequence[_Unit],
    new_units: Sequence[_Unit],
    opcodes: Sequence[Opcode],
) -> list[tuple[int, int, int, int]]:
    groups: list[tuple[int, int, int, int]] = []
    for tag, old_start, old_end, new_start, new_end in opcodes:
        if tag == "equal":
            continue
        group = (
            _unit_boundary(old_units, old_start, len(old_text)),
            _unit_boundary(old_units, old_end, len(old_text)),
            _unit_boundary(new_units, new_start, len(new_text)),
            _unit_boundary(new_units, new_end, len(new_text)),
        )
        if groups:
            previous = groups[-1]
            old_gap = old_text[previous[1] : group[0]]
            new_gap = new_text[previous[3] : group[2]]
            if (
                display_width(old_gap) <= BLOB_MERGE_GAP_CELLS
                and display_width(new_gap) <= BLOB_MERGE_GAP_CELLS
            ):
                groups[-1] = (
                    previous[0],
                    group[1],
                    previous[2],
                    group[3],
                )
                continue
        groups.append(group)
    return groups


def _unit_boundary(
    units: Sequence[_Unit],
    index: int,
    text_length: int,
) -> int:
    return units[index].start if index < len(units) else text_length


def _common_grapheme_prefix(old: str, new: str) -> int:
    prefix = 0
    for old_match, new_match in zip(
        _GRAPHEME_RE.finditer(old),
        _GRAPHEME_RE.finditer(new),
        strict=False,
    ):
        if old_match.group() != new_match.group():
            break
        prefix = old_match.end()
    return prefix


def _common_grapheme_suffix(old: str, new: str, prefix: int) -> int:
    old_count = sum(1 for _match in _GRAPHEME_RE.finditer(old))
    new_count = sum(1 for _match in _GRAPHEME_RE.finditer(new))
    aligned_count = min(old_count, new_count)
    old_matches = _GRAPHEME_RE.finditer(old)
    new_matches = _GRAPHEME_RE.finditer(new)
    for _index in range(old_count - aligned_count):
        next(old_matches)
    for _index in range(new_count - aligned_count):
        next(new_matches)

    suffix = 0
    for old_match, new_match in zip(old_matches, new_matches, strict=True):
        if (
            old_match.start() < prefix
            or new_match.start() < prefix
            or old_match.group() != new_match.group()
        ):
            suffix = 0
        else:
            suffix += len(old_match.group())
    return suffix


def _project_long(
    analysis: LongStringDiff,
    view: View,
    escape_for_width: EscapeForWidth,
) -> ProjectedLongStringDiff:
    width = excerpt_cells_for_view(view)
    old_partitions = [
        _grapheme_partition(
            analysis.old_text,
            previous.old_end,
            current.old_start,
        )
        for previous, current in zip(analysis.hunks, analysis.hunks[1:], strict=False)
    ]
    new_partitions = [
        _grapheme_partition(
            analysis.new_text,
            previous.new_end,
            current.new_start,
        )
        for previous, current in zip(analysis.hunks, analysis.hunks[1:], strict=False)
    ]
    hunks: list[ProjectedLongStringHunk] = []
    for index, hunk in enumerate(analysis.hunks):
        old_lower = old_partitions[index - 1] if index > 0 else 0
        new_lower = new_partitions[index - 1] if index > 0 else 0
        old_upper = (
            analysis.old_length
            if index + 1 == len(analysis.hunks)
            else old_partitions[index]
        )
        new_upper = (
            analysis.new_length
            if index + 1 == len(analysis.hunks)
            else new_partitions[index]
        )
        hunks.append(
            ProjectedLongStringHunk(
                hunk.old_start,
                hunk.old_end,
                hunk.new_start,
                hunk.new_end,
                _hunk_excerpt(
                    analysis.old_text,
                    old_lower,
                    hunk.old_start,
                    hunk.old_end,
                    old_upper,
                    width,
                    escape_for_width,
                ),
                _hunk_excerpt(
                    analysis.new_text,
                    new_lower,
                    hunk.new_start,
                    hunk.new_end,
                    new_upper,
                    width,
                    escape_for_width,
                ),
            )
        )
    return ProjectedLongStringDiff(
        analysis.old_length,
        analysis.new_length,
        analysis.omitted_before,
        analysis.omitted_after,
        tuple(hunks),
        analysis.fallback_reason,
        analysis.work,
    )


def _grapheme_partition(text: str, start: int, end: int) -> int:
    """Choose a midpoint-like boundary without bisecting a grapheme."""

    target = (start + end) // 2
    if target <= start:
        return start
    if target >= end:
        return end
    for match in _GRAPHEME_RE.finditer(text, start, end):
        if match.end() < target:
            continue
        before = match.start()
        after = match.end()
        return before if target - before <= after - target else after
    return end


def _hunk_excerpt(
    text: str,
    lower: int,
    start: int,
    end: int,
    upper: int,
    width: int,
    escape_for_width: EscapeForWidth,
) -> Excerpt:
    changed = text[start:end]
    changed_excerpt = bounded_excerpt(changed, width, escape_for_width)
    if changed_excerpt.omitted:
        return replace(
            changed_excerpt,
            source_start=start,
            source_end=end,
        )
    changed_width = display_width(escape_for_width(changed))
    remaining = max(width - changed_width, 0)
    left_budget = remaining // 2
    right_budget = remaining - left_budget
    left = list(
        _take_text_right(
            text,
            lower,
            start,
            left_budget,
            escape_for_width,
        )
    )
    right = list(
        _take_text_left(
            text,
            end,
            upper,
            right_budget,
            escape_for_width,
        )
    )
    candidate = (
        "".join(item.text for item in left)
        + changed
        + "".join(item.text for item in right)
    )
    while display_width(escape_for_width(candidate)) > width and (left or right):
        if _grapheme_text_width(left, escape_for_width) >= _grapheme_text_width(
            right,
            escape_for_width,
        ):
            left = left[1:]
        else:
            right = right[:-1]
        candidate = (
            "".join(item.text for item in left)
            + changed
            + "".join(item.text for item in right)
        )
    source_start = left[0].start if left else start
    source_end = right[-1].end if right else end
    return Excerpt(candidate, 0, source_start, source_end)


def _fits_display_cells(
    text: str,
    max_cells: int,
    escape_for_width: EscapeForWidth,
) -> bool:
    used = 0
    for match in _GRAPHEME_RE.finditer(text):
        used += display_width(escape_for_width(match.group()))
        if used > max_cells:
            return False
    return display_width(escape_for_width(text)) <= max_cells


def _take_text_left(
    text: str,
    start: int,
    end: int,
    max_cells: int,
    escape_for_width: EscapeForWidth,
) -> tuple[Grapheme, ...]:
    chosen: list[Grapheme] = []
    used = 0
    for match in _GRAPHEME_RE.finditer(text, start, end):
        item = Grapheme(match.group(), match.start(), match.end())
        width = display_width(escape_for_width(item.text))
        if chosen and used + width > max_cells:
            break
        if not chosen and width > max_cells and max_cells > 0:
            chosen.append(item)
            break
        if max_cells <= 0:
            break
        chosen.append(item)
        used += width
    return tuple(chosen)


def _take_text_right(
    text: str,
    start: int,
    end: int,
    max_cells: int,
    escape_for_width: EscapeForWidth,
) -> tuple[Grapheme, ...]:
    if max_cells <= 0:
        return ()
    chosen: deque[tuple[Grapheme, int]] = deque()
    used = 0
    for match in _GRAPHEME_RE.finditer(text, start, end):
        item = Grapheme(match.group(), match.start(), match.end())
        width = display_width(escape_for_width(item.text))
        chosen.append((item, width))
        used += width
        while len(chosen) > 1 and used > max_cells:
            _removed, removed_width = chosen.popleft()
            used -= removed_width
    return tuple(item for item, _width in chosen)


def _grapheme_text_width(
    graphemes: Sequence[Grapheme],
    escape_for_width: EscapeForWidth,
) -> int:
    return display_width(escape_for_width("".join(item.text for item in graphemes)))


def _is_blob_candidate(text: str) -> bool:
    if len(text) >= BLOB_HARD_CODE_POINT_LIMIT:
        return True
    whitespace = sum(character.isspace() for character in text)
    separators = sum(character in _BLOB_SEPARATORS for character in text)
    if (
        len(text) >= BLOB_DENSE_CODE_POINT_LIMIT
        and whitespace <= len(text) // 20
        and separators >= 3
    ):
        return True
    longest = 0
    current = 0
    for character in text:
        if character.isspace():
            longest = max(longest, current)
            current = 0
        else:
            current += 1
    return max(longest, current) >= BLOB_OPAQUE_RUN_LIMIT


def _identity_text(text: str) -> str:
    return text
