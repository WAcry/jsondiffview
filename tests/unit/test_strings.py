from __future__ import annotations

from dataclasses import replace
from itertools import combinations, pairwise, permutations

import pytest

from jsondiffview.model import View
from jsondiffview.strings import (
    BLOB_DENSE_CODE_POINT_LIMIT,
    BLOB_HARD_CODE_POINT_LIMIT,
    BLOB_MERGE_GAP_CELLS,
    BLOB_OPAQUE_RUN_LIMIT,
    FULL_EXCERPT_CELLS,
    REVIEW_EXCERPT_CELLS,
    SIMILARITY_LINE_CODE_POINT_LIMIT,
    SUMMARY_EXCERPT_CELLS,
    FallbackReason,
    FragmentKind,
    LineKind,
    LogicalLine,
    LongStringDiff,
    MultilineStringDiff,
    ProjectedLongStringDiff,
    ShortStringDiff,
    StringBudgets,
    StringMode,
    TokenKind,
    _line_similarity_score,
    _unique_line_anchors,
    bounded_excerpt,
    build_string_diff,
    classify_string_mode,
    display_width,
    project_string_diff,
    split_graphemes,
    tokenize_string,
)


def fragment_signature(
    result: ShortStringDiff,
) -> list[tuple[str, FragmentKind]]:
    return [(fragment.text, fragment.kind) for fragment in result.fragments]


def test_inline_uses_unicode_word_space_and_punctuation_segments() -> None:
    result = build_string_diff("Hello, world!", "Hello, team!")
    assert isinstance(result, ShortStringDiff)
    assert fragment_signature(result) == [
        ("Hello, ", FragmentKind.UNCHANGED),
        ("world", FragmentKind.REMOVED),
        ("team", FragmentKind.ADDED),
        ("!", FragmentKind.UNCHANGED),
    ]


def test_one_identifier_replacement_uses_grapheme_microdiff() -> None:
    result = build_string_diff("candidate", "canrevate")
    assert isinstance(result, ShortStringDiff)
    assert fragment_signature(result) == [
        ("can", FragmentKind.UNCHANGED),
        ("did", FragmentKind.REMOVED),
        ("rev", FragmentKind.ADDED),
        ("ate", FragmentKind.UNCHANGED),
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("e\u0301", ["e\u0301"]),
        ("👨\u200d👩\u200d👧\u200d👦", ["👨\u200d👩\u200d👧\u200d👦"]),
        ("👍🏽", ["👍🏽"]),
        ("🇨🇦", ["🇨🇦"]),
        ("1️⃣", ["1️⃣"]),
        ("\u1100\u1161", ["\u1100\u1161"]),
        ("क्\u200dष", ["क्\u200dष"]),
    ],
)
def test_uax29_grapheme_clusters_are_not_split(
    text: str,
    expected: list[str],
) -> None:
    assert [item.text for item in split_graphemes(text)] == expected


@pytest.mark.parametrize(
    "cluster",
    [
        "e\u0301",
        "👨\u200d👩\u200d👧\u200d👦",
        "👍🏽",
        "🇨🇦",
        "1️⃣",
        "\u1100\u1161",
        "क्\u200dष",
    ],
)
def test_token_boundaries_never_split_grapheme_clusters(cluster: str) -> None:
    text = "b" + cluster + "c"
    boundaries = {item.start for item in split_graphemes(text)} | {len(text)}
    tokens = tokenize_string(text)
    assert "".join(token.text for token in tokens) == text
    assert all(
        token.start in boundaries and token.end in boundaries for token in tokens
    )


def test_microdiff_never_detaches_combining_mark() -> None:
    result = build_string_diff("prefixe\u0301suffix", "prefixxsuffix")
    assert isinstance(result, ShortStringDiff)
    texts = [fragment.text for fragment in result.fragments]
    assert "\u0301" not in texts
    assert "e\u0301" in texts
    assert _reconstruct_old(result) == "prefixe\u0301suffix"
    assert _reconstruct_new(result) == "prefixxsuffix"


def test_unicode_normalization_is_not_applied() -> None:
    result = build_string_diff("café", "cafe\u0301")
    assert isinstance(result, ShortStringDiff)
    assert any(
        fragment.kind is not FragmentKind.UNCHANGED for fragment in result.fragments
    )


def test_tokenizer_covers_exact_text_with_expected_classes() -> None:
    tokens = tokenize_string("v2-alpha_01 🙂")
    assert [(token.kind, token.text) for token in tokens] == [
        (TokenKind.IDENT, "v2"),
        (TokenKind.PUNCT, "-"),
        (TokenKind.IDENT, "alpha"),
        (TokenKind.PUNCT, "_"),
        (TokenKind.NUMBER, "01"),
        (TokenKind.SPACE, " "),
        (TokenKind.OTHER, "🙂"),
    ]
    assert "".join(token.text for token in tokens) == "v2-alpha_01 🙂"


