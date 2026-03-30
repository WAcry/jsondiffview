from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache

import regex
from patiencediff import PatienceSequenceMatcher
from wcwidth import wcswidth

from .model import (
    DiffSettings,
    StringBlobHunk,
    StringDetail,
    StringLine,
    StringMode,
    StringMultilineHunk,
    StringSpan,
    StringSummary,
    StringToken,
    StringTokenKind,
)


_TOKEN_RE = regex.compile(
    r"(?P<IDENT>\p{L}[\p{L}\p{M}\p{Nd}]*)"
    r"|(?P<NUMBER>\p{Nd}+)"
    r"|(?P<SPACE>[^\S\r\n]+)"
    r"|(?P<PUNCT>[-./:_=+?&@#%|\\]+)"
    r"|(?P<OTHER>\X)"
)
_GRAPHEME_RE = regex.compile(r"\X")
_BLOB_SEPARATORS = frozenset("-./:_=+?&@#%|\\")


@dataclass(frozen=True)
class _LinePairingResult:
    score: float
    count: int
    pairs: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class _BlobGroup:
    old_start: int
    old_end: int
    new_start: int
    new_end: int


def classify_string_mode(old_text: str, new_text: str, settings: DiffSettings) -> StringMode:
    if "\n" in old_text or "\n" in new_text:
        return StringMode.MULTILINE_BLOCK

    if _is_blob_candidate(old_text, settings) or _is_blob_candidate(new_text, settings):
        return StringMode.BLOB_SUMMARY

    return StringMode.INLINE_TOKEN


def tokenize_string(text: str) -> list[StringToken]:
    tokens: list[StringToken] = []
    cursor = 0
    for match in _TOKEN_RE.finditer(text):
        if match.start() != cursor:
            raise ValueError(f"tokenizer gap detected at offset {cursor}")
        group_name = match.lastgroup
        assert group_name is not None
        tokens.append(
            StringToken(
                kind=_TOKEN_KIND_BY_GROUP[group_name],
                text=match.group(),
            )
        )
        cursor = match.end()

    if cursor != len(text):
        raise ValueError(f"tokenizer stopped early at offset {cursor}")
    return tokens


def split_graphemes(text: str) -> list[str]:
    return _GRAPHEME_RE.findall(text)


def build_string_detail(old_text: str, new_text: str, settings: DiffSettings) -> StringDetail:
    mode = classify_string_mode(old_text, new_text, settings)
    detail = StringDetail(mode=mode, old_text=old_text, new_text=new_text)

    if mode is StringMode.INLINE_TOKEN:
        detail.inline_spans = _build_inline_spans(old_text, new_text, settings)
        return detail

    if mode is StringMode.MULTILINE_BLOCK:
        detail.old_line_count = len(old_text.splitlines(keepends=False))
        detail.new_line_count = len(new_text.splitlines(keepends=False))
        detail.trailing_newline_changed = old_text.endswith("\n") != new_text.endswith("\n")
        detail.multiline_hunks = _build_multiline_hunks(old_text, new_text, settings)
        return detail

    detail.blob_hunks = _build_blob_hunks(old_text, new_text, settings)
    detail.summary = StringSummary(
        old_len=len(old_text),
        new_len=len(new_text),
        hunk_count=len(detail.blob_hunks),
    )
    return detail


def build_paired_string_line_spans(
    old_text: str,
    new_text: str,
    settings: DiffSettings,
) -> tuple[list[StringSpan], list[StringSpan]]:
    old_tokens = tokenize_string(old_text)
    new_tokens = tokenize_string(new_text)
    _, old_side, new_side = _build_all_span_views(old_tokens, new_tokens, settings)
    return old_side, new_side


_TOKEN_KIND_BY_GROUP = {
    "IDENT": StringTokenKind.IDENT,
    "NUMBER": StringTokenKind.NUMBER,
    "SPACE": StringTokenKind.SPACE,
    "PUNCT": StringTokenKind.PUNCT,
    "OTHER": StringTokenKind.OTHER,
}


