"""Cross-layer regressions for trustworthy and resource-safe review output."""

from __future__ import annotations

import json
from collections.abc import Iterator
from itertools import combinations, pairwise, permutations, product

import pytest

from jsondiffview.color import serialize_ansi, serialize_plain
from jsondiffview.diff import build_diff
from jsondiffview.matching import ArrayMatch, _stationary_positions, match_array
from jsondiffview.model import (
    AlignmentBasis,
    JsonValue,
    MatchEvidence,
    MatchKind,
    View,
    bounded_diagnostic_text,
)
from jsondiffview.parser import decode_json_bytes
from jsondiffview.render import _escape_json_fragment, render_diff
from jsondiffview.strings import (
    EXCERPT_CODE_POINT_LIMIT,
    ProjectedLongStringDiff,
    bounded_excerpt,
    build_string_diff,
    display_width,
    project_string_diff,
)

_BIDI_CONTROLS = (
    0x061C,
    0x200E,
    0x200F,
    0x202A,
    0x202B,
    0x202C,
    0x202D,
    0x202E,
    0x2066,
    0x2067,
    0x2068,
    0x2069,
)


def _parse(text: str) -> JsonValue:
    return decode_json_bytes(text.encode(), "regression.json")


@pytest.mark.parametrize("view", list(View))
@pytest.mark.parametrize(
    ("old", "new", "move"),
    [
        ('["a","b","a"]', '["a","a","b"]', (1, 2)),
        ('[{"id":"x"},0,0]', '[0,{"id":"x"},0]', (0, 1)),
        (
            '[{"id":"x","v":1},0,0]',
            '[0,{"id":"x","v":2},0]',
            (0, 1),
        ),
    ],
)
def test_duplicate_alignment_cannot_hide_a_trusted_move(
    old: str, new: str, move: tuple[int, int], view: View
) -> None:
    tree = build_diff(_parse(old), _parse(new))
    moved = [entry for entry in tree.array_entries if entry.moved]
    assert [(entry.old_index, entry.new_index) for entry in moved] == [move]
    output = serialize_plain(render_diff(tree, view))
    assert f"moved from $[{move[0]}] to $[{move[1]}]" in output
    assert "3 unchanged items omitted" not in output


def test_all_small_array_matches_have_a_monotone_stationary_backbone() -> None:
    sequences = [seq for size in range(5) for seq in product("abc", repeat=size)]
    for old_sequence, new_sequence in product(sequences, repeat=2):
        old: list[JsonValue] = list(old_sequence)
        new: list[JsonValue] = list(new_sequence)
        matches = match_array(old, new, ())
        stationary = [match.old_index for match in matches if not match.moved]
        assert all(left < right for left, right in pairwise(stationary)), (
            old_sequence,
            new_sequence,
            matches,
        )
        assert len({match.old_index for match in matches}) == len(matches)
        assert len({match.new_index for match in matches}) == len(matches)
        assert all(old[match.old_index] == new[match.new_index] for match in matches)
        assert all(not match.moved for match in matches if match.evidence is None)


def test_constrained_backbone_matches_an_exhaustive_independent_oracle() -> None:
    for size in range(1, 6):
        for old_indexes in permutations(range(size)):
            subsequences = [
                positions
                for length in range(size + 1)
                for positions in combinations(range(size), length)
                if all(
                    old_indexes[left] < old_indexes[right]
                    for left, right in pairwise(positions)
                )
            ]
            for anchors in subsequences:
                required = set(anchors)
                matches = [
                    ArrayMatch(
                        old_index,
                        new_index,
                        AlignmentBasis.DUPLICATE_EXACT_SEQUENCE
                        if new_index in required
                        else AlignmentBasis.UNIQUE_EXACT,
                        None
                        if new_index in required
                        else MatchEvidence(MatchKind.EXACT),
                    )
                    for new_index, old_index in enumerate(old_indexes)
                ]
                expected = min(
                    (
                        positions
                        for positions in subsequences
                        if required <= set(positions)
                    ),
                    key=lambda positions: (
                        -len(positions),
                        tuple(old_indexes[p] for p in positions),
                    ),
                )
                assert _stationary_positions(matches) == set(expected)


@pytest.mark.parametrize("code_point", _BIDI_CONTROLS)
@pytest.mark.parametrize("view", list(View))
def test_bidi_controls_are_visible_in_keys_values_and_move_provenance(
    code_point: int, view: View
) -> None:
    control = chr(code_point)
    key = "key" + control
    old = json.dumps({key: [{"id": "safe"}, {"id": "unsafe" + control}]})
    new = json.dumps({key: [{"id": "unsafe" + control}, {"id": "safe"}]})
    spans = render_diff(build_diff(_parse(old), _parse(new)), view)
    for output in (serialize_plain(spans), serialize_ansi(spans)):
        assert control not in output
        assert rf"\u{code_point:04x}" in output
        provenance = next(line for line in output.splitlines() if "moved from" in line)
        assert rf"\u{code_point:04x}" in provenance


@pytest.mark.parametrize("code_point", _BIDI_CONTROLS)
def test_bidi_controls_are_visible_in_diagnostics(code_point: int) -> None:
    control = chr(code_point)
    diagnostic = bounded_diagnostic_text("invalid option: " + control + "hidden")
    assert control not in diagnostic
    assert rf"\u{code_point:04x}" in diagnostic


def test_terminal_safety_keeps_normal_script_and_emoji_joiners() -> None:
    text = "العربية עברית 中文 e\u0301 👨‍👩‍👧‍👦 می\u200cروم"
    assert _escape_json_fragment(text) == text
    assert bounded_diagnostic_text(text) == text