@pytest.mark.parametrize(
    ("length", "mode"),
    [
        (BLOB_HARD_CODE_POINT_LIMIT - 1, StringMode.INLINE),
        (BLOB_HARD_CODE_POINT_LIMIT, StringMode.BLOB),
        (BLOB_HARD_CODE_POINT_LIMIT + 1, StringMode.BLOB),
    ],
)
def test_hard_blob_classifier_boundaries(length: int, mode: StringMode) -> None:
    prose = ("a " * (length // 2 + 1))[:length]
    changed = prose[:-1] + ("x" if prose[-1:] != "x" else "y")
    assert classify_string_mode(prose, changed) is mode


@pytest.mark.parametrize(
    ("length", "mode"),
    [
        (BLOB_DENSE_CODE_POINT_LIMIT - 1, StringMode.INLINE),
        (BLOB_DENSE_CODE_POINT_LIMIT, StringMode.BLOB),
        (BLOB_DENSE_CODE_POINT_LIMIT + 1, StringMode.BLOB),
    ],
)
def test_dense_blob_classifier_boundaries(length: int, mode: StringMode) -> None:
    dense = (("a" * 35 + ":" + "b" * 3 + " ") * 5)[:length]
    assert classify_string_mode(dense, dense[:-1] + "x") is mode


@pytest.mark.parametrize(
    ("length", "mode"),
    [
        (BLOB_OPAQUE_RUN_LIMIT - 1, StringMode.INLINE),
        (BLOB_OPAQUE_RUN_LIMIT, StringMode.BLOB),
        (BLOB_OPAQUE_RUN_LIMIT + 1, StringMode.BLOB),
    ],
)
def test_opaque_blob_classifier_boundaries(length: int, mode: StringMode) -> None:
    old = "A" * length
    new = "B" * length
    assert classify_string_mode(old, new) is mode


def test_blob_classification_is_symmetric() -> None:
    opaque = "A" * BLOB_OPAQUE_RUN_LIMIT
    prose = "ordinary prose"
    assert classify_string_mode(opaque, prose) is StringMode.BLOB
    assert classify_string_mode(prose, opaque) is StringMode.BLOB


@pytest.mark.parametrize(
    ("unit_limit", "expected"),
    [(5, FallbackReason.INLINE_UNITS), (6, None), (7, None)],
)
def test_inline_unit_budget_boundaries(
    unit_limit: int,
    expected: FallbackReason | None,
) -> None:
    result = build_string_diff(
        "a b",
        "c d",
        budgets=replace(StringBudgets(), inline_units=unit_limit),
    )
    if expected is None:
        assert isinstance(result, ShortStringDiff)
    else:
        assert isinstance(result, LongStringDiff)
        assert result.fallback_reason is expected


@pytest.mark.parametrize(
    ("cell_limit", "fallback"),
    [(3, True), (4, False), (5, False)],
)
def test_inline_cell_budget_boundaries(
    cell_limit: int,
    fallback: bool,
) -> None:
    result = build_string_diff(
        "a ",
        "b ",
        budgets=replace(StringBudgets(), inline_cells=cell_limit),
    )
    assert isinstance(result, LongStringDiff) is fallback
    if fallback:
        assert result.fallback_reason is FallbackReason.INLINE_CELLS


def test_microdiff_size_and_product_budgets_decline_safely() -> None:
    old = "abcXdef"
    new = "abcYdef"
    detailed = build_string_diff(old, new)
    size_limited = build_string_diff(
        old,
        new,
        budgets=replace(StringBudgets(), micro_graphemes=6),
    )
    product_limited = build_string_diff(
        old,
        new,
        budgets=replace(StringBudgets(), micro_cells=48),
    )
    assert isinstance(detailed, ShortStringDiff)
    assert isinstance(size_limited, ShortStringDiff)
    assert isinstance(product_limited, ShortStringDiff)
    assert len(detailed.fragments) == 4
    assert fragment_signature(size_limited) == [
        (old, FragmentKind.REMOVED),
        (new, FragmentKind.ADDED),
    ]
    assert fragment_signature(product_limited) == fragment_signature(size_limited)


@pytest.mark.parametrize(
    ("old", "new", "detailed"),
    [
        ("aXb", "aYb", False),
        ("abXc", "abYc", True),
        ("abXcd", "abYcd", True),
    ],
)
def test_microdiff_shared_affix_threshold_boundaries(
    old: str,
    new: str,
    detailed: bool,
) -> None:
    result = build_string_diff(old, new)
    assert isinstance(result, ShortStringDiff)
    assert (len(result.fragments) == 4) is detailed


@pytest.mark.parametrize(
    ("grapheme_limit", "detailed"),
    [(6, False), (7, True), (8, True)],
)
def test_microdiff_grapheme_budget_boundaries(
    grapheme_limit: int,
    detailed: bool,
) -> None:
    result = build_string_diff(
        "abcXdef",
        "abcYdef",
        budgets=replace(StringBudgets(), micro_graphemes=grapheme_limit),
    )
    assert isinstance(result, ShortStringDiff)
    assert (len(result.fragments) == 4) is detailed


@pytest.mark.parametrize(
    ("cell_limit", "detailed"),
    [(48, False), (49, True), (50, True)],
)
def test_microdiff_cell_budget_boundaries(
    cell_limit: int,
    detailed: bool,
) -> None:
    result = build_string_diff(
        "abcXdef",
        "abcYdef",
        budgets=replace(StringBudgets(), micro_cells=cell_limit),
    )
    assert isinstance(result, ShortStringDiff)
    assert (len(result.fragments) == 4) is detailed


def test_multiline_retains_exact_bodies_terminators_and_final_state() -> None:
    result = build_string_diff("same\nold\r\nlast", "same\nnew\rlast\n")
    assert isinstance(result, MultilineStringDiff)
    assert result.old_line_count == result.new_line_count == 3
    changed = [
        row.text
        for row in result.rows
        if row.kind in {LineKind.REMOVED, LineKind.ADDED}
    ]
    assert "old\r\n" in changed
    assert "new\r" in changed
    assert "last" in changed
    assert "last\n" in changed


def test_similar_multiline_rows_pair_with_side_specific_intraline_spans() -> None:
    result = build_string_diff("line1\nline2", "line1\nlineX")
    assert isinstance(result, MultilineStringDiff)
    removed = next(row for row in result.rows if row.kind is LineKind.REMOVED)
    added = next(row for row in result.rows if row.kind is LineKind.ADDED)
    assert [(item.text, item.kind) for item in removed.fragments] == [
        ("line", FragmentKind.UNCHANGED),
        ("2", FragmentKind.REMOVED),
    ]
    assert [(item.text, item.kind) for item in added.fragments] == [
        ("line", FragmentKind.UNCHANGED),
        ("X", FragmentKind.ADDED),
    ]


@pytest.mark.parametrize(
    ("old", "new", "paired"),
    [
        ("same:old\n", "same/new\n", False),
        ("same:\n", "same/new\n", True),
        ("same:\n", "same/\n", True),
    ],
)
def test_similar_line_score_threshold_boundaries(
    old: str,
    new: str,
    paired: bool,
) -> None:
    result = build_string_diff(old, new)
    assert isinstance(result, MultilineStringDiff)
    assert any(row.fragments for row in result.rows) is paired


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("foo bar baz\n", "one two six\n"),
        ("aa:bb:cc\n", "xx:yy:zz\n"),
    ],
)
def test_similar_line_pairing_rejects_separator_only_overlap(
    old: str,
    new: str,
) -> None:
    result = build_string_diff(old, new)
    assert isinstance(result, MultilineStringDiff)
    assert all(not row.fragments for row in result.rows)


