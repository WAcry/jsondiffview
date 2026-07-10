"""Conservative, deterministically bounded array pairing."""

from __future__ import annotations

from array import array
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from .model import (
    AlignmentBasis,
    JsonNumber,
    JsonValue,
    MatchEvidence,
    MatchKind,
)
from .parser import Fingerprint, canonical_fingerprint

SPARSE_PAIR_BUDGET = 2_000_000
MYERS_FRONTIER_STATE_BUDGET = 2_000_000
MYERS_EQUALITY_BUDGET = 8_000_000
FALLBACK_RUN_PAIR_BUDGET = 250_000
FALLBACK_TOKEN_PRODUCT_LIMIT = 64


@dataclass(frozen=True, slots=True)
class MatchingBudgets:
    """Deterministic work limits for duplicate exact-value alignment."""

    sparse_pairs: int = SPARSE_PAIR_BUDGET
    myers_frontier_states: int = MYERS_FRONTIER_STATE_BUDGET
    myers_equalities: int = MYERS_EQUALITY_BUDGET
    fallback_run_pairs: int = FALLBACK_RUN_PAIR_BUDGET
    fallback_token_product: int = FALLBACK_TOKEN_PRODUCT_LIMIT


DEFAULT_MATCHING_BUDGETS = MatchingBudgets()


class AlignmentStrategy(StrEnum):
    """The exact or conservative path used for duplicate alignment."""

    NONE = "none"
    SPARSE_EXACT = "sparse_exact"
    DENSE_EXACT = "dense_exact"
    RUN_FALLBACK = "run_fallback"
    PREFIX_SUFFIX_FALLBACK = "prefix_suffix_fallback"


@dataclass(frozen=True, slots=True)
class MatchStats:
    """Stable matcher counters exposed only to focused tests and benchmarks."""

    strategy: AlignmentStrategy = AlignmentStrategy.NONE
    sparse_candidate_pairs: int = 0
    myers_frontier_states: int = 0
    myers_equality_comparisons: int = 0
    fallback_run_pairs: int = 0
    exhausted: bool = False


@dataclass(frozen=True, slots=True)
class ArrayMatch:
    """A one-to-one array pair with alignment and trusted move evidence."""

    old_index: int
    new_index: int
    alignment_basis: AlignmentBasis
    evidence: MatchEvidence | None
    moved: bool = False


@dataclass(frozen=True, slots=True)
class _AlignmentResult:
    pairs: tuple[tuple[int, int], ...]
    stats: MatchStats


@dataclass(frozen=True, slots=True)
class _DenseResult:
    pairs: tuple[tuple[int, int], ...] | None
    frontier_states: int
    equality_comparisons: int


@dataclass(frozen=True, slots=True)
class _Run:
    token: Fingerprint
    start: int
    length: int


def match_array(
    old: list[JsonValue],
    new: list[JsonValue],
    match_keys: tuple[str, ...],
) -> tuple[ArrayMatch, ...]:
    """Pair entries conservatively and classify minimal trusted moves."""

    matches, _ = match_array_with_stats(old, new, match_keys)
    return matches