def _build_inline_spans(old_text: str, new_text: str, settings: DiffSettings) -> list[StringSpan]:
    old_tokens = tokenize_string(old_text)
    new_tokens = tokenize_string(new_text)
    combined, _, _ = _build_all_span_views(old_tokens, new_tokens, settings)
    return combined


def _build_all_span_views(
    old_tokens: list[StringToken],
    new_tokens: list[StringToken],
    settings: DiffSettings,
) -> tuple[list[StringSpan], list[StringSpan], list[StringSpan]]:
    combined: list[StringSpan] = []
    old_side: list[StringSpan] = []
    new_side: list[StringSpan] = []

    matcher = SequenceMatcher(
        a=_token_signature(old_tokens),
        b=_token_signature(new_tokens),
        autojunk=False,
    )
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        old_slice = old_tokens[old_start:old_end]
        new_slice = new_tokens[new_start:new_end]
        if tag == "equal":
            text = _concat_token_text(old_slice)
            combined.append(StringSpan(role="plain", text=text))
            old_side.append(StringSpan(role="plain", text=text))
            new_side.append(StringSpan(role="plain", text=text))
            continue

        if tag == "delete":
            text = _concat_token_text(old_slice)
            combined.append(StringSpan(role="removed", text=text))
            old_side.append(StringSpan(role="removed", text=text))
            continue

        if tag == "insert":
            text = _concat_token_text(new_slice)
            combined.append(StringSpan(role="added", text=text))
            new_side.append(StringSpan(role="added", text=text))
            continue

        if _can_microdiff(old_slice, new_slice, settings):
            micro = _build_microdiff_spans(old_slice[0].text, new_slice[0].text)
            combined.extend(micro)
            old_side.extend(_filter_side_spans(micro, keep_role="removed"))
            new_side.extend(_filter_side_spans(micro, keep_role="added"))
            continue

        old_text = _concat_token_text(old_slice)
        new_text = _concat_token_text(new_slice)
        if old_text:
            combined.append(StringSpan(role="removed", text=old_text))
            old_side.append(StringSpan(role="removed", text=old_text))
        if new_text:
            combined.append(StringSpan(role="added", text=new_text))
            new_side.append(StringSpan(role="added", text=new_text))

    return (
        _combine_adjacent_spans(combined),
        _combine_adjacent_spans(old_side),
        _combine_adjacent_spans(new_side),
    )


def _filter_side_spans(
    spans: list[StringSpan],
    keep_role: str,
) -> list[StringSpan]:
    return [
        span
        for span in spans
        if span.role == "plain" or span.role == keep_role
    ]


def _can_microdiff(
    old_tokens: list[StringToken],
    new_tokens: list[StringToken],
    settings: DiffSettings,
) -> bool:
    if len(old_tokens) != 1 or len(new_tokens) != 1:
        return False

    old_token = old_tokens[0]
    new_token = new_tokens[0]
    if old_token.kind is not new_token.kind:
        return False
    if old_token.kind not in (StringTokenKind.IDENT, StringTokenKind.NUMBER):
        return False

    old_graphemes = split_graphemes(old_token.text)
    new_graphemes = split_graphemes(new_token.text)
    if (
        len(old_graphemes) > settings.string_microdiff_max_token_graphemes
        or len(new_graphemes) > settings.string_microdiff_max_token_graphemes
    ):
        return False

    shared = _shared_affix_len(old_graphemes, new_graphemes)
    return shared >= settings.string_microdiff_min_shared_affix


def _build_microdiff_spans(old_text: str, new_text: str) -> list[StringSpan]:
    spans: list[StringSpan] = []
    old_graphemes = split_graphemes(old_text)
    new_graphemes = split_graphemes(new_text)
    matcher = SequenceMatcher(a=old_graphemes, b=new_graphemes, autojunk=False)
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            text = "".join(old_graphemes[old_start:old_end])
            spans.append(StringSpan(role="plain", text=text))
            continue
        if tag == "delete":
            spans.append(StringSpan(role="removed", text="".join(old_graphemes[old_start:old_end])))
            continue
        if tag == "insert":
            spans.append(StringSpan(role="added", text="".join(new_graphemes[new_start:new_end])))
            continue
        removed = "".join(old_graphemes[old_start:old_end])
        added = "".join(new_graphemes[new_start:new_end])
        if removed:
            spans.append(StringSpan(role="removed", text=removed))
        if added:
            spans.append(StringSpan(role="added", text=added))
    return _combine_adjacent_spans(spans)


