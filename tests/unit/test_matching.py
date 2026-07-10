from __future__ import annotations

from itertools import combinations, pairwise, permutations

import pytest

from jsondiffview.matching import (
    AlignmentStrategy,
    ArrayMatch,
    MatchingBudgets,
    _bounded_myers_pairs,
    _candidate_pair_count,
    _fallback_pairs,
    _sparse_lcs_pairs,
    _stationary_positions,
    match_array_with_stats,
)
from jsondiffview.model import (
    AlignmentBasis,
    JsonValue,
    MatchEvidence,
    MatchKind,
)
from jsondiffview.parser import decode_json_bytes, strict_equal


def parse(text: str) -> JsonValue:
    return decode_json_bytes(text.encode(), "fixture.json")


def test_higher_priority_identity_conflict_vetoes_lower_key() -> None:
    old = parse('[{"id":1,"name":"same","v":"old"}]')
    new = parse('[{"id":2,"name":"same","v":"new"}]')
    assert isinstance(old, list)
    assert isinstance(new, list)

    matches, _ = match_array_with_stats(old, new, ("id", "name"))
    assert matches == ()


def test_ambiguous_higher_key_allows_unique_lower_key() -> None:
    old = parse('[{"name":"same","title":"one"},{"name":"same","title":"two"}]')
    new = parse('[{"name":"same","title":"two"},{"name":"same","title":"three"}]')
    assert isinstance(old, list)
    assert isinstance(new, list)

    matches, _ = match_array_with_stats(old, new, ("name", "title"))
    assert len(matches) == 1
    assert matches[0].evidence is not None
    assert matches[0].evidence.key == "title"


@pytest.mark.parametrize("unavailable", ["null", "{}", "[]"])
def test_unavailable_higher_identity_neither_matches_nor_vetoes(
    unavailable: str,
) -> None:
    old = parse(f'[{{"id":{unavailable},"name":"same","v":1}}]')
    new = parse(f'[{{"id":{unavailable},"name":"same","v":2}}]')
    assert isinstance(old, list)
    assert isinstance(new, list)

    matches, _ = match_array_with_stats(old, new, ("id", "name"))
    assert len(matches) == 1
    assert matches[0].evidence is not None
    assert matches[0].evidence.key == "name"


@pytest.mark.parametrize(
    ("old_identity", "new_identity"),
    [("true", "1"), ("1", "1.0"), ('"1"', "1")],
)
def test_identity_fingerprints_keep_strict_types(
    old_identity: str,
    new_identity: str,
) -> None:
    old = parse(f'[{{"id":{old_identity},"v":1}}]')
    new = parse(f'[{{"id":{new_identity},"v":2}}]')
    assert isinstance(old, list)
    assert isinstance(new, list)
    matches, _ = match_array_with_stats(old, new, ("id",))
    assert matches == ()


def test_duplicate_exact_alignment_is_stable_and_never_move_evidence() -> None:
    old = parse('["a","b","a","b"]')
    new = parse('["b","a","b","a"]')
    assert isinstance(old, list)
    assert isinstance(new, list)
    matches, stats = match_array_with_stats(old, new, ())

    duplicates = [
        match
        for match in matches
        if match.alignment_basis is AlignmentBasis.DUPLICATE_EXACT_SEQUENCE
    ]
    assert [(match.old_index, match.new_index) for match in duplicates] == [
        (0, 1),
        (1, 2),
        (2, 3),
    ]
    assert all(match.evidence is None and not match.moved for match in duplicates)
    assert stats.strategy is AlignmentStrategy.SPARSE_EXACT


def test_duplicate_count_imbalance_leaves_remainder_unmatched() -> None:
    old = parse('["x","x"]')
    new = parse('["x"]')
    assert isinstance(old, list)
    assert isinstance(new, list)
    matches, _ = match_array_with_stats(old, new, ())

    assert [(match.old_index, match.new_index) for match in matches] == [(0, 0)]


def test_globally_unique_exact_value_retains_move_evidence() -> None:
    old = parse('["a","b"]')
    new = parse('["b","a"]')
    assert isinstance(old, list)
    assert isinstance(new, list)
    matches, _ = match_array_with_stats(old, new, ())

    assert all(
        match.alignment_basis is AlignmentBasis.UNIQUE_EXACT for match in matches
    )
    assert sum(match.moved for match in matches) == 1
    assert all(match.evidence is not None for match in matches)