def match_array_with_stats(
    old: list[JsonValue],
    new: list[JsonValue],
    match_keys: tuple[str, ...],
    *,
    budgets: MatchingBudgets = DEFAULT_MATCHING_BUDGETS,
) -> tuple[tuple[ArrayMatch, ...], MatchStats]:
    """Run the matcher while returning deterministic work observations."""

    old_fingerprints = [canonical_fingerprint(item) for item in old]
    new_fingerprints = [canonical_fingerprint(item) for item in new]
    old_global_counts = Counter(old_fingerprints)
    new_global_counts = Counter(new_fingerprints)
    unmatched_old = [True] * len(old)
    unmatched_new = [True] * len(new)
    matches: list[ArrayMatch] = []

    for key_index, key in enumerate(match_keys):
        old_groups = _index_identity(old, unmatched_old, key)
        new_groups = _index_identity(new, unmatched_new, key)
        candidates: list[tuple[int, int]] = []
        for old_index in range(len(old)):
            if not unmatched_old[old_index]:
                continue
            fingerprint = _identity_fingerprint(old[old_index], key)
            if fingerprint is None:
                continue
            old_indexes = old_groups.get(fingerprint, ())
            new_indexes = new_groups.get(fingerprint, ())
            if len(old_indexes) != 1 or len(new_indexes) != 1:
                continue
            new_index = new_indexes[0]
            if _has_higher_priority_conflict(
                old[old_index],
                new[new_index],
                match_keys[:key_index],
            ):
                continue
            candidates.append((old_index, new_index))

        for old_index, new_index in sorted(candidates):
            if not unmatched_old[old_index] or not unmatched_new[new_index]:
                continue
            old_object = old[old_index]
            if not isinstance(old_object, dict):
                continue
            matches.append(
                ArrayMatch(
                    old_index=old_index,
                    new_index=new_index,
                    alignment_basis=AlignmentBasis.IDENTITY,
                    evidence=MatchEvidence(
                        MatchKind.IDENTITY,
                        key=key,
                        key_value=old_object[key],
                    ),
                )
            )
            unmatched_old[old_index] = False
            unmatched_new[new_index] = False

    new_unmatched_by_value = _index_fingerprints(
        new_fingerprints,
        unmatched_new,
    )
    exact_candidates: list[tuple[int, int]] = []
    for old_index, fingerprint in enumerate(old_fingerprints):
        if not unmatched_old[old_index]:
            continue
        if old_global_counts[fingerprint] != 1 or new_global_counts[fingerprint] != 1:
            continue
        new_indexes = new_unmatched_by_value.get(fingerprint, ())
        if len(new_indexes) == 1:
            exact_candidates.append((old_index, new_indexes[0]))

    for old_index, new_index in exact_candidates:
        if not unmatched_old[old_index] or not unmatched_new[new_index]:
            continue
        matches.append(
            ArrayMatch(
                old_index=old_index,
                new_index=new_index,
                alignment_basis=AlignmentBasis.UNIQUE_EXACT,
                evidence=MatchEvidence(MatchKind.EXACT),
            )
        )
        unmatched_old[old_index] = False
        unmatched_new[new_index] = False

    remaining_old = [
        index for index, is_unmatched in enumerate(unmatched_old) if is_unmatched
    ]
    remaining_new = [
        index for index, is_unmatched in enumerate(unmatched_new) if is_unmatched
    ]
    duplicate_result = _align_duplicate_exact(
        remaining_old,
        remaining_new,
        old_fingerprints,
        new_fingerprints,
        budgets,
    )
    for old_index, new_index in duplicate_result.pairs:
        matches.append(
            ArrayMatch(
                old_index=old_index,
                new_index=new_index,
                alignment_basis=AlignmentBasis.DUPLICATE_EXACT_SEQUENCE,
                evidence=None,
            )
        )
        unmatched_old[old_index] = False
        unmatched_new[new_index] = False

    matches.sort(key=lambda match: match.new_index)
    stationary_positions = _stationary_positions(matches)
    classified = tuple(
        replace(
            match,
            moved=(position not in stationary_positions and match.evidence is not None),
        )
        for position, match in enumerate(matches)
    )
    return classified, duplicate_result.stats


def _is_identity_scalar(value: JsonValue) -> bool:
    return value is not None and isinstance(value, (bool, str, JsonNumber))


def _identity_fingerprint(value: JsonValue, key: str) -> Fingerprint | None:
    if not isinstance(value, dict) or key not in value:
        return None
    identity = value[key]
    if not _is_identity_scalar(identity):
        return None
    return canonical_fingerprint(identity)


def _index_identity(
    values: list[JsonValue],
    available: list[bool],
    key: str,
) -> dict[Fingerprint, list[int]]:
    result: dict[Fingerprint, list[int]] = {}
    for index, value in enumerate(values):
        if not available[index]:
            continue
        fingerprint = _identity_fingerprint(value, key)
        if fingerprint is not None:
            result.setdefault(fingerprint, []).append(index)
    return result


