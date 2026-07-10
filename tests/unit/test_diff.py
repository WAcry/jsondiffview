from __future__ import annotations

import pytest

from jsondiffview.diff import build_diff
from jsondiffview.model import AlignmentBasis, DiffStatus, JsonValue, MatchKind
from jsondiffview.parser import decode_json_bytes


def parse(text: str) -> JsonValue:
    return decode_json_bytes(text.encode(), "fixture.json")


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("null", "true"),
        ("false", "true"),
        ("1", "2"),
        ("1.0", "2.0"),
        ('"old"', '"new"'),
        ("[]", "[1]"),
        ("{}", '{"key":1}'),
    ],
)
def test_every_root_value_kind_can_change(old: str, new: str) -> None:
    node = build_diff(parse(old), parse(new))
    assert node.status is DiffStatus.MODIFIED
    assert node.old_path == ()
    assert node.new_path == ()


def test_object_reordering_is_unchanged() -> None:
    node = build_diff(parse('{"a":1,"b":2}'), parse('{"b":2,"a":1}'))
    assert node.status is DiffStatus.UNCHANGED


def test_object_removal_is_anchored_before_old_following_survivor() -> None:
    node = build_diff(
        parse('{"a":1,"gone":2,"b":3,"tail":4}'),
        parse('{"b":3,"a":1}'),
    )
    assert [(member.key, member.node.status) for member in node.object_members] == [
        ("gone", DiffStatus.REMOVED),
        ("b", DiffStatus.UNCHANGED),
        ("a", DiffStatus.UNCHANGED),
        ("tail", DiffStatus.REMOVED),
    ]


def test_unique_identity_match_retains_paths_and_nested_change() -> None:
    node = build_diff(
        parse('[{"id":"a","value":1}]'),
        parse('[{"id":"a","value":2}]'),
    )
    entry = node.array_entries[0]
    assert entry.evidence is not None
    assert entry.evidence.kind is MatchKind.IDENTITY
    assert entry.evidence.key == "id"
    assert entry.node.status is DiffStatus.MODIFIED
    assert entry.node.old_path == (0,)
    assert entry.node.new_path == (0,)
    assert entry.node.object_members[1].node.status is DiffStatus.MODIFIED


def test_custom_match_key_replaces_default_identity_keys() -> None:
    old = parse('[{"id":"old","sku":"x","value":1}]')
    new = parse('[{"id":"new","sku":"x","value":2}]')

    default_node = build_diff(old, new)
    assert [entry.node.status for entry in default_node.array_entries] == [
        DiffStatus.ADDED,
        DiffStatus.REMOVED,
    ]

    custom_node = build_diff(old, new, ("sku",))
    assert len(custom_node.array_entries) == 1
    assert custom_node.array_entries[0].evidence is not None
    assert custom_node.array_entries[0].evidence.key == "sku"


def test_earlier_match_key_has_priority() -> None:
    node = build_diff(
        parse('[{"id":"one","key":"shared","v":1},{"id":"two","key":"other","v":1}]'),
        parse('[{"id":"two","key":"shared","v":2},{"id":"one","key":"other","v":2}]'),
        ("id", "key"),
    )
    assert [entry.evidence.key for entry in node.array_entries if entry.evidence] == [
        "id",
        "id",
    ]


def test_unique_exact_values_pair_without_identity() -> None:
    node = build_diff(parse('["a","b"]'), parse('["b","a"]'))
    assert all(
        entry.evidence is not None and entry.evidence.kind is MatchKind.EXACT
        for entry in node.array_entries
    )


def test_insertion_shift_does_not_report_moves() -> None:
    node = build_diff(
        parse('[{"id":"a"},{"id":"b"}]'),
        parse('[{"id":"new"},{"id":"a"},{"id":"b"}]'),
    )
    matched = [entry for entry in node.array_entries if entry.evidence is not None]
    assert [entry.moved for entry in matched] == [False, False]


def test_relative_reorder_reports_minimal_deterministic_move() -> None:
    node = build_diff(
        parse('[{"id":"a"},{"id":"b"},{"id":"c"}]'),
        parse('[{"id":"b"},{"id":"a"},{"id":"c"}]'),
    )
    by_new = {entry.new_index: entry for entry in node.array_entries}
    assert by_new[0].moved is True
    assert by_new[1].moved is False
    assert by_new[2].moved is False


def test_moved_item_keeps_nested_modification() -> None:
    node = build_diff(
        parse('[{"id":"a","v":1},{"id":"b","v":1}]'),
        parse('[{"id":"b","v":2},{"id":"a","v":1}]'),
    )
    moved = node.array_entries[0]
    assert moved.moved is True
    assert moved.node.status is DiffStatus.MODIFIED
    assert moved.node.old_path == (1,)
    assert moved.node.new_path == (0,)


def test_duplicate_identities_remain_remove_plus_add() -> None:
    node = build_diff(
        parse('[{"id":"x","v":1},{"id":"x","v":2}]'),
        parse('[{"id":"x","v":3},{"id":"x","v":4}]'),
    )
    assert [entry.node.status for entry in node.array_entries] == [
        DiffStatus.ADDED,
        DiffStatus.ADDED,
        DiffStatus.REMOVED,
        DiffStatus.REMOVED,
    ]
    assert all(entry.evidence is None for entry in node.array_entries)


def test_duplicate_exact_values_align_in_sequence_without_move_evidence() -> None:
    node = build_diff(parse('["same","same",0]'), parse('["same","same",1]'))
    assert [entry.node.status for entry in node.array_entries] == [
        DiffStatus.UNCHANGED,
        DiffStatus.UNCHANGED,
        DiffStatus.ADDED,
        DiffStatus.REMOVED,
    ]
    aligned = node.array_entries[:2]
    assert all(
        entry.alignment_basis is AlignmentBasis.DUPLICATE_EXACT_SEQUENCE
        for entry in aligned
    )
    assert all(entry.evidence is None and not entry.moved for entry in aligned)


def test_array_removal_is_anchored_before_following_match() -> None:
    node = build_diff(parse('["a","gone","b","tail"]'), parse('["b","a"]'))
    assert [
        (entry.old_index, entry.new_index, entry.node.status)
        for entry in node.array_entries
    ] == [
        (1, None, DiffStatus.REMOVED),
        (2, 0, DiffStatus.UNCHANGED),
        (0, 1, DiffStatus.UNCHANGED),
        (3, None, DiffStatus.REMOVED),
    ]
