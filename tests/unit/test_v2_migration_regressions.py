"""Behavioral fixtures ported from v2 without retaining v2 output snapshots."""

from __future__ import annotations

from jsondiffview.diff import build_diff
from jsondiffview.model import AlignmentBasis, JsonValue
from jsondiffview.parser import decode_json_bytes
from jsondiffview.strings import (
    FragmentKind,
    LineKind,
    LongStringDiff,
    MultilineStringDiff,
    ShortStringDiff,
    build_string_diff,
    display_width,
    split_graphemes,
)


def parse(text: str) -> JsonValue:
    return decode_json_bytes(text.encode(), "v2-regression.json")


def test_ported_identity_conflict_fixture_remains_unmatched() -> None:
    node = build_diff(
        parse('[{"id":1,"name":"checkout"}]'),
        parse('[{"id":2,"name":"checkout"}]'),
    )
    assert all(entry.evidence is None for entry in node.array_entries)


def test_ported_duplicate_fixture_aligns_without_move_provenance() -> None:
    node = build_diff(
        parse('[{"x":1},{"x":1},{"y":2}]'),
        parse('[{"x":1},{"y":2},{"x":1}]'),
    )
    duplicates = [
        entry
        for entry in node.array_entries
        if entry.alignment_basis is AlignmentBasis.DUPLICATE_EXACT_SEQUENCE
    ]
    assert duplicates
    assert all(entry.evidence is None and not entry.moved for entry in duplicates)


def test_ported_grapheme_microdiff_fixture_gains_safe_detail() -> None:
    result = build_string_diff("🙂e\u0301", "🙂x")
    assert isinstance(result, ShortStringDiff)
    assert [item.text for item in split_graphemes("🙂e\u0301")] == ["🙂", "e\u0301"]
    assert [(fragment.text, fragment.kind) for fragment in result.fragments] == [
        ("🙂", FragmentKind.UNCHANGED),
        ("e\u0301", FragmentKind.REMOVED),
        ("x", FragmentKind.ADDED),
    ]


def test_ported_multiline_pair_fixture_gains_intraline_spans() -> None:
    result = build_string_diff("line1\nline2", "line1\nlineX")
    assert isinstance(result, MultilineStringDiff)
    changed = [
        row for row in result.rows if row.kind in {LineKind.REMOVED, LineKind.ADDED}
    ]
    assert len(changed) == 2
    assert all(row.fragments for row in changed)


def test_ported_opaque_and_display_width_fixtures_are_bounded() -> None:
    result = build_string_diff("A" * 220, "B" * 220)
    assert isinstance(result, LongStringDiff)
    assert display_width("界e\u0301") == 3