def _index_fingerprints(
    fingerprints: list[Fingerprint],
    available: list[bool],
) -> dict[Fingerprint, list[int]]:
    result: dict[Fingerprint, list[int]] = {}
    for index, fingerprint in enumerate(fingerprints):
        if available[index]:
            result.setdefault(fingerprint, []).append(index)
    return result


def _has_higher_priority_conflict(
    old_item: JsonValue,
    new_item: JsonValue,
    higher_priority_keys: tuple[str, ...],
) -> bool:
    if not isinstance(old_item, dict) or not isinstance(new_item, dict):
        return False
    for key in higher_priority_keys:
        old_fingerprint = _identity_fingerprint(old_item, key)
        new_fingerprint = _identity_fingerprint(new_item, key)
        if (
            old_fingerprint is not None
            and new_fingerprint is not None
            and old_fingerprint != new_fingerprint
        ):
            return True
    return False


def _align_duplicate_exact(
    old_indices: list[int],
    new_indices: list[int],
    old_fingerprints: list[Fingerprint],
    new_fingerprints: list[Fingerprint],
    budgets: MatchingBudgets,
) -> _AlignmentResult:
    old_tokens = [old_fingerprints[index] for index in old_indices]
    new_tokens = [new_fingerprints[index] for index in new_indices]

    prefix = 0
    common_limit = min(len(old_tokens), len(new_tokens))
    while prefix < common_limit and old_tokens[prefix] == new_tokens[prefix]:
        prefix += 1

    suffix = 0
    suffix_limit = common_limit - prefix
    while (
        suffix < suffix_limit
        and old_tokens[len(old_tokens) - 1 - suffix]
        == new_tokens[len(new_tokens) - 1 - suffix]
    ):
        suffix += 1

    pairs = [(old_indices[offset], new_indices[offset]) for offset in range(prefix)]
    old_end = len(old_tokens) - suffix if suffix else len(old_tokens)
    new_end = len(new_tokens) - suffix if suffix else len(new_tokens)
    interior_old = old_tokens[prefix:old_end]
    interior_new = new_tokens[prefix:new_end]

    if not interior_old or not interior_new:
        strategy = (
            AlignmentStrategy.PREFIX_SUFFIX_FALLBACK
            if pairs or suffix
            else AlignmentStrategy.NONE
        )
        stats = MatchStats(strategy=strategy)
    else:
        candidate_count = _candidate_pair_count(
            interior_old,
            interior_new,
            budgets.sparse_pairs,
        )
        if candidate_count <= budgets.sparse_pairs:
            interior_pairs = _sparse_lcs_pairs(interior_old, interior_new)
            pairs.extend(
                (old_indices[prefix + old_pos], new_indices[prefix + new_pos])
                for old_pos, new_pos in interior_pairs
            )
            stats = MatchStats(
                strategy=AlignmentStrategy.SPARSE_EXACT,
                sparse_candidate_pairs=candidate_count,
            )
        else:
            dense = _bounded_myers_pairs(interior_old, interior_new, budgets)
            if dense.pairs is not None:
                pairs.extend(
                    (old_indices[prefix + old_pos], new_indices[prefix + new_pos])
                    for old_pos, new_pos in dense.pairs
                )
                stats = MatchStats(
                    strategy=AlignmentStrategy.DENSE_EXACT,
                    sparse_candidate_pairs=candidate_count,
                    myers_frontier_states=dense.frontier_states,
                    myers_equality_comparisons=dense.equality_comparisons,
                )
            else:
                fallback_pairs, run_pair_count, used_runs = _fallback_pairs(
                    interior_old,
                    interior_new,
                    budgets,
                )
                pairs.extend(
                    (old_indices[prefix + old_pos], new_indices[prefix + new_pos])
                    for old_pos, new_pos in fallback_pairs
                )
                stats = MatchStats(
                    strategy=(
                        AlignmentStrategy.RUN_FALLBACK
                        if used_runs
                        else AlignmentStrategy.PREFIX_SUFFIX_FALLBACK
                    ),
                    sparse_candidate_pairs=candidate_count,
                    myers_frontier_states=dense.frontier_states,
                    myers_equality_comparisons=dense.equality_comparisons,
                    fallback_run_pairs=run_pair_count,
                    exhausted=True,
                )

    if suffix:
        pairs.extend(
            (
                old_indices[len(old_indices) - suffix + offset],
                new_indices[len(new_indices) - suffix + offset],
            )
            for offset in range(suffix)
        )
    pairs.sort()
    return _AlignmentResult(tuple(pairs), stats)