def _build_multiline_hunks(old_text: str, new_text: str, settings: DiffSettings) -> list[StringMultilineHunk]:
    old_lines = old_text.splitlines(keepends=False)
    new_lines = new_text.splitlines(keepends=False)
    matcher = PatienceSequenceMatcher(None, old_lines, new_lines)
    opcodes = matcher.get_opcodes()

    windows: list[tuple[int, int, int, int, tuple[int, int] | None, tuple[int, int] | None]] = []
    index = 0
    while index < len(opcodes):
        tag, old_start, old_end, new_start, new_end = opcodes[index]
        if tag == "equal":
            index += 1
            continue

        merged_old_start = old_start
        merged_old_end = old_end
        merged_new_start = new_start
        merged_new_end = new_end
        window_start_index = index
        while index + 1 < len(opcodes) and opcodes[index + 1][0] != "equal":
            index += 1
            _, inner_old_start, inner_old_end, inner_new_start, inner_new_end = opcodes[index]
            merged_old_end = inner_old_end
            merged_new_end = inner_new_end

        prev_equal = None
        if window_start_index > 0 and opcodes[window_start_index - 1][0] == "equal":
            _, eq_old_start, eq_old_end, _, _ = opcodes[window_start_index - 1]
            prev_equal = (eq_old_start, eq_old_end)

        next_equal = None
        if index + 1 < len(opcodes) and opcodes[index + 1][0] == "equal":
            _, eq_old_start, eq_old_end, _, _ = opcodes[index + 1]
            next_equal = (eq_old_start, eq_old_end)

        windows.append(
            (
                merged_old_start,
                merged_old_end,
                merged_new_start,
                merged_new_end,
                prev_equal,
                next_equal,
            )
        )
        index += 1

    if not windows:
        return [
            StringMultilineHunk(
                prefix_context=[
                    _context_line(
                        line_text=line,
                        old_line_no=index + 1,
                        new_line_no=index + 1,
                    )
                    for index, line in enumerate(old_lines)
                ],
                body=[],
                suffix_context=[],
            )
        ]

    hunks: list[StringMultilineHunk] = []
    for old_start, old_end, new_start, new_end, prev_equal, next_equal in windows:
        prefix_context = []
        if prev_equal is not None:
            prefix_context = [
                _context_line(
                    line_text=line,
                    old_line_no=line_index + 1,
                    new_line_no=line_index + 1,
                )
                for line_index, line in enumerate(old_lines[prev_equal[0]:prev_equal[1]], start=prev_equal[0])
            ]

        suffix_context = []
        if next_equal is not None:
            suffix_context = [
                _context_line(
                    line_text=line,
                    old_line_no=line_index + 1,
                    new_line_no=line_index + 1,
                )
                for line_index, line in enumerate(old_lines[next_equal[0]:next_equal[1]], start=next_equal[0])
            ]

        body = _build_multiline_window_body(
            old_lines[old_start:old_end],
            new_lines[new_start:new_end],
            settings,
            old_line_offset=old_start,
            new_line_offset=new_start,
        )
        hunks.append(
            StringMultilineHunk(
                prefix_context=prefix_context,
                body=body,
                suffix_context=suffix_context,
            )
        )

    return hunks


