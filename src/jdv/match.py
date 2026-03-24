from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from .model import AlignmentBasis, DiffSettings, IdentityLabel, MoveBasis, SameItemBasis
from .paths import canonical_json, render_json_scalar


@dataclass(frozen=True)
class ItemMatch:
    old_index: int | None
    new_index: int | None
    same_item_basis: SameItemBasis
    alignment_basis: AlignmentBasis
    move_basis: MoveBasis
    identity_label: IdentityLabel | None = None


@dataclass(frozen=True)
class _Pair:
    old_index: int
    new_index: int
    same_item_basis: SameItemBasis
    alignment_basis: AlignmentBasis
    identity_label: IdentityLabel | None
    exact_token: str | None


def match_array_items(
    old_items: list[Any],
    new_items: list[Any],
    parent_path: tuple[str | int, ...],
    settings: DiffSettings,
) -> list[ItemMatch]:
    _ = parent_path

    unmatched_old = set(range(len(old_items)))
    unmatched_new = set(range(len(new_items)))
    pairs: list[_Pair] = []

    for key_index, key in enumerate(settings.match_keys):
        old_groups: dict[str, list[int]] = defaultdict(list)
        new_groups: dict[str, list[int]] = defaultdict(list)
        old_labels: dict[str, IdentityLabel] = {}

        for old_index in sorted(unmatched_old):
            item = old_items[old_index]
            if isinstance(item, dict) and key in item:
                token = canonical_json(item[key])
                old_groups[token].append(old_index)
                old_labels[token] = IdentityLabel(key, render_json_scalar(item[key]))

        for new_index in sorted(unmatched_new):
            item = new_items[new_index]
            if isinstance(item, dict) and key in item:
                token = canonical_json(item[key])
                new_groups[token].append(new_index)

        candidate_pairs: list[tuple[int, int, IdentityLabel]] = []
        for token in old_groups.keys() & new_groups.keys():
            if len(old_groups[token]) != 1 or len(new_groups[token]) != 1:
                continue

            old_index = old_groups[token][0]
            new_index = new_groups[token][0]
            if _has_higher_priority_conflict(
                old_items[old_index],
                new_items[new_index],
                settings.match_keys[:key_index],
            ):
                continue
            candidate_pairs.append((old_index, new_index, old_labels[token]))

        for old_index, new_index, label in sorted(candidate_pairs):
            if old_index not in unmatched_old or new_index not in unmatched_new:
                continue
            unmatched_old.remove(old_index)
            unmatched_new.remove(new_index)
            pairs.append(
                _Pair(
                    old_index=old_index,
                    new_index=new_index,
                    same_item_basis=SameItemBasis.IDENTITY_KEY,
                    alignment_basis=AlignmentBasis.IDENTITY_PASS,
                    identity_label=label,
                    exact_token=None,
                )
            )

    sequence_pairs = _match_exact_sequence(
        old_items,
        new_items,
        sorted(unmatched_old),
        sorted(unmatched_new),
    )
    for pair in sequence_pairs:
        unmatched_old.remove(pair.old_index)
        unmatched_new.remove(pair.new_index)
        pairs.append(pair)

    unique_pairs = _match_unique_exact_values(
        old_items,
        new_items,
        sorted(unmatched_old),
        sorted(unmatched_new),
    )
    for pair in unique_pairs:
        unmatched_old.remove(pair.old_index)
        unmatched_new.remove(pair.new_index)
        pairs.append(pair)

    unique_exact_tokens = _compute_exact_token_uniqueness(old_items, new_items)
    backbone_pairs = _select_backbone(sorted(pairs, key=lambda pair: (pair.old_index, pair.new_index)))
    backbone_keys = {(pair.old_index, pair.new_index) for pair in backbone_pairs}

    matches: list[ItemMatch] = []
    for pair in sorted(pairs, key=lambda item: (item.old_index, item.new_index)):
        move_basis = MoveBasis.NONE
        if (pair.old_index, pair.new_index) not in backbone_keys:
            if pair.same_item_basis is SameItemBasis.IDENTITY_KEY:
                move_basis = MoveBasis.IDENTITY_KEY
            elif pair.exact_token is not None and unique_exact_tokens[pair.exact_token]:
                move_basis = MoveBasis.EXACT_VALUE

        matches.append(
            ItemMatch(
                old_index=pair.old_index,
                new_index=pair.new_index,
                same_item_basis=pair.same_item_basis,
                alignment_basis=pair.alignment_basis,
                move_basis=move_basis,
                identity_label=pair.identity_label,
            )
        )

    for new_index in sorted(unmatched_new):
        matches.append(
            ItemMatch(
                old_index=None,
                new_index=new_index,
                same_item_basis=SameItemBasis.NONE,
                alignment_basis=AlignmentBasis.NONE,
                move_basis=MoveBasis.NONE,
                identity_label=None,
            )
        )

    for old_index in sorted(unmatched_old):
        matches.append(
            ItemMatch(
                old_index=old_index,
                new_index=None,
                same_item_basis=SameItemBasis.NONE,
                alignment_basis=AlignmentBasis.NONE,
                move_basis=MoveBasis.NONE,
                identity_label=None,
            )
        )

    return sorted(
        matches,
        key=lambda item: (
            item.new_index is None,
            item.new_index if item.new_index is not None else len(new_items),
            item.old_index if item.old_index is not None else len(old_items),
        ),
    )