def _candidate_pair_count(
    old_tokens: Sequence[Fingerprint],
    new_tokens: Sequence[Fingerprint],
    limit: int,
) -> int:
    old_counts = Counter(old_tokens)
    new_counts = Counter(new_tokens)
    total = 0
    for token, old_count in old_counts.items():
        total += old_count * new_counts.get(token, 0)
        if total > limit:
            return limit + 1
    return total


def _sparse_lcs_pairs(
    old_tokens: Sequence[Fingerprint],
    new_tokens: Sequence[Fingerprint],
    *,
    allowed_tokens: set[Fingerprint] | None = None,
) -> tuple[tuple[int, int], ...]:
    """Return an exact LCS with old-tuple then new-tuple lexical ties."""

    if not old_tokens or not new_tokens:
        return ()
    new_positions: dict[Fingerprint, list[int]] = {}
    for new_index, token in enumerate(new_tokens):
        if allowed_tokens is None or token in allowed_tokens:
            new_positions.setdefault(token, []).append(new_index)

    starts = array("I", [0])
    candidates = array("I")
    for token in old_tokens:
        if allowed_tokens is None or token in allowed_tokens:
            candidates.extend(new_positions.get(token, ()))
        starts.append(len(candidates))
    if not candidates:
        return ()

    lengths = array("I", [0]) * len(candidates)
    fenwick = array("I", [0]) * (len(new_tokens) + 1)
    best = 0
    for old_index in range(len(old_tokens) - 1, -1, -1):
        start = starts[old_index]
        end = starts[old_index + 1]
        for candidate_index in range(start, end):
            new_index = candidates[candidate_index]
            rank = len(new_tokens) - new_index
            length = 1 + _fenwick_query(fenwick, rank - 1)
            lengths[candidate_index] = length
            best = max(best, length)
        for candidate_index in range(start, end):
            new_index = candidates[candidate_index]
            rank = len(new_tokens) - new_index
            _fenwick_update(fenwick, rank, lengths[candidate_index])

    selected: list[tuple[int, int]] = []
    remaining = best
    last_new = -1
    for old_index in range(len(old_tokens)):
        for candidate_index in range(starts[old_index], starts[old_index + 1]):
            new_index = candidates[candidate_index]
            if new_index <= last_new or lengths[candidate_index] < remaining:
                continue
            selected.append((old_index, new_index))
            last_new = new_index
            remaining -= 1
            break
        if remaining == 0:
            break
    return tuple(selected)


def _fenwick_query(tree: array[int], index: int) -> int:
    result = 0
    while index > 0:
        result = max(result, tree[index])
        index -= index & -index
    return result


def _fenwick_update(tree: array[int], index: int, value: int) -> None:
    while index < len(tree):
        if value > tree[index]:
            tree[index] = value
        index += index & -index


