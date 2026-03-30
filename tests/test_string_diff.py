from __future__ import annotations

from jdv.model import DiffSettings, StringMode, StringTokenKind
from jdv.string_diff import build_string_detail, classify_string_mode, split_graphemes, tokenize_string


def test_word_level_replace_prefers_whole_token_chunks() -> None:
    detail = build_string_detail("silver tier", "gold tier", DiffSettings())

    assert detail.mode is StringMode.INLINE_TOKEN
    assert _span_signature(detail.inline_spans) == [
        ("removed", "silver"),
        ("added", "gold"),
        ("plain", " tier"),
    ]


def test_microdiff_requires_shared_affixes_and_token_size_guard() -> None:
    detail = build_string_detail("candidate", "canrevate", DiffSettings())
    assert _span_signature(detail.inline_spans) == [
        ("plain", "can"),
        ("removed", "did"),
        ("added", "rev"),
        ("plain", "ate"),
    ]

    whole_token = build_string_detail("silver", "gold", DiffSettings())
    assert _span_signature(whole_token.inline_spans) == [
        ("removed", "silver"),
        ("added", "gold"),
    ]

    oversized = build_string_detail("a" * 65, "b" * 65, DiffSettings())
    assert _span_signature(oversized.inline_spans) == [
        ("removed", "a" * 65),
        ("added", "b" * 65),
    ]


def test_multiline_strings_render_logical_lines() -> None:
    detail = build_string_detail("line1\nline2", "line1\nlineX", DiffSettings())

    assert detail.mode is StringMode.MULTILINE_BLOCK
    assert len(detail.multiline_hunks) == 1
    hunk = detail.multiline_hunks[0]
    assert [line.text for line in hunk.prefix_context] == ["line1"]
    assert _span_signature(hunk.body[0].spans) == [("plain", "line"), ("removed", "2")]
    assert _span_signature(hunk.body[1].spans) == [("plain", "line"), ("added", "X")]


def test_multiline_header_reports_line_counts_and_trailing_newline() -> None:
    detail = build_string_detail("a\nb\n", "a\nb\nc", DiffSettings())

    assert detail.mode is StringMode.MULTILINE_BLOCK
    assert detail.old_line_count == 2
    assert detail.new_line_count == 3
    assert detail.trailing_newline_changed is True


def test_blob_classifier_promotes_dense_long_single_lines() -> None:
    old_text = "segment=" + ("a" * 70) + "&query=" + ("b" * 70) + ":token=" + ("c" * 40)
    new_text = old_text[:-5] + "delta"

    assert classify_string_mode(old_text, new_text, DiffSettings()) is StringMode.BLOB_SUMMARY


def test_blob_classifier_promotes_opaque_long_token_without_punctuation_density() -> None:
    old_text = "A" * 220
    new_text = "B" * 220

    assert classify_string_mode(old_text, new_text, DiffSettings()) is StringMode.BLOB_SUMMARY


def test_blob_classifier_promotes_asymmetric_opaque_long_token() -> None:
    old_text = "A" * 220
    new_text = ("word " * 45).rstrip()

    assert classify_string_mode(old_text, new_text, DiffSettings()) is StringMode.BLOB_SUMMARY


def test_grapheme_clusters_are_not_split_by_microdiff() -> None:
    detail = build_string_detail("🙂é", "🙂x", DiffSettings())

    assert split_graphemes("🙂é") == ["🙂", "é"]
    assert _span_signature(detail.inline_spans) == [
        ("plain", "🙂"),
        ("removed", "é"),
        ("added", "x"),
    ]


def test_unicode_normalization_is_not_applied() -> None:
    detail = build_string_detail("café", "cafe\u0301", DiffSettings())

    assert any(span.role != "plain" for span in detail.inline_spans)


def test_tokenize_string_uses_expected_token_classes() -> None:
    tokens = tokenize_string("v2-alpha_01")

    assert [(token.kind, token.text) for token in tokens] == [
        (StringTokenKind.IDENT, "v2"),
        (StringTokenKind.PUNCT, "-"),
        (StringTokenKind.IDENT, "alpha"),
        (StringTokenKind.PUNCT, "_"),
        (StringTokenKind.NUMBER, "01"),
    ]


def test_multiline_pairing_does_not_recurse_on_large_replace_window() -> None:
    old_text = "\n".join(f"old-{index}" for index in range(600))
    new_text = "\n".join(f"new-{index}" for index in range(600))

    detail = build_string_detail(old_text, new_text, DiffSettings())

    assert detail.mode is StringMode.MULTILINE_BLOCK
    assert detail.multiline_hunks


def _span_signature(spans) -> list[tuple[str, str]]:
    return [(span.role, span.text) for span in spans]