def _has_higher_priority_conflict(old_item: Any, new_item: Any, higher_priority_keys: tuple[str, ...]) -> bool:
    if not isinstance(old_item, dict) or not isinstance(new_item, dict):
        return False

    for key in higher_priority_keys:
        if key in old_item and key in new_item and canonical_json(old_item[key]) != canonical_json(new_item[key]):
            return True
    return False


def _match_exact_sequence(
    old_items: list[Any],
    new_items: list[Any],
    old_indices: list[int],
    new_indices: list[int],
) -> list[_Pair]:
    old_tokens = [canonical_json(old_items[index]) for index in old_indices]
    new_tokens = [canonical_json(new_items[index]) for index in new_indices]
    old_count = len(old_tokens)
    new_count = len(new_tokens)
    dp = [[0] * (new_count + 1) for _ in range(old_count + 1)]

    for old_offset in range(old_count - 1, -1, -1):
        for new_offset in range(new_count - 1, -1, -1):
            if old_tokens[old_offset] == new_tokens[new_offset]:
                dp[old_offset][new_offset] = 1 + dp[old_offset + 1][new_offset + 1]
            else:
                dp[old_offset][new_offset] = max(
                    dp[old_offset + 1][new_offset],
                    dp[old_offset][new_offset + 1],
                )

    pairs: list[_Pair] = []
    old_offset = 0
    new_offset = 0
    while old_offset < old_count and new_offset < new_count:
        if old_tokens[old_offset] == new_tokens[new_offset]:
            token = old_tokens[old_offset]
            pairs.append(
                _Pair(
                    old_index=old_indices[old_offset],
                    new_index=new_indices[new_offset],
                    same_item_basis=SameItemBasis.EXACT_VALUE,
                    alignment_basis=AlignmentBasis.EXACT_SEQUENCE,
                    identity_label=None,
                    exact_token=token,
                )
            )
            old_offset += 1
            new_offset += 1
            continue

        advance_old = dp[old_offset + 1][new_offset]
        advance_new = dp[old_offset][new_offset + 1]
        if advance_new >= advance_old:
            new_offset += 1
        else:
            old_offset += 1

    return pairs


def _match_unique_exact_values(
    old_items: list[Any],
    new_items: list[Any],
    old_indices: list[int],
    new_indices: list[int],
) -> list[_Pair]:
    old_groups: dict[str, list[int]] = defaultdict(list)
    new_groups: dict[str, list[int]] = defaultdict(list)

    for old_index in old_indices:
        old_groups[canonical_json(old_items[old_index])].append(old_index)
    for new_index in new_indices:
        new_groups[canonical_json(new_items[new_index])].append(new_index)

    pairs: list[_Pair] = []
    common_tokens = sorted(
        old_groups.keys() & new_groups.keys(),
        key=lambda token: (old_groups[token][0], new_groups[token][0]),
    )
    for token in common_tokens:
        if len(old_groups[token]) != 1 or len(new_groups[token]) != 1:
            continue
        pairs.append(
            _Pair(
                old_index=old_groups[token][0],
                new_index=new_groups[token][0],
                same_item_basis=SameItemBasis.EXACT_VALUE,
                alignment_basis=AlignmentBasis.EXACT_UNIQUE,
                identity_label=None,
                exact_token=token,
            )
        )
    return pairs


def _compute_exact_token_uniqueness(old_items: list[Any], new_items: list[Any]) -> dict[str, bool]:
    old_counter = Counter(canonical_json(item) for item in old_items)
    new_counter = Counter(canonical_json(item) for item in new_items)
    result: dict[str, bool] = {}
    for token in old_counter.keys() | new_counter.keys():
        result[token] = old_counter[token] == 1 and new_counter[token] == 1
    return result


def _select_backbone(pairs: list[_Pair]) -> list[_Pair]:
    if not pairs:
        return []

    best_sequences: list[list[int]] = [[] for _ in pairs]
    for index, pair in enumerate(pairs):
        best_sequences[index] = [index]
        for previous_index, previous_pair in enumerate(pairs[:index]):
            if previous_pair.new_index >= pair.new_index:
                continue
            candidate = best_sequences[previous_index] + [index]
            if _is_better_sequence(candidate, best_sequences[index], pairs):
                best_sequences[index] = candidate

    best_overall: list[int] = []
    for candidate in best_sequences:
        if _is_better_sequence(candidate, best_overall, pairs):
            best_overall = candidate

    return [pairs[index] for index in best_overall]


def _is_better_sequence(candidate: list[int], current: list[int], pairs: list[_Pair]) -> bool:
    if not current:
        return True
    if len(candidate) != len(current):
        return len(candidate) > len(current)

    candidate_new = [pairs[index].new_index for index in candidate]
    current_new = [pairs[index].new_index for index in current]
    if candidate_new != current_new:
        return candidate_new < current_new

    candidate_old = [pairs[index].old_index for index in candidate]
    current_old = [pairs[index].old_index for index in current]
    return candidate_old < current_old