def _bounded_myers_pairs(
    old_tokens: Sequence[Fingerprint],
    new_tokens: Sequence[Fingerprint],
    budgets: MatchingBudgets,
) -> _DenseResult:
    """Complete Myers alignment or a fully discarded over-budget result."""

    old_count = len(old_tokens)
    new_count = len(new_tokens)
    trace: list[array[int]] = []
    frontier_states = 0
    equality_comparisons = 0

    for distance in range(old_count + new_count + 1):
        previous = trace[-1] if trace else None
        row = array("q", [0]) * (distance + 1)
        for offset, diagonal in enumerate(range(-distance, distance + 1, 2)):
            if frontier_states >= budgets.myers_frontier_states:
                return _DenseResult(None, frontier_states, equality_comparisons)
            frontier_states += 1

            if distance == 0:
                old_index = 0
            elif diagonal == -distance:
                assert previous is not None
                old_index = previous[offset]
            elif diagonal == distance:
                assert previous is not None
                old_index = previous[offset - 1] + 1
            else:
                assert previous is not None
                advance_old = previous[offset - 1] + 1
                advance_new = previous[offset]
                old_index = advance_new if advance_new >= advance_old else advance_old
            new_index = old_index - diagonal

            while old_index < old_count and new_index < new_count:
                if equality_comparisons >= budgets.myers_equalities:
                    return _DenseResult(None, frontier_states, equality_comparisons)
                equality_comparisons += 1
                if old_tokens[old_index] != new_tokens[new_index]:
                    break
                old_index += 1
                new_index += 1
            row[offset] = old_index
            if old_index >= old_count and new_index >= new_count:
                trace.append(row)
                return _DenseResult(
                    _backtrack_myers(trace, old_count, new_count),
                    frontier_states,
                    equality_comparisons,
                )
        trace.append(row)

    raise AssertionError("Myers search failed to reach its finite terminal state")


def _backtrack_myers(
    trace: list[array[int]],
    old_count: int,
    new_count: int,
) -> tuple[tuple[int, int], ...]:
    old_index = old_count
    new_index = new_count
    pairs: list[tuple[int, int]] = []

    for distance in range(len(trace) - 1, 0, -1):
        diagonal = old_index - new_index
        offset = (diagonal + distance) // 2
        previous = trace[distance - 1]
        if diagonal == -distance:
            advance_new = True
        elif diagonal == distance:
            advance_new = False
        else:
            advance_old_x = previous[offset - 1] + 1
            advance_new_x = previous[offset]
            advance_new = advance_new_x >= advance_old_x

        previous_diagonal = diagonal + 1 if advance_new else diagonal - 1
        previous_offset = (previous_diagonal + distance - 1) // 2
        previous_old = previous[previous_offset]
        previous_new = previous_old - previous_diagonal
        snake_old = previous_old if advance_new else previous_old + 1
        snake_new = previous_new + 1 if advance_new else previous_new

        while old_index > snake_old and new_index > snake_new:
            old_index -= 1
            new_index -= 1
            pairs.append((old_index, new_index))
        old_index = previous_old
        new_index = previous_new

    while old_index > 0 and new_index > 0:
        old_index -= 1
        new_index -= 1
        pairs.append((old_index, new_index))
    pairs.reverse()
    return tuple(pairs)