def _build_multiline_window_body(
    old_lines: list[str],
    new_lines: list[str],
    settings: DiffSettings,
    old_line_offset: int,
    new_line_offset: int,
) -> list[StringLine]:
    pairs = _pair_replace_window_lines(old_lines, new_lines, settings)
    body: list[StringLine] = []
    old_index = 0
    new_index = 0

    for pair_old_index, pair_new_index in pairs:
        while old_index < pair_old_index:
            body.append(
                StringLine(
                    kind="removed",
                    spans=[StringSpan(role="plain", text=old_lines[old_index])],
                    text=old_lines[old_index],
                    old_line_no=old_line_offset + old_index + 1,
                )
            )
            old_index += 1

        while new_index < pair_new_index:
            body.append(
                StringLine(
                    kind="added",
                    spans=[StringSpan(role="plain", text=new_lines[new_index])],
                    text=new_lines[new_index],
                    new_line_no=new_line_offset + new_index + 1,
                )
            )
            new_index += 1

        old_spans, new_spans = build_paired_string_line_spans(
            old_lines[pair_old_index],
            new_lines[pair_new_index],
            settings,
        )
        body.append(
            StringLine(
                kind="removed",
                spans=old_spans,
                text=old_lines[pair_old_index],
                old_line_no=old_line_offset + pair_old_index + 1,
            )
        )
        body.append(
            StringLine(
                kind="added",
                spans=new_spans,
                text=new_lines[pair_new_index],
                new_line_no=new_line_offset + pair_new_index + 1,
            )
        )
        old_index = pair_old_index + 1
        new_index = pair_new_index + 1

    while old_index < len(old_lines):
        body.append(
            StringLine(
                kind="removed",
                spans=[StringSpan(role="plain", text=old_lines[old_index])],
                text=old_lines[old_index],
                old_line_no=old_line_offset + old_index + 1,
            )
        )
        old_index += 1

    while new_index < len(new_lines):
        body.append(
            StringLine(
                kind="added",
                spans=[StringSpan(role="plain", text=new_lines[new_index])],
                text=new_lines[new_index],
                new_line_no=new_line_offset + new_index + 1,
            )
        )
        new_index += 1

    return body


def _pair_replace_window_lines(
    old_lines: list[str],
    new_lines: list[str],
    settings: DiffSettings,
) -> tuple[tuple[int, int], ...]:
    if len(old_lines) * len(new_lines) > 50_000:
        return tuple(
            (index, index)
            for index in range(min(len(old_lines), len(new_lines)))
            if _line_similarity(old_lines[index], new_lines[index]) >= settings.string_multiline_pair_min_ratio
        )

    ratios = [
        [
            _line_similarity(old_line, new_line)
            for new_line in new_lines
        ]
        for old_line in old_lines
    ]

    @lru_cache(maxsize=None)
    def solve(old_index: int, new_index: int) -> _LinePairingResult:
        if old_index >= len(old_lines) or new_index >= len(new_lines):
            return _LinePairingResult(score=0.0, count=0, pairs=())

        best = solve(old_index + 1, new_index)
        candidate = solve(old_index, new_index + 1)
        if _is_better_pairing(candidate, best):
            best = candidate

        ratio = ratios[old_index][new_index]
        if ratio >= settings.string_multiline_pair_min_ratio:
            remainder = solve(old_index + 1, new_index + 1)
            candidate = _LinePairingResult(
                score=ratio + remainder.score,
                count=remainder.count + 1,
                pairs=((old_index, new_index),) + remainder.pairs,
            )
            if _is_better_pairing(candidate, best):
                best = candidate

        return best

    return solve(0, 0).pairs


def _is_better_pairing(candidate: _LinePairingResult, current: _LinePairingResult) -> bool:
    if candidate.score > current.score + 1e-9:
        return True
    if current.score > candidate.score + 1e-9:
        return False
    if candidate.count != current.count:
        return candidate.count > current.count
    return candidate.pairs < current.pairs


def _line_similarity(old_line: str, new_line: str) -> float:
    old_signature = _token_signature(tokenize_string(old_line))
    new_signature = _token_signature(tokenize_string(new_line))
    token_ratio = SequenceMatcher(a=old_signature, b=new_signature, autojunk=False).ratio()
    if token_ratio > 0:
        return token_ratio
    return SequenceMatcher(a=split_graphemes(old_line), b=split_graphemes(new_line), autojunk=False).ratio()