def test_patience_anchor_tie_prefers_the_earliest_new_line() -> None:
    old = (_logical_line("a\n"), _logical_line("b\n"))
    new = (_logical_line("b\n"), _logical_line("a\n"))
    assert _unique_line_anchors(old, new, 0, 2, 0, 2) == ((1, 0),)


def test_patience_anchor_backbone_matches_independent_small_reference() -> None:
    for size in range(1, 7):
        old = tuple(_logical_line(f"{index}\n") for index in range(size))
        for order in permutations(range(size)):
            new = tuple(_logical_line(f"{index}\n") for index in order)
            assert _unique_line_anchors(old, new, 0, size, 0, size) == (
                _reference_unique_line_anchors(old, new)
            )


@pytest.mark.parametrize(
    ("length", "expected_cost"),
    [(4_095, 1), (4_096, 1), (4_097, 0)],
)
def test_similarity_line_code_point_boundaries(
    length: int,
    expected_cost: int,
) -> None:
    old = _logical_line("a" * length)
    new = _logical_line("b" * length)
    _score, cost = _line_similarity_score(
        old,
        new,
        tokenize_string(old.body),
        tokenize_string(new.body),
    )
    assert cost == expected_cost


@pytest.mark.parametrize(
    ("units", "admitted"),
    [(511, True), (512, True), (513, False)],
)
def test_similarity_line_unit_boundaries(units: int, admitted: bool) -> None:
    old = _logical_line("🙂" * units)
    new = _logical_line("🙃" * units)
    _score, cost = _line_similarity_score(
        old,
        new,
        tokenize_string(old.body),
        tokenize_string(new.body),
    )
    assert (cost > 0) is admitted