@pytest.mark.parametrize("width", [48, 96, 160])
@pytest.mark.parametrize(
    "text",
    ["e" + "\u0301" * 4_096, "\u200b" * 4_096, "👩" + "‍👩" * 2_048],
    ids=["combining-cluster", "zero-width-run", "joined-emoji"],
)
def test_excerpt_has_a_code_point_bound_as_well_as_a_cell_bound(
    text: str, width: int
) -> None:
    excerpt = bounded_excerpt(text, width, _escape_json_fragment)
    assert len(excerpt.text) <= 512
    assert display_width(_escape_json_fragment(excerpt.text)) <= width
    assert excerpt.omitted == len(text) - len(excerpt.text.replace("…", ""))
    if not text.startswith("\u200b"):
        # An over-budget extended grapheme must be omitted whole, not split.
        assert excerpt.text == "…"


@pytest.mark.parametrize("view", list(View))
def test_long_hunk_context_cannot_bypass_the_code_point_bound(view: View) -> None:
    context = "e" + "\u0301" * 4_096
    old = context + "-OLD-" + context
    new = context + "-NEW-" + context
    projected = project_string_diff(
        build_string_diff(old, new), view, _escape_json_fragment
    )
    assert isinstance(projected, ProjectedLongStringDiff)
    for hunk in projected.hunks:
        for excerpt in (hunk.old_excerpt, hunk.new_excerpt):
            assert len(excerpt.text) <= 512
            assert context not in excerpt.text


class _CountingDict(dict[str, JsonValue]):
    key_visits = 0

    def __iter__(self) -> Iterator[str]:
        for key in super().__iter__():
            self.key_visits += 1
            yield key


def test_full_unchanged_object_projection_visits_keys_only_once() -> None:
    stable = _CountingDict({f"key_{index}": "stable" for index in range(128)})
    old: JsonValue = {"context": stable, "flag": False}
    new: JsonValue = {"context": stable, "flag": True}
    tree = build_diff(old, new)
    stable.key_visits = 0
    output = serialize_plain(render_diff(tree, View.FULL))
    assert '"key_127": "stable"' in output
    assert stable.key_visits <= len(stable)


@pytest.mark.parametrize("length", [511, 512, 513])
def test_code_point_allowance_boundary_keeps_or_omits_whole_clusters(
    length: int,
) -> None:
    text = "e" + "\u0301" * (length - 1)
    excerpt = bounded_excerpt(text)
    if length <= EXCERPT_CODE_POINT_LIMIT:
        assert excerpt.text == text
        assert excerpt.omitted == 0
    else:
        assert excerpt.text == "…"
        assert excerpt.omitted == length


@pytest.mark.parametrize("cells", [0, 1, 2, 48])
@pytest.mark.parametrize("code_points", [0, 1, 2, 8])
def test_small_excerpt_budgets_include_the_omission_marker(
    cells: int,
    code_points: int,
) -> None:
    text = "\u200b" * 10 + "abc"
    excerpt = bounded_excerpt(text, cells, max_code_points=code_points)
    assert len(excerpt.text) <= code_points
    assert display_width(excerpt.text) <= cells
    assert excerpt.omitted == len(text) - len(excerpt.text.replace("…", ""))
    assert bounded_excerpt("", cells, max_code_points=code_points).text == ""


@pytest.mark.parametrize(("cells", "code_points"), [(-1, 512), (48, -1)])
def test_negative_excerpt_budgets_are_rejected(cells: int, code_points: int) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        bounded_excerpt("text", cells, max_code_points=code_points)


def test_oversized_graphemes_are_not_copied_into_the_display_escaper() -> None:
    sizes: list[int] = []

    def escape(text: str) -> str:
        sizes.append(len(text))
        assert len(text) <= EXCERPT_CODE_POINT_LIMIT
        return _escape_json_fragment(text)

    giant = "e" + "\u0301" * 100_000
    text = "prefix-" + giant + "-suffix"
    excerpt = bounded_excerpt(text, escape_for_width=escape)
    assert excerpt.text == "prefix-…-suffix"
    assert excerpt.omitted == len(giant)
    assert sizes


@pytest.mark.parametrize("view", list(View))
@pytest.mark.parametrize("route", ["add", "remove", "context", "replace", "multiline"])
def test_every_string_render_route_bounds_zero_width_output(
    route: str,
    view: View,
) -> None:
    giant = "e" + "\u0301" * 4_096
    if route == "add":
        old, new = "{}", json.dumps({"value": giant})
    elif route == "remove":
        old, new = json.dumps({"value": giant}), "{}"
    elif route == "context":
        old = json.dumps({"value": giant, "flag": False})
        new = json.dumps({"value": giant, "flag": True})
    elif route == "replace":
        old, new = "null", json.dumps(giant)
    else:
        old = json.dumps(giant + "\nold\n")
        new = json.dumps(giant + "\nnew\n")
    output = serialize_plain(render_diff(build_diff(_parse(old), _parse(new)), view))
    assert giant not in output
    assert len(output) < 2_000
    if route != "context" or view is not View.SUMMARY:
        assert "4097 code points omitted" in output


@pytest.mark.parametrize("view", list(View))
def test_long_zero_width_identity_is_bounded_in_move_evidence(view: View) -> None:
    giant = "e" + "\u0301" * 4_096
    old = json.dumps([{"id": "safe"}, {"id": giant}])
    new = json.dumps([{"id": giant}, {"id": "safe"}])
    output = serialize_plain(render_diff(build_diff(_parse(old), _parse(new)), view))
    assert giant not in output
    assert "moved from" in output
    assert "4097 code points omitted" in output
    assert len(output) < 2_000