def _build_blob_hunks(old_text: str, new_text: str, settings: DiffSettings) -> list[StringBlobHunk]:
    old_tokens = tokenize_string(old_text)
    new_tokens = tokenize_string(new_text)
    if (
        len(old_tokens) == 1
        and len(new_tokens) == 1
        and old_tokens[0].kind is new_tokens[0].kind
    ):
        return _build_blob_hunks_from_graphemes(old_text, new_text, settings)

    opcodes = SequenceMatcher(
        a=_token_signature(old_tokens),
        b=_token_signature(new_tokens),
        autojunk=False,
    ).get_opcodes()
    groups = _merge_blob_groups(old_tokens, opcodes, settings)
    max_context_columns = settings.string_blob_excerpt_columns_full

    hunks: list[StringBlobHunk] = []
    for index, group in enumerate(groups):
        prev_old_end = groups[index - 1].old_end if index > 0 else 0
        prev_new_end = groups[index - 1].new_end if index > 0 else 0
        next_old_start = groups[index + 1].old_start if index + 1 < len(groups) else len(old_tokens)
        next_new_start = groups[index + 1].new_start if index + 1 < len(groups) else len(new_tokens)

        before_old = _concat_token_text(old_tokens[prev_old_end:group.old_start])
        before_new = _concat_token_text(new_tokens[prev_new_end:group.new_start])
        after_old = _concat_token_text(old_tokens[group.old_end:next_old_start])
        after_new = _concat_token_text(new_tokens[group.new_end:next_new_start])

        prefix_old = _take_right_columns(before_old, max_context_columns)
        prefix_new = _take_right_columns(before_new, max_context_columns)
        suffix_old = _take_left_columns(after_old, max_context_columns)
        suffix_new = _take_left_columns(after_new, max_context_columns)

        old_group_tokens = old_tokens[group.old_start:group.old_end]
        new_group_tokens = new_tokens[group.new_start:group.new_end]
        if (
            len(old_group_tokens) == 1
            and len(new_group_tokens) == 1
            and old_group_tokens[0].kind is new_group_tokens[0].kind
        ):
            micro = _build_microdiff_spans(old_group_tokens[0].text, new_group_tokens[0].text)
            old_group_spans = _filter_side_spans(micro, keep_role="removed")
            new_group_spans = _filter_side_spans(micro, keep_role="added")
        else:
            _, old_group_spans, new_group_spans = _build_all_span_views(
                old_group_tokens,
                new_group_tokens,
                settings,
            )

        old_spans = _combine_adjacent_spans(
            _surround_with_plain_text(prefix_old, old_group_spans, suffix_old)
        )
        new_spans = _combine_adjacent_spans(
            _surround_with_plain_text(prefix_new, new_group_spans, suffix_new)
        )
        hunks.append(
            StringBlobHunk(
                old_spans=old_spans,
                new_spans=new_spans,
                omitted_before_chars=max(
                    len(before_old) - len(prefix_old),
                    len(before_new) - len(prefix_new),
                ),
                omitted_after_chars=max(
                    len(after_old) - len(suffix_old),
                    len(after_new) - len(suffix_new),
                ),
            )
        )

    return hunks