def test_terminator_only_change_is_a_mandatory_pair_candidate() -> None:
    result = build_string_diff("same\n", "same\r\n")
    assert isinstance(result, MultilineStringDiff)
    changed = [
        row for row in result.rows if row.kind in {LineKind.REMOVED, LineKind.ADDED}
    ]
    assert len(changed) == 2
    assert all(row.fragments for row in changed)


def test_oversized_terminator_only_change_skips_similarity_tokenization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(_text: str) -> tuple[object, ...]:
        raise AssertionError("oversized mandatory pairs must not be tokenized")

    monkeypatch.setattr("jsondiffview.strings.tokenize_string", fail_if_called)
    body = "a" * (SIMILARITY_LINE_CODE_POINT_LIMIT + 1)
    result = build_string_diff(body + "\n", body + "\r\n")

    assert isinstance(result, MultilineStringDiff)
    changed = [
        row for row in result.rows if row.kind in {LineKind.REMOVED, LineKind.ADDED}
    ]
    assert len(changed) == 2
    assert all(row.fragments for row in changed)


def test_pairing_budget_falls_back_to_unpaired_rows() -> None:
    result = build_string_diff(
        "line2\n",
        "lineX\n",
        budgets=replace(StringBudgets(), similar_line_pair_cells=0),
    )
    assert isinstance(result, MultilineStringDiff)
    assert result.fallback_reason is FallbackReason.PAIRING_CELLS
    assert all(not row.fragments for row in result.rows)


@pytest.mark.parametrize(
    ("combined_lines", "fallback"),
    [(3, False), (4, False), (5, True)],
)
def test_multiline_line_budget_boundaries(
    combined_lines: int,
    fallback: bool,
) -> None:
    old_count = combined_lines // 2
    new_count = combined_lines - old_count
    old = "".join(f"old-{index}\n" for index in range(old_count))
    new = "".join(f"new-{index}\n" for index in range(new_count))
    result = build_string_diff(
        old,
        new,
        budgets=replace(StringBudgets(), multiline_lines=4),
    )
    assert isinstance(result, MultilineStringDiff)
    assert (result.fallback_reason is FallbackReason.MULTILINE_LINES) is fallback


@pytest.mark.parametrize(
    ("combined_code_points", "fallback"),
    [(19, False), (20, False), (21, True)],
)
def test_multiline_code_point_budget_boundaries(
    combined_code_points: int,
    fallback: bool,
) -> None:
    old_length = combined_code_points // 2
    new_length = combined_code_points - old_length
    old = "a" * (old_length - 1) + "\n"
    new = "b" * (new_length - 1) + "\n"
    result = build_string_diff(
        old,
        new,
        budgets=replace(StringBudgets(), multiline_code_points=20),
    )
    assert isinstance(result, MultilineStringDiff)
    assert (result.fallback_reason is FallbackReason.MULTILINE_CODE_POINTS) is fallback


def test_patience_work_and_small_gap_budgets_are_deterministic() -> None:
    patience = build_string_diff(
        "old\nanchor\n",
        "new\nanchor\n",
        budgets=replace(StringBudgets(), patience_line_visits=0),
    )
    gap = build_string_diff(
        "repeat\nold\n",
        "repeat\nnew\n",
        budgets=replace(StringBudgets(), small_gap_line_cells=0),
    )
    assert isinstance(patience, MultilineStringDiff)
    assert isinstance(gap, MultilineStringDiff)
    assert patience.fallback_reason is FallbackReason.PATIENCE_WORK
    assert gap.fallback_reason is FallbackReason.SMALL_GAP_CELLS


@pytest.mark.parametrize(
    ("visit_limit", "fallback"),
    [(1, True), (2, False), (3, False)],
)
def test_patience_visit_budget_boundaries(
    visit_limit: int,
    fallback: bool,
) -> None:
    result = build_string_diff(
        "old\n",
        "new\n",
        budgets=replace(StringBudgets(), patience_line_visits=visit_limit),
    )
    assert isinstance(result, MultilineStringDiff)
    assert (result.fallback_reason is FallbackReason.PATIENCE_WORK) is fallback


@pytest.mark.parametrize(
    ("cell_limit", "fallback"),
    [(0, True), (1, False), (2, False)],
)
def test_small_gap_cell_budget_boundaries(
    cell_limit: int,
    fallback: bool,
) -> None:
    result = build_string_diff(
        "old\n",
        "new\n",
        budgets=replace(StringBudgets(), small_gap_line_cells=cell_limit),
    )
    assert isinstance(result, MultilineStringDiff)
    assert (result.fallback_reason is FallbackReason.SMALL_GAP_CELLS) is fallback


