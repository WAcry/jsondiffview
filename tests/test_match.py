from __future__ import annotations

from jdv.match import match_array_items
from jdv.model import AlignmentBasis, DiffSettings, MoveBasis, SameItemBasis


def test_lower_priority_key_cannot_override_higher_priority_conflict() -> None:
    matches = match_array_items(
        old_items=[{"id": 1, "name": "checkout"}],
        new_items=[{"id": 2, "name": "checkout"}],
        parent_path=("items",),
        settings=DiffSettings(),
    )

    assert [match.same_item_basis for match in matches] == [SameItemBasis.NONE, SameItemBasis.NONE]


def test_duplicate_name_can_fall_back_to_unique_title() -> None:
    matches = match_array_items(
        old_items=[{"name": "A", "title": "1"}, {"name": "A", "title": "2"}],
        new_items=[{"name": "A", "title": "2"}, {"name": "A", "title": "3"}],
        parent_path=("items",),
        settings=DiffSettings(),
    )

    paired = [match for match in matches if match.old_index is not None and match.new_index is not None]
    assert len(paired) == 1
    assert paired[0].same_item_basis is SameItemBasis.IDENTITY_KEY
    assert paired[0].identity_label is not None
    assert paired[0].identity_label.field_name == "title"


def test_no_positional_pairing_for_anonymous_modified_objects() -> None:
    matches = match_array_items(
        old_items=[{"x": 1}],
        new_items=[{"x": 2}],
        parent_path=("items",),
        settings=DiffSettings(),
    )

    assert all(match.same_item_basis is SameItemBasis.NONE for match in matches)


def test_unique_exact_value_can_move() -> None:
    matches = match_array_items(
        old_items=[{"x": 1}, {"y": 2}],
        new_items=[{"y": 2}, {"x": 1}],
        parent_path=("items",),
        settings=DiffSettings(),
    )

    moved = [match for match in matches if match.move_basis is MoveBasis.EXACT_VALUE]
    assert len(moved) == 1
    assert moved[0].same_item_basis is SameItemBasis.EXACT_VALUE


def test_backbone_suppresses_rotation_noise() -> None:
    matches = match_array_items(
        old_items=[1, 2, 3, 4, 5],
        new_items=[2, 3, 4, 5, 1],
        parent_path=("items",),
        settings=DiffSettings(),
    )

    assert sum(match.move_basis is not MoveBasis.NONE for match in matches) == 1


def test_backbone_lis_tie_break_is_stable() -> None:
    matches = match_array_items(
        old_items=["A", "B"],
        new_items=["B", "A"],
        parent_path=("items",),
        settings=DiffSettings(),
    )

    moved = [match for match in matches if match.move_basis is MoveBasis.EXACT_VALUE]
    assert len(moved) == 1
    assert moved[0].old_index == 0
    assert moved[0].new_index == 1


def test_duplicate_exact_values_do_not_emit_arbitrary_move_provenance() -> None:
    matches = match_array_items(
        old_items=[{"x": 1}, {"x": 1}, {"y": 2}],
        new_items=[{"x": 1}, {"y": 2}, {"x": 1}],
        parent_path=("items",),
        settings=DiffSettings(),
    )

    exact_sequence = [match for match in matches if match.alignment_basis is AlignmentBasis.EXACT_SEQUENCE]
    assert exact_sequence
    assert all(match.move_basis is MoveBasis.NONE for match in exact_sequence if match.new_index != 1)