def _build_blob_hunks_from_graphemes(
    old_text: str,
    new_text: str,
    settings: DiffSettings,
) -> list[StringBlobHunk]:
    old_units = split_graphemes(old_text)
    new_units = split_graphemes(new_text)
    opcodes = SequenceMatcher(a=old_units, b=new_units, autojunk=False).get_opcodes()
    groups = _merge_blob_groups_from_text_units(old_units, opcodes, settings)
    max_context_columns = settings.string_blob_excerpt_columns_full

    hunks: list[StringBlobHunk] = []
    for index, group in enumerate(groups):
        prev_old_end = groups[index - 1].old_end if index > 0 else 0
        prev_new_end = groups[index - 1].new_end if index > 0 else 0
        next_old_start = groups[index + 1].old_start if index + 1 < len(groups) else len(old_units)
        next_new_start = groups[index + 1].new_start if index + 1 < len(groups) else len(new_units)

        before_old = "".join(old_units[prev_old_end:group.old_start])
        before_new = "".join(new_units[prev_new_end:group.new_start])
        after_old = "".join(old_units[group.old_end:next_old_start])
        after_new = "".join(new_units[group.new_end:next_new_start])

        prefix_old = _take_right_columns(before_old, max_context_columns)
        prefix_new = _take_right_columns(before_new, max_context_columns)
        suffix_old = _take_left_columns(after_old, max_context_columns)
        suffix_new = _take_left_columns(after_new, max_context_columns)

        micro = _build_microdiff_spans(
            "".join(old_units[group.old_start:group.old_end]),
            "".join(new_units[group.new_start:group.new_end]),
        )
        old_group_spans = _filter_side_spans(micro, keep_role="removed")
        new_group_spans = _filter_side_spans(micro, keep_role="added")

        hunks.append(
            StringBlobHunk(
                old_spans=_combine_adjacent_spans(
                    _surround_with_plain_text(prefix_old, old_group_spans, suffix_old)
                ),
                new_spans=_combine_adjacent_spans(
                    _surround_with_plain_text(prefix_new, new_group_spans, suffix_new)
                ),
                omitted_before_chars=max(
                    len(before_old) - len(prefix_old),
                    len(before_new) - len(prefix_new),
                ),
                omitted_after_chars=max(
                    len(after_old) - len(suffix_old),
                    len(after_new) - len(suffix_new),
                ),
            )
        )

    return hunks


def _merge_blob_groups(
    old_tokens: list[StringToken],
    opcodes: list[tuple[str, int, int, int, int]],
    settings: DiffSettings,
) -> list[_BlobGroup]:
    groups: list[_BlobGroup] = []
    current: _BlobGroup | None = None
    gap_after_current: tuple[int, int, int, int] | None = None

    for tag, old_start, old_end, new_start, new_end in opcodes:
        if tag == "equal":
            if current is not None:
                gap_after_current = (old_start, old_end, new_start, new_end)
            continue

        if current is None:
            current = _BlobGroup(old_start=old_start, old_end=old_end, new_start=new_start, new_end=new_end)
            gap_after_current = None
            continue

        if gap_after_current is not None:
            gap_old_start, gap_old_end, _, _ = gap_after_current
            gap_width = _display_width(_concat_token_text(old_tokens[gap_old_start:gap_old_end]))
            if gap_width <= settings.string_blob_merge_gap_columns:
                current = _BlobGroup(
                    old_start=current.old_start,
                    old_end=old_end,
                    new_start=current.new_start,
                    new_end=new_end,
                )
                gap_after_current = None
                continue

        groups.append(current)
        current = _BlobGroup(old_start=old_start, old_end=old_end, new_start=new_start, new_end=new_end)
        gap_after_current = None

    if current is not None:
        groups.append(current)

    return groups


def _merge_blob_groups_from_text_units(
    old_units: list[str],
    opcodes: list[tuple[str, int, int, int, int]],
    settings: DiffSettings,
) -> list[_BlobGroup]:
    groups: list[_BlobGroup] = []
    current: _BlobGroup | None = None
    gap_after_current: tuple[int, int, int, int] | None = None

    for tag, old_start, old_end, new_start, new_end in opcodes:
        if tag == "equal":
            if current is not None:
                gap_after_current = (old_start, old_end, new_start, new_end)
            continue

        if current is None:
            current = _BlobGroup(old_start=old_start, old_end=old_end, new_start=new_start, new_end=new_end)
            gap_after_current = None
            continue

        if gap_after_current is not None:
            gap_old_start, gap_old_end, _, _ = gap_after_current
            gap_width = _display_width("".join(old_units[gap_old_start:gap_old_end]))
            if gap_width <= settings.string_blob_merge_gap_columns:
                current = _BlobGroup(
                    old_start=current.old_start,
                    old_end=old_end,
                    new_start=current.new_start,
                    new_end=new_end,
                )
                gap_after_current = None
                continue

        groups.append(current)
        current = _BlobGroup(old_start=old_start, old_end=old_end, new_start=new_start, new_end=new_end)
        gap_after_current = None

    if current is not None:
        groups.append(current)

    return groups