@pytest.mark.parametrize(
    ("cell_limit", "paired"),
    [(0, False), (1, True), (2, True)],
)
def test_similar_line_pair_cell_budget_boundaries(
    cell_limit: int,
    paired: bool,
) -> None:
    result = build_string_diff(
        "line2\n",
        "lineX\n",
        budgets=replace(StringBudgets(), similar_line_pair_cells=cell_limit),
    )
    assert isinstance(result, MultilineStringDiff)
    assert any(row.fragments for row in result.rows) is paired


@pytest.mark.parametrize(
    ("cell_limit", "paired"),
    [(36, False), (37, True), (38, True)],
)
def test_similarity_matcher_cell_budget_boundaries(
    cell_limit: int,
    paired: bool,
) -> None:
    result = build_string_diff(
        "line2\n",
        "lineX\n",
        budgets=replace(StringBudgets(), similarity_matcher_cells=cell_limit),
    )
    assert isinstance(result, MultilineStringDiff)
    assert any(row.fragments for row in result.rows) is paired


def test_views_project_one_multiline_analysis_without_mutating_it() -> None:
    old = "a\nb\nc\nold\nd\ne\nf\n"
    new = "a\nb\nc\nnew\nd\ne\nf\n"
    analysis = build_string_diff(old, new)
    assert isinstance(analysis, MultilineStringDiff)
    original_rows = analysis.rows
    projected = {
        view: project_string_diff(analysis, view, lambda text: text) for view in View
    }
    assert analysis.rows == original_rows
    summary = projected[View.SUMMARY]
    review = projected[View.REVIEW]
    full = projected[View.FULL]
    assert isinstance(summary, MultilineStringDiff)
    assert isinstance(review, MultilineStringDiff)
    assert isinstance(full, MultilineStringDiff)
    assert sum(row.kind is LineKind.UNCHANGED for row in summary.rows) == 2
    assert sum(row.kind is LineKind.UNCHANGED for row in review.rows) == 4
    assert sum(row.kind is LineKind.UNCHANGED for row in full.rows) == 6


def test_inter_hunk_context_never_duplicates_overlapping_edges() -> None:
    analysis = build_string_diff(
        "old1\nkeep1\nkeep2\nkeep3\nold2\n",
        "new1\nkeep1\nkeep2\nkeep3\nnew2\n",
    )
    assert isinstance(analysis, MultilineStringDiff)
    review = project_string_diff(
        analysis,
        View.REVIEW,
        lambda text: text,
    )
    summary = project_string_diff(
        analysis,
        View.SUMMARY,
        lambda text: text,
    )
    assert isinstance(review, MultilineStringDiff)
    assert isinstance(summary, MultilineStringDiff)
    review_context = [row.text for row in review.rows if row.kind is LineKind.UNCHANGED]
    assert review_context == ["keep1\n", "keep2\n", "keep3\n"]
    summary_context = [
        row.text for row in summary.rows if row.kind is LineKind.UNCHANGED
    ]
    assert summary_context == ["keep1\n", "keep3\n"]


def test_multiline_row_and_cell_caps_use_coarse_first_last_previews() -> None:
    analysis = build_string_diff("a\nb\nc\n", "x\ny\nz\n")
    assert isinstance(analysis, MultilineStringDiff)
    row_limited = project_string_diff(
        analysis,
        View.FULL,
        lambda text: text,
        budgets=replace(StringBudgets(), detail_rows=2),
    )
    cell_limited = project_string_diff(
        analysis,
        View.FULL,
        lambda text: text,
        budgets=replace(StringBudgets(), detail_display_cells=2),
    )
    assert isinstance(row_limited, MultilineStringDiff)
    assert isinstance(cell_limited, MultilineStringDiff)
    assert row_limited.fallback_reason is FallbackReason.DETAIL_ROWS
    assert cell_limited.fallback_reason is FallbackReason.DETAIL_CELLS


@pytest.mark.parametrize("budget_name", ["detail_rows", "detail_display_cells"])
def test_multiline_cap_fallback_reclips_large_edge_previews(
    budget_name: str,
) -> None:
    old = "a" * 10_000 + "\nold-tail\n"
    new = "b" * 10_000 + "\nnew-tail\n"
    analysis = build_string_diff(old, new)
    assert isinstance(analysis, MultilineStringDiff)
    projected = project_string_diff(
        analysis,
        View.FULL,
        lambda text: text.replace("\n", "\\n"),
        budgets=replace(StringBudgets(), **{budget_name: 1}),
    )
    assert isinstance(projected, MultilineStringDiff)
    detail_rows = [
        row
        for row in projected.rows
        if row.kind
        not in {
            LineKind.OMITTED,
            LineKind.REMOVED_OMITTED,
            LineKind.ADDED_OMITTED,
        }
    ]
    assert any(row.omitted_code_points for row in detail_rows)
    assert all(
        display_width(row.text.replace("\n", "\\n")) <= FULL_EXCERPT_CELLS
        for row in detail_rows
    )