def _fallback_pairs(
    old_tokens: Sequence[Fingerprint],
    new_tokens: Sequence[Fingerprint],
    budgets: MatchingBudgets,
) -> tuple[tuple[tuple[int, int], ...], int, bool]:
    old_runs = _runs(old_tokens)
    new_runs = _runs(new_tokens)
    old_by_token: dict[Fingerprint, list[int]] = {}
    new_by_token: dict[Fingerprint, list[int]] = {}
    for index, run in enumerate(old_runs):
        old_by_token.setdefault(run.token, []).append(index)
    for index, run in enumerate(new_runs):
        new_by_token.setdefault(run.token, []).append(index)

    run_pair_count = 0
    for token, old_indexes in old_by_token.items():
        run_pair_count += len(old_indexes) * len(new_by_token.get(token, ()))
        if run_pair_count > budgets.fallback_run_pairs:
            run_pair_count = budgets.fallback_run_pairs + 1
            break

    if run_pair_count <= budgets.fallback_run_pairs:
        allowed_tokens = set(old_by_token) & set(new_by_token)
    else:
        groups: list[tuple[int, int, int, Fingerprint]] = []
        for token, old_indexes in old_by_token.items():
            new_indexes = new_by_token.get(token)
            if not new_indexes:
                continue
            product = len(old_indexes) * len(new_indexes)
            if product <= budgets.fallback_token_product:
                groups.append((product, old_indexes[0], new_indexes[0], token))
        groups.sort(key=lambda item: item[:3])
        allowed_tokens = set()
        admitted = 0
        for product, _old_first, _new_first, token in groups:
            if admitted + product > budgets.fallback_run_pairs:
                break
            admitted += product
            allowed_tokens.add(token)
        run_pair_count = min(run_pair_count, budgets.fallback_run_pairs + 1)

    old_run_tokens = [run.token for run in old_runs]
    new_run_tokens = [run.token for run in new_runs]
    matched_runs = _sparse_lcs_pairs(
        old_run_tokens,
        new_run_tokens,
        allowed_tokens=allowed_tokens,
    )
    anchors: list[tuple[int, int]] = []
    for old_run_index, new_run_index in matched_runs:
        old_run = old_runs[old_run_index]
        new_run = new_runs[new_run_index]
        anchors.extend(
            (old_run.start + offset, new_run.start + offset)
            for offset in range(min(old_run.length, new_run.length))
        )

    result: list[tuple[int, int]] = []
    previous_old = 0
    previous_new = 0
    for old_anchor, new_anchor in anchors:
        result.extend(
            _edge_pairs(
                old_tokens,
                new_tokens,
                previous_old,
                old_anchor,
                previous_new,
                new_anchor,
            )
        )
        result.append((old_anchor, new_anchor))
        previous_old = old_anchor + 1
        previous_new = new_anchor + 1
    result.extend(
        _edge_pairs(
            old_tokens,
            new_tokens,
            previous_old,
            len(old_tokens),
            previous_new,
            len(new_tokens),
        )
    )
    deduplicated = tuple(dict.fromkeys(result))
    return deduplicated, run_pair_count, bool(anchors)


def _runs(tokens: Sequence[Fingerprint]) -> list[_Run]:
    if not tokens:
        return []
    result: list[_Run] = []
    start = 0
    for index in range(1, len(tokens) + 1):
        if index < len(tokens) and tokens[index] == tokens[start]:
            continue
        result.append(_Run(tokens[start], start, index - start))
        start = index
    return result


def _edge_pairs(
    old_tokens: Sequence[Fingerprint],
    new_tokens: Sequence[Fingerprint],
    old_start: int,
    old_end: int,
    new_start: int,
    new_end: int,
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    while (
        old_start < old_end
        and new_start < new_end
        and old_tokens[old_start] == new_tokens[new_start]
    ):
        result.append((old_start, new_start))
        old_start += 1
        new_start += 1

    suffix: list[tuple[int, int]] = []
    while (
        old_start < old_end
        and new_start < new_end
        and old_tokens[old_end - 1] == new_tokens[new_end - 1]
    ):
        old_end -= 1
        new_end -= 1
        suffix.append((old_end, new_end))
    result.extend(reversed(suffix))
    return result


def _stationary_positions(matches: list[ArrayMatch]) -> set[int]:
    """Return the lexicographically-smallest old-index LIS in O(k log k)."""

    if not matches:
        return set()
    old_indexes = sorted(match.old_index for match in matches)
    rank_by_old = {old_index: rank + 1 for rank, old_index in enumerate(old_indexes)}
    old_limit = len(old_indexes)
    fenwick = array("I", [0]) * (old_limit + 1)
    lis_from = [0] * len(matches)
    for position in range(len(matches) - 1, -1, -1):
        rank = old_limit - rank_by_old[matches[position].old_index] + 1
        lis_from[position] = 1 + _fenwick_query(fenwick, rank - 1)
        _fenwick_update(fenwick, rank, lis_from[position])

    remaining = max(lis_from)
    stationary: set[int] = set()
    last_position = -1
    for position in sorted(
        range(len(matches)),
        key=lambda item: matches[item].old_index,
    ):
        if position <= last_position or lis_from[position] < remaining:
            continue
        stationary.add(position)
        last_position = position
        remaining -= 1
        if remaining == 0:
            break
    return stationary