def test_sparse_lcs_uses_old_then_new_lexical_ties() -> None:
    old = [("v", value) for value in ("a", "b", "a", "c")]
    new = [("v", value) for value in ("a", "a", "b", "c")]
    assert _sparse_lcs_pairs(old, new) == _reference_pairs(old, new)


def test_sparse_lcs_matches_reference_exhaustively() -> None:
    alphabet = (("v", "a"), ("v", "b"))
    sequences = [
        list(sequence) for length in range(5) for sequence in _product(alphabet, length)
    ]
    for old in sequences:
        for new in sequences:
            assert _sparse_lcs_pairs(old, new) == _reference_pairs(old, new)


@pytest.mark.parametrize(
    ("candidate_pairs", "reported"),
    [(2, 2), (3, 3), (4, 4)],
)
def test_sparse_candidate_budget_boundaries(
    candidate_pairs: int,
    reported: int,
) -> None:
    old = [("v", "x")]
    new = [("v", "x")] * candidate_pairs
    assert _candidate_pair_count(old, new, 3) == reported


@pytest.mark.parametrize(
    ("equality_budget", "complete"),
    [(2, False), (3, True), (4, True)],
)
def test_dense_equality_budget_boundaries(
    equality_budget: int,
    complete: bool,
) -> None:
    tokens = [("v", "x")] * 3
    result = _bounded_myers_pairs(
        tokens,
        tokens,
        MatchingBudgets(
            sparse_pairs=0,
            myers_frontier_states=10,
            myers_equalities=equality_budget,
        ),
    )
    assert (result.pairs is not None) is complete
    assert result.equality_comparisons == min(equality_budget, 3)


@pytest.mark.parametrize(
    ("state_budget", "complete"),
    [(4, False), (5, True), (6, True)],
)
def test_dense_frontier_budget_boundaries(
    state_budget: int,
    complete: bool,
) -> None:
    result = _bounded_myers_pairs(
        [("v", "a")],
        [("v", "b")],
        MatchingBudgets(
            sparse_pairs=0,
            myers_frontier_states=state_budget,
            myers_equalities=10,
        ),
    )
    assert (result.pairs is not None) is complete
    assert result.frontier_states == min(state_budget, 5)


def test_dense_alignment_returns_only_equal_monotone_pairs() -> None:
    old = [("v", value) for value in "abababab"]
    new = [("v", value) for value in "babababa"]
    result = _bounded_myers_pairs(
        old,
        new,
        MatchingBudgets(
            sparse_pairs=0,
            myers_frontier_states=100,
            myers_equalities=100,
        ),
    )
    assert result.pairs is not None
    assert all(
        old[old_index] == new[new_index] for old_index, new_index in result.pairs
    )
    assert list(result.pairs) == sorted(result.pairs)


def test_dense_alignment_matches_independent_small_lcs_reference() -> None:
    alphabet = (("v", "a"), ("v", "b"))
    sequences = [
        list(sequence) for length in range(5) for sequence in _product(alphabet, length)
    ]
    budgets = MatchingBudgets(
        sparse_pairs=0,
        myers_frontier_states=10_000,
        myers_equalities=100_000,
    )
    for old in sequences:
        for new in sequences:
            result = _bounded_myers_pairs(old, new, budgets)
            assert result.pairs is not None
            assert len(result.pairs) == _reference_lcs_length(old, new)
            assert all(
                old[old_index] == new[new_index]
                for old_index, new_index in result.pairs
            )


def test_over_budget_matcher_uses_exact_conservative_fallback() -> None:
    old = parse('["a","b","a","b","a","b"]')
    new = parse('["b","b","b","a","a","a"]')
    assert isinstance(old, list)
    assert isinstance(new, list)
    matches, stats = match_array_with_stats(
        old,
        new,
        (),
        budgets=MatchingBudgets(
            sparse_pairs=1,
            myers_frontier_states=1,
            myers_equalities=1,
            fallback_run_pairs=2,
            fallback_token_product=1,
        ),
    )

    assert stats.exhausted
    assert stats.strategy in {
        AlignmentStrategy.RUN_FALLBACK,
        AlignmentStrategy.PREFIX_SUFFIX_FALLBACK,
    }
    for match in matches:
        assert strict_equal(old[match.old_index], new[match.new_index])
        assert match.evidence is None
        assert not match.moved