def test_preprocessing_fallback_preview_does_not_duplicate_short_edges() -> None:
    analysis = build_string_diff(
        "a\nb\nc\n",
        "x\ny\nz\n",
        budgets=replace(StringBudgets(), multiline_code_points=1),
    )
    assert isinstance(analysis, MultilineStringDiff)
    projected = project_string_diff(
        analysis,
        View.FULL,
        lambda text: text,
    )
    assert isinstance(projected, MultilineStringDiff)
    assert [row.text for row in projected.rows if row.text] == [
        "a\n",
        "b\n",
        "c\n",
        "x\n",
        "y\n",
        "z\n",
    ]


def test_coarse_multiline_preview_reports_exact_omitted_code_points() -> None:
    analysis = build_string_diff(
        "a\nbb\nccc\ndddd\neeeee\n",
        "x\nyy\nzzz\nwwww\nvvvvv\n",
        budgets=replace(StringBudgets(), multiline_code_points=1),
    )
    assert isinstance(analysis, MultilineStringDiff)
    projected = project_string_diff(
        analysis,
        View.FULL,
        lambda text: text,
    )
    assert isinstance(projected, MultilineStringDiff)

    removed = next(
        row for row in projected.rows if row.kind is LineKind.REMOVED_OMITTED
    )
    added = next(row for row in projected.rows if row.kind is LineKind.ADDED_OMITTED)
    assert (removed.count, removed.omitted_code_points) == (1, len("ccc\n"))
    assert (added.count, added.omitted_code_points) == (1, len("zzz\n"))


def test_display_width_uses_fixed_unicode_cells() -> None:
    assert display_width("abc") == 3
    assert display_width("界") == 2
    assert display_width("e\u0301") == 1
    assert display_width("·") == 1


def test_display_excerpt_is_grapheme_safe_and_width_bounded() -> None:
    text = "界" * 20 + "e\u0301" + "👨\u200d👩\u200d👧\u200d👦"
    excerpt = bounded_excerpt(text, 12, lambda value: value)
    assert excerpt.omitted > 0
    assert display_width(excerpt.text) <= 12
    assert "\u0301" not in {item.text for item in split_graphemes(excerpt.text)}


def test_bounded_excerpt_streams_edges_without_materializing_all_graphemes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(_text: str) -> tuple[object, ...]:
        raise AssertionError("bounded excerpts must stream grapheme edges")

    monkeypatch.setattr("jsondiffview.strings.split_graphemes", fail_if_called)
    excerpt = bounded_excerpt("A" * 10_000, 12, lambda value: value)

    assert excerpt.omitted == 9_989
    assert display_width(excerpt.text) <= 12


def test_blob_hunks_keep_exact_code_point_offsets_on_grapheme_boundaries() -> None:
    prefix = "word " * 110
    old = prefix + "👨\u200d👩\u200d👧\u200d👦" + " tail"
    new = prefix + "👨\u200d👩\u200d👧\u200d👦!" + " tail"
    result = build_string_diff(old, new)
    assert isinstance(result, LongStringDiff)
    hunk = result.hunks[0]
    assert old[hunk.old_start : hunk.old_end] == ""
    assert new[hunk.new_start : hunk.new_end] == "!"
    boundaries = {item.start for item in split_graphemes(new)} | {len(new)}
    assert hunk.new_start in boundaries
    assert hunk.new_end in boundaries


def test_blob_common_suffix_uses_forward_flag_boundaries() -> None:
    flag = "🇨🇦"
    old = "A" * 96 + flag * 3
    new = "B" * 96 + "--" + flag
    result = build_string_diff(old, new)
    assert isinstance(result, LongStringDiff)
    assert result.omitted_after == len(flag)
    assert result.hunks[-1].old_end == len(old) - len(flag)
    assert result.hunks[-1].new_end == len(new) - len(flag)


def test_blob_projection_uses_view_specific_display_widths() -> None:
    old = "A" * 200 + "OLD" + "B" * 200
    new = "A" * 200 + "NEW" + "B" * 200
    analysis = build_string_diff(old, new)
    assert isinstance(analysis, LongStringDiff)
    for view, width in [
        (View.SUMMARY, SUMMARY_EXCERPT_CELLS),
        (View.REVIEW, REVIEW_EXCERPT_CELLS),
        (View.FULL, FULL_EXCERPT_CELLS),
    ]:
        projected = project_string_diff(
            analysis,
            view,
            lambda text: text,
        )
        assert isinstance(projected, ProjectedLongStringDiff)
        assert display_width(projected.hunks[0].old_excerpt.text) <= width
        assert display_width(projected.hunks[0].new_excerpt.text) <= width