def _surround_with_plain_text(
    prefix_text: str,
    middle_spans: list[StringSpan],
    suffix_text: str,
) -> list[StringSpan]:
    spans: list[StringSpan] = []
    if prefix_text:
        spans.append(StringSpan(role="plain", text=prefix_text))
    spans.extend(middle_spans)
    if suffix_text:
        spans.append(StringSpan(role="plain", text=suffix_text))
    return spans


def _context_line(
    line_text: str,
    old_line_no: int | None,
    new_line_no: int | None,
) -> StringLine:
    return StringLine(
        kind="context",
        spans=[StringSpan(role="plain", text=line_text)],
        text=line_text,
        old_line_no=old_line_no,
        new_line_no=new_line_no,
    )


def _token_signature(tokens: list[StringToken]) -> list[tuple[str, str]]:
    return [(token.kind.value, token.text) for token in tokens]


def _concat_token_text(tokens: list[StringToken]) -> str:
    return "".join(token.text for token in tokens)


def _combine_adjacent_spans(spans: list[StringSpan]) -> list[StringSpan]:
    merged: list[StringSpan] = []
    for span in spans:
        if not span.text:
            continue
        if merged and merged[-1].role == span.role:
            previous = merged[-1]
            merged[-1] = StringSpan(role=span.role, text=previous.text + span.text)
            continue
        merged.append(span)
    return merged


def _shared_affix_len(old_graphemes: list[str], new_graphemes: list[str]) -> int:
    prefix = 0
    while (
        prefix < len(old_graphemes)
        and prefix < len(new_graphemes)
        and old_graphemes[prefix] == new_graphemes[prefix]
    ):
        prefix += 1

    suffix = 0
    old_limit = len(old_graphemes) - prefix
    new_limit = len(new_graphemes) - prefix
    while (
        suffix < old_limit
        and suffix < new_limit
        and old_graphemes[len(old_graphemes) - suffix - 1] == new_graphemes[len(new_graphemes) - suffix - 1]
    ):
        suffix += 1

    return prefix + suffix


def _is_blob_candidate(text: str, settings: DiffSettings) -> bool:
    text_len = len(text)
    if text_len >= settings.string_blob_min_chars:
        return True

    whitespace_count = sum(1 for ch in text if ch.isspace())
    separator_count = sum(1 for ch in text if ch in _BLOB_SEPARATORS)
    if (
        text_len >= settings.string_blob_dense_line_chars
        and whitespace_count <= text_len // 20
        and separator_count >= 3
    ):
        return True

    return _longest_non_whitespace_run(text) >= settings.string_blob_opaque_token_chars


def _longest_non_whitespace_run(text: str) -> int:
    best = 0
    current = 0
    for char in text:
        if char.isspace():
            best = max(best, current)
            current = 0
            continue
        current += 1
    return max(best, current)


def _take_left_columns(text: str, max_columns: int | None) -> str:
    if max_columns is None:
        return text
    if max_columns <= 0 or not text:
        return ""

    graphemes = split_graphemes(text)
    chosen: list[str] = []
    used = 0
    for grapheme in graphemes:
        width = _display_width(grapheme)
        if chosen and used + width > max_columns:
            break
        chosen.append(grapheme)
        used += width
        if used >= max_columns:
            break
    return "".join(chosen)


def _take_right_columns(text: str, max_columns: int | None) -> str:
    if max_columns is None:
        return text
    if max_columns <= 0 or not text:
        return ""

    graphemes = split_graphemes(text)
    chosen: list[str] = []
    used = 0
    for grapheme in reversed(graphemes):
        width = _display_width(grapheme)
        if chosen and used + width > max_columns:
            break
        chosen.append(grapheme)
        used += width
        if used >= max_columns:
            break
    return "".join(reversed(chosen))


def _display_width(text: str) -> int:
    width = wcswidth(text)
    if width >= 0:
        return width
    return len(split_graphemes(text))