@pytest.mark.parametrize(
    ("run_pairs", "reported"),
    [(2, 2), (3, 3), (4, 4)],
)
def test_fallback_run_pair_budget_boundaries(
    run_pairs: int,
    reported: int,
) -> None:
    old = [("v", "x")]
    new = [
        token
        for index in range(run_pairs)
        for token in (
            ("v", "x"),
            ("separator", str(index)),
        )
    ][:-1]
    _pairs, count, _used_runs = _fallback_pairs(
        old,
        new,
        MatchingBudgets(
            fallback_run_pairs=3,
            fallback_token_product=64,
        ),
    )
    assert count == reported


@pytest.mark.parametrize(
    ("run_pairs", "uses_anchor"),
    [(2, True), (3, True), (4, False)],
)
def test_fallback_token_product_boundaries(
    run_pairs: int,
    uses_anchor: bool,
) -> None:
    old = [
        ("v", "x"),
        ("v", "y"),
        ("old-separator", "1"),
        ("v", "y"),
        ("old-separator", "2"),
        ("v", "y"),
    ]
    new_x = [
        token
        for index in range(run_pairs)
        for token in (
            ("v", "x"),
            ("new-x-separator", str(index)),
        )
    ][:-1]
    new = [
        *new_x,
        ("v", "y"),
        ("new-y-separator", "1"),
        ("v", "y"),
        ("new-y-separator", "2"),
        ("v", "y"),
    ]
    _pairs, _count, used_runs = _fallback_pairs(
        old,
        new,
        MatchingBudgets(
            fallback_run_pairs=4,
            fallback_token_product=3,
        ),
    )
    assert used_runs is uses_anchor


def test_scalable_stationary_backbone_matches_small_reference() -> None:
    for size in range(1, 8):
        for old_indexes in permutations(range(size)):
            matches = [
                ArrayMatch(
                    old_index,
                    new_index,
                    AlignmentBasis.UNIQUE_EXACT,
                    MatchEvidence(MatchKind.EXACT),
                )
                for new_index, old_index in enumerate(old_indexes)
            ]
            assert _stationary_positions(matches) == _reference_stationary(old_indexes)


def test_stationary_backbone_memory_depends_on_matches_not_old_index_span() -> None:
    old_indexes = (1_000_000_000, 1, 2)
    matches = [
        ArrayMatch(
            old_index,
            new_index,
            AlignmentBasis.UNIQUE_EXACT,
            MatchEvidence(MatchKind.EXACT),
        )
        for new_index, old_index in enumerate(old_indexes)
    ]

    assert _stationary_positions(matches) == _reference_stationary(old_indexes)


def _reference_stationary(old_indexes: tuple[int, ...]) -> set[int]:
    candidates: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
    for length in range(len(old_indexes) + 1):
        for positions in combinations(range(len(old_indexes)), length):
            values = tuple(old_indexes[position] for position in positions)
            if all(left < right for left, right in pairwise(values)):
                candidates.append((values, positions))
    _values, positions = min(
        candidates,
        key=lambda candidate: (-len(candidate[0]), candidate[0]),
    )
    return set(positions)


def _reference_pairs(
    old: list[tuple[str, str]],
    new: list[tuple[str, str]],
) -> tuple[tuple[int, int], ...]:
    candidates: list[tuple[tuple[int, int], ...]] = [()]

    def visit(
        old_start: int,
        new_start: int,
        selected: tuple[tuple[int, int], ...],
    ) -> None:
        for old_index in range(old_start, len(old)):
            for new_index in range(new_start, len(new)):
                if old[old_index] != new[new_index]:
                    continue
                candidate = (*selected, (old_index, new_index))
                candidates.append(candidate)
                visit(old_index + 1, new_index + 1, candidate)

    visit(0, 0, ())
    return min(
        candidates,
        key=lambda pairs: (
            -len(pairs),
            tuple(old_index for old_index, _new_index in pairs),
            tuple(new_index for _old_index, new_index in pairs),
        ),
    )


def _reference_lcs_length(
    old: list[tuple[str, str]],
    new: list[tuple[str, str]],
) -> int:
    previous = [0] * (len(new) + 1)
    for old_token in old:
        current = [0]
        for new_index, new_token in enumerate(new, start=1):
            if old_token == new_token:
                current.append(previous[new_index - 1] + 1)
            else:
                current.append(max(previous[new_index], current[-1]))
        previous = current
    return previous[-1]


def _product(
    values: tuple[tuple[str, str], ...],
    length: int,
) -> list[tuple[tuple[str, str], ...]]:
    if length == 0:
        return [()]
    return [
        (*prefix, value) for prefix in _product(values, length - 1) for value in values
    ]