def test_blob_projection_context_partitions_stay_on_grapheme_boundaries() -> None:
    cluster = "e\u0301"
    old = "A" * 100 + "x" + cluster * 11 + "y" + "B" * 100
    new = "A" * 100 + "u" + cluster * 11 + "v" + "B" * 100
    analysis = build_string_diff(old, new)
    assert isinstance(analysis, LongStringDiff)
    assert len(analysis.hunks) == 2

    old_boundaries = {item.start for item in split_graphemes(old)} | {len(old)}
    new_boundaries = {item.start for item in split_graphemes(new)} | {len(new)}
    for view in View:
        projected = project_string_diff(analysis, view, lambda text: text)
        assert isinstance(projected, ProjectedLongStringDiff)
        for hunk in projected.hunks:
            assert hunk.old_excerpt.source_start in old_boundaries
            assert hunk.old_excerpt.source_end in old_boundaries
            assert hunk.new_excerpt.source_start in new_boundaries
            assert hunk.new_excerpt.source_end in new_boundaries


def test_blob_projection_streams_large_unchanged_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = "A" * 10_000 + "x" + "B" * 10_000
    new = "A" * 10_000 + "u" + "B" * 10_000
    analysis = build_string_diff(old, new)
    assert isinstance(analysis, LongStringDiff)

    def fail_if_called(_text: str) -> tuple[object, ...]:
        raise AssertionError("blob projection must stream context graphemes")

    monkeypatch.setattr("jsondiffview.strings.split_graphemes", fail_if_called)
    projected = project_string_diff(
        analysis,
        View.REVIEW,
        lambda value: value,
    )

    assert isinstance(projected, ProjectedLongStringDiff)
    assert display_width(projected.hunks[0].old_excerpt.text) <= REVIEW_EXCERPT_CELLS
    assert display_width(projected.hunks[0].new_excerpt.text) <= REVIEW_EXCERPT_CELLS


@pytest.mark.parametrize(
    ("limit", "fallback"),
    [(191, True), (192, False), (193, False)],
)
def test_blob_code_point_budget_boundaries(
    limit: int,
    fallback: bool,
) -> None:
    result = build_string_diff(
        "A" * 96,
        "B" * 96,
        budgets=replace(StringBudgets(), blob_interior_code_points=limit),
    )
    assert isinstance(result, LongStringDiff)
    assert (result.fallback_reason is FallbackReason.BLOB_CODE_POINTS) is fallback


@pytest.mark.parametrize(
    ("limit", "fallback"),
    [(191, True), (192, False), (193, False)],
)
def test_blob_unit_budget_boundaries(limit: int, fallback: bool) -> None:
    result = build_string_diff(
        "A" * 96,
        "B" * 96,
        budgets=replace(StringBudgets(), blob_units=limit),
    )
    assert isinstance(result, LongStringDiff)
    assert (result.fallback_reason is FallbackReason.BLOB_UNITS) is fallback


@pytest.mark.parametrize(
    ("limit", "fallback"),
    [(9_215, True), (9_216, False), (9_217, False)],
)
def test_blob_cell_budget_boundaries(limit: int, fallback: bool) -> None:
    result = build_string_diff(
        "A" * 96,
        "B" * 96,
        budgets=replace(StringBudgets(), blob_cells=limit),
    )
    assert isinstance(result, LongStringDiff)
    assert (result.fallback_reason is FallbackReason.BLOB_CELLS) is fallback


@pytest.mark.parametrize(
    ("limit", "fallback"),
    [(0, True), (1, False), (2, False)],
)
def test_blob_opcode_budget_boundaries(limit: int, fallback: bool) -> None:
    result = build_string_diff(
        "A" * 96,
        "B" * 96,
        budgets=replace(StringBudgets(), blob_opcodes=limit),
    )
    assert isinstance(result, LongStringDiff)
    assert (result.fallback_reason is FallbackReason.BLOB_OPCODES) is fallback


@pytest.mark.parametrize(
    ("limit", "fallback"),
    [(1, True), (2, False), (3, False)],
)
def test_blob_hunk_budget_boundaries(limit: int, fallback: bool) -> None:
    old = "A" * 20 + "x" + "q" * 10 + "y" + "B" * 70
    new = "A" * 20 + "u" + "q" * 10 + "v" + "B" * 70
    result = build_string_diff(
        old,
        new,
        budgets=replace(StringBudgets(), blob_hunks=limit),
    )
    assert isinstance(result, LongStringDiff)
    assert (result.fallback_reason is FallbackReason.BLOB_HUNKS) is fallback


@pytest.mark.parametrize(
    ("gap_cells", "hunk_count"),
    [
        (BLOB_MERGE_GAP_CELLS - 1, 1),
        (BLOB_MERGE_GAP_CELLS, 1),
        (BLOB_MERGE_GAP_CELLS + 1, 2),
    ],
)
def test_blob_merge_gap_display_cell_boundaries(
    gap_cells: int,
    hunk_count: int,
) -> None:
    old = "A" * 100 + "x" + "q" * gap_cells + "y" + "B" * 100
    new = "A" * 100 + "u" + "q" * gap_cells + "v" + "B" * 100
    result = build_string_diff(old, new)
    assert isinstance(result, LongStringDiff)
    assert len(result.hunks) == hunk_count


@pytest.mark.parametrize(
    ("limit", "fallback"),
    [(5, True), (6, False), (7, False)],
)
def test_detail_row_budget_boundaries(limit: int, fallback: bool) -> None:
    analysis = build_string_diff("a\nb\nc\n", "x\ny\nz\n")
    assert isinstance(analysis, MultilineStringDiff)
    projected = project_string_diff(
        analysis,
        View.FULL,
        lambda text: text,
        budgets=replace(StringBudgets(), detail_rows=limit),
    )
    assert isinstance(projected, MultilineStringDiff)
    assert (projected.fallback_reason is FallbackReason.DETAIL_ROWS) is fallback


@pytest.mark.parametrize(
    ("limit", "fallback"),
    [(5, True), (6, False), (7, False)],
)
def test_detail_display_cell_budget_boundaries(
    limit: int,
    fallback: bool,
) -> None:
    analysis = build_string_diff("a\n", "b\n")
    assert isinstance(analysis, MultilineStringDiff)
    projected = project_string_diff(
        analysis,
        View.FULL,
        lambda text: text.replace("\n", "\\n"),
        budgets=replace(StringBudgets(), detail_display_cells=limit),
    )
    assert isinstance(projected, MultilineStringDiff)
    assert (projected.fallback_reason is FallbackReason.DETAIL_CELLS) is fallback


@pytest.mark.parametrize(
    ("budget_name", "reason"),
    [
        ("blob_interior_code_points", FallbackReason.BLOB_CODE_POINTS),
        ("blob_units", FallbackReason.BLOB_UNITS),
        ("blob_cells", FallbackReason.BLOB_CELLS),
        ("blob_opcodes", FallbackReason.BLOB_OPCODES),
        ("blob_hunks", FallbackReason.BLOB_HUNKS),
    ],
)
def test_blob_work_budgets_degrade_to_one_complete_hunk(
    budget_name: str,
    reason: FallbackReason,
) -> None:
    old = "A" * 20 + "x" + "q" * 10 + "y" + "B" * 70
    new = "A" * 20 + "u" + "q" * 10 + "v" + "B" * 70
    budgets = replace(StringBudgets(), **{budget_name: 1})
    result = build_string_diff(old, new, budgets=budgets)
    assert isinstance(result, LongStringDiff)
    assert result.fallback_reason is reason
    assert len(result.hunks) == 1
    hunk = result.hunks[0]
    assert hunk.old_start <= hunk.old_end <= len(old)
    assert hunk.new_start <= hunk.new_end <= len(new)


def _reconstruct_old(result: ShortStringDiff) -> str:
    return "".join(
        fragment.text
        for fragment in result.fragments
        if fragment.kind is not FragmentKind.ADDED
    )


def _reconstruct_new(result: ShortStringDiff) -> str:
    return "".join(
        fragment.text
        for fragment in result.fragments
        if fragment.kind is not FragmentKind.REMOVED
    )


def _logical_line(text: str) -> LogicalLine:
    terminator = "\n" if text.endswith("\n") else ""
    body = text[:-1] if terminator else text
    return LogicalLine(body, terminator, text, 0, len(text))


def _reference_unique_line_anchors(
    old: tuple[LogicalLine, ...],
    new: tuple[LogicalLine, ...],
) -> tuple[tuple[int, int], ...]:
    old_positions = {line.text: index for index, line in enumerate(old)}
    candidates = tuple(
        (old_positions[line.text], new_index)
        for new_index, line in enumerate(new)
        if line.text in old_positions
    )
    backbones = [
        tuple(candidates[index] for index in positions)
        for length in range(len(candidates) + 1)
        for positions in combinations(range(len(candidates)), length)
        if all(
            candidates[left][0] < candidates[right][0]
            for left, right in pairwise(positions)
        )
    ]
    return min(
        backbones,
        key=lambda pairs: (
            -len(pairs),
            tuple(new_index for _old_index, new_index in pairs),
            tuple(old_index for old_index, _new_index in pairs),
        ),
    )
