from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from jsondiffview.color import serialize_ansi, serialize_plain
from jsondiffview.diff import build_diff
from jsondiffview.model import JsonNumber, JsonNumberKind, JsonValue, StyleRole, View
from jsondiffview.parser import decode_json_bytes
from jsondiffview.render import (
    SUBTREE_SUMMARY_THRESHOLD,
    SUMMARY_PREVIEW_CELL_LIMIT,
    SUMMARY_PREVIEW_ROW_LIMIT,
    _render_summary_preview,
    render_diff,
)
from jsondiffview.strings import (
    BLOB_HARD_CODE_POINT_LIMIT,
    REVIEW_EXCERPT_CELLS,
    StringBudgets,
    build_string_diff,
    display_width,
)

_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


def parse(text: str) -> JsonValue:
    return decode_json_bytes(text.encode(), "fixture.json")


def render(old: str, new: str, view: View = View.REVIEW) -> str:
    return serialize_plain(render_diff(build_diff(parse(old), parse(new)), view))


@pytest.mark.parametrize(
    ("view", "expected"),
    [
        (
            View.SUMMARY,
            """\
~ {
…   2 unchanged fields omitted
~   "c": 2 -> 20,
…   2 unchanged fields omitted
  }
""",
        ),
        (
            View.REVIEW,
            """\
~ {
…   1 unchanged field omitted
    "b": 1,
~   "c": 2 -> 20,
    "d": 3,
…   1 unchanged field omitted
  }
""",
        ),
        (
            View.FULL,
            """\
~ {
    "a": 0,
    "b": 1,
~   "c": 2 -> 20,
    "d": 3,
    "e": 4
  }
""",
        ),
    ],
)
def test_view_projection_goldens(view: View, expected: str) -> None:
    old = '{"a":0,"b":1,"c":2,"d":3,"e":4}'
    new = '{"a":0,"b":1,"c":20,"d":3,"e":4}'
    assert render(old, new, view) == expected


def test_move_plus_modification_golden() -> None:
    old = (
        '{"services":[{"id":"api","port":80},{"id":"worker","port":9000},'
        '{"id":"db","port":5432}],"title":"Hello world","obsolete":true}'
    )
    new = (
        '{"services":[{"id":"api","port":80},{"id":"db","port":5432},'
        '{"id":"worker","port":9001}],"title":"Hello team"}'
    )
    expected = """\
~ {
~   "services": [
      [0]: {
        "id": "api",
…       1 unchanged field omitted
      },
>     moved from $.services[2] to $.services[1] (matched by "id": "db")
      [1]: {
        "id": "db",
…       1 unchanged field omitted
      },
~     [2]: {
        "id": "worker",
~       "port": 9000 -> 9001
      }
    ],
~   "title": "Hello [-world-][+team+]",
-   "obsolete": true
  }
"""
    assert render(old, new) == expected
    readme = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")
    assert f"```text\n{expected}```" in readme


def test_readme_matching_examples_are_renderer_output() -> None:
    readme = (Path(__file__).parents[2] / "README.md").read_text(encoding="utf-8")
    examples = (
        render('["keep","gone"]', '["keep"]'),
        render(
            '[{"id":"a","v":1},{"id":"b","v":1}]',
            '[{"id":"b","v":2},{"id":"a","v":1}]',
        ),
        render(
            '[{"id":"x","v":1},{"id":"x","v":2}]',
            '[{"id":"x","v":3},{"id":"x","v":4}]',
        ),
    )
    for example in examples:
        assert f"```text\n{example}```" in readme


def test_root_scalar_and_type_replacements() -> None:
    assert render("1", "2") == "~ 1 -> 2\n"
    assert (
        render("1", "1.0")
        == """\
~ integer -> decimal
-   1
+   1.0
"""
    )


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
def test_every_value_kind_renders_deterministically_at_root_and_nested(
    old: str,
    new: str,
) -> None:
    for old_document, new_document in (
        (old, new),
        (f'{{"value":{old}}}', f'{{"value":{new}}}'),
    ):
        first = render(old_document, new_document)
        assert first
        assert first == render(old_document, new_document)
        assert first.endswith("\n")
        assert all(
            line[:2] in {"  ", "+ ", "- ", "~ ", "> ", "… "}
            for line in first.splitlines()
        )


def test_ambiguous_array_items_are_remove_plus_add_with_old_labels() -> None:
    output = render(
        '[{"id":"x","v":1},{"id":"x","v":2}]',
        '[{"id":"x","v":3},{"id":"x","v":4}]',
    )
    assert "+   [0]:" in output
    assert "+   [1]:" in output
    assert "-   [old 0]:" in output
    assert "-   [old 1]:" in output
    assert "moved from" not in output


def test_nested_removed_arrays_use_old_index_labels() -> None:
    output = render('{"gone":[["value"]]}', "{}")
    assert '-   "gone": [' in output
    assert "-     [old 0]: [" in output
    assert '-       [old 0]: "value"' in output
    assert "-     [0]:" not in output


def test_summary_can_collapse_large_added_subtree() -> None:
    fields = ",".join(f'"k{index}":{index}' for index in range(10))
    summary = render("{}", f'{{"config":{{{fields}}}}}', View.SUMMARY)
    review = render("{}", f'{{"config":{{{fields}}}}}', View.REVIEW)
    assert '+   "config": {' in summary
    assert '+     "k0": 0,' in summary
    assert '+     "k1": 1,' in summary
    assert "+     … 8 added nested values omitted" in summary
    assert '"k0": 0' in review
    assert '"k9": 9' in review


def test_summary_preview_falls_back_when_row_cap_would_be_exceeded() -> None:
    first = '{"a":1,"b":2,"c":3}'
    second = '{"d":4,"e":5,"f":6}'
    new = '{"config":{"first":' + first + ',"second":' + second + ',"tail":7}}'
    output = render("{}", new, View.SUMMARY)
    assert '+   "config": { … 9 added nested values omitted }' in output
    assert '"first"' not in output


@pytest.mark.parametrize(
    ("second_fields", "previewed"),
    [(2, True), (3, True), (4, False)],
)
def test_summary_preview_row_cap_boundaries(
    second_fields: int,
    previewed: bool,
) -> None:
    first = ",".join(f'"a{index}":{index}' for index in range(2))
    second = ",".join(f'"b{index}":{index}' for index in range(second_fields))
    omitted = ",".join(f'"z{index}":{index}' for index in range(10))
    new = (
        '{"config":{"first":{'
        + first
        + '},"second":{'
        + second
        + '},"omitted":{'
        + omitted
        + "}}}"
    )
    output = render("{}", new, View.SUMMARY)
    assert ('+     "first": {' in output) is previewed
    assert ('+     "second": {' in output) is previewed
    if previewed:
        physical_rows = len(output.splitlines()) - 2
        assert physical_rows <= SUMMARY_PREVIEW_ROW_LIMIT


def test_summary_preview_falls_back_when_escaped_cell_cap_is_exceeded() -> None:
    huge_key = "界" * 600
    fields = f'"{huge_key}":1,' + ",".join(f'"k{index}":{index}' for index in range(10))
    output = render("{}", f'{{"config":{{{fields}}}}}', View.SUMMARY)
    assert '+   "config": { … 11 added nested values omitted }' in output
    assert huge_key not in output


def test_summary_preview_cell_cap_boundaries() -> None:
    number = JsonNumber(JsonNumberKind.INTEGER, 1, "1")

    def preview(key_length: int) -> object:
        return _render_summary_preview(
            {
                "k" * key_length: number,
                "second": number,
                "omitted": number,
            },
            '"config"',
            1,
            "+ ",
            StyleRole.ADDED,
            "added",
        )

    fixed_cells = sum(
        display_width(line)
        for line in (
            '+   "config": {',
            '+     "": 1,',
            '+     "second": 1,',
            "+     … 1 added nested value omitted",
            "+   }",
        )
    )
    maximum_key_length = SUMMARY_PREVIEW_CELL_LIMIT - fixed_cells
    assert preview(maximum_key_length - 1) is not None
    assert preview(maximum_key_length) is not None
    assert preview(maximum_key_length + 1) is None


@pytest.mark.parametrize(
    ("count", "summarized"),
    [
        (SUBTREE_SUMMARY_THRESHOLD - 1, False),
        (SUBTREE_SUMMARY_THRESHOLD, False),
        (SUBTREE_SUMMARY_THRESHOLD + 1, True),
    ],
)
def test_added_subtree_summary_threshold(count: int, summarized: bool) -> None:
    fields = ",".join(f'"k{index}":{index}' for index in range(count))
    output = render("{}", f'{{"config":{{{fields}}}}}', View.SUMMARY)
    assert ("added nested values omitted" in output) is summarized


def test_multiline_string_shows_escaped_logical_line_terminators() -> None:
    output = render('"same\\nold\\r\\nlast"', '"same\\nnew\\rlast\\n"')
    assert "<multiline string: 3 -> 3 logical lines>" in output
    assert '-   "old\\r\\n"' in output
    assert '+   "new\\r"' in output
    assert '-   "last"' in output
    assert '+   "last[+\\n+]"' in output


def test_coarse_multiline_render_reports_exact_omitted_code_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def constrained_string_diff(old: str, new: str) -> object:
        return build_string_diff(
            old,
            new,
            budgets=replace(StringBudgets(), multiline_code_points=1),
        )

    monkeypatch.setattr(
        "jsondiffview.render.build_string_diff",
        constrained_string_diff,
    )
    old = "a\nbb\nccc\ndddd\neeeee\n"
    new = "x\nyy\nzzz\nwwww\nvvvvv\n"
    output = render(json.dumps(old), json.dumps(new), View.FULL)

    assert "1 removed line / 4 code points omitted" in output
    assert "1 added line / 4 code points omitted" in output


@pytest.mark.parametrize(
    ("row_length", "bounded"),
    [
        (REVIEW_EXCERPT_CELLS - 2, False),
        (REVIEW_EXCERPT_CELLS - 1, False),
        (REVIEW_EXCERPT_CELLS, True),
    ],
)
def test_multiline_logical_line_excerpt_boundaries(
    row_length: int,
    bounded: bool,
) -> None:
    common_line = "z" * (row_length - 1) + "\\n"
    output = render(
        f'"{common_line}old\\n"',
        f'"{common_line}new\\n"',
    )
    assert ("omitted within logical line" in output) is bounded


def test_long_string_output_is_bounded_and_reports_code_point_offsets() -> None:
    prefix = "p" * (BLOB_HARD_CODE_POINT_LIMIT + 10)
    output = render(f'"{prefix}xxx"', f'"{prefix}yyy-value"')
    assert "<long string:" in output
    assert "code points; 1 hunk>" in output
    assert "476 old / 479 new unchanged code points omitted before" in output
    assert f"old {len(prefix)}:{len(prefix) + 3}" in output
    assert '"ppppppppppppppppppppppppppppppppppppppppppppppxxx"' in output


def test_multiple_long_hunks_partition_context_without_overlap() -> None:
    old = "A" * 100 + "x" + "q" * 300 + "y" + "B" * 100
    new = "A" * 100 + "u" + "q" * 300 + "v" + "B" * 100
    output = render(f'"{old}"', f'"{new}"')
    assert "2 hunks>" in output
    assert "unchanged code points omitted between hunks" in output
    assert " -1 " not in output
    assert "old -1" not in output
    assert "new -1" not in output


def test_long_added_and_context_strings_use_bounded_excerpts() -> None:
    value = "z" * 10_000
    added = render("{}", f'{{"payload":"{value}"}}')
    context = render(
        f'{{"payload":"{value}","changed":1}}',
        f'{{"payload":"{value}","changed":2}}',
        View.FULL,
    )

    assert "<long string: 10000 code points>" in added
    assert "9905 code points omitted within excerpt" in added
    assert added.count("z") == REVIEW_EXCERPT_CELLS - 1
    assert "<long string: 10000 code points>" in context
    assert "9841 code points omitted within excerpt" in context
    assert context.count("z") == 159
    assert len(added) < 500
    assert len(context) < 500


def test_long_multiline_added_and_context_strings_are_also_bounded() -> None:
    value = "line\n" * 2_000
    added = render("{}", json.dumps({"payload": value}))
    context = render(
        json.dumps({"payload": value, "changed": 1}),
        json.dumps({"payload": value, "changed": 2}),
        View.FULL,
    )

    assert "<long string: 10000 code points>" in added
    assert "<long string: 10000 code points>" in context
    assert "code points omitted within excerpt" in added
    assert "code points omitted within excerpt" in context
    assert len(added) < 500
    assert len(context) < 500


@pytest.mark.parametrize(
    ("length", "bounded"),
    [
        (BLOB_HARD_CODE_POINT_LIMIT - 1, False),
        (BLOB_HARD_CODE_POINT_LIMIT, True),
        (BLOB_HARD_CODE_POINT_LIMIT + 1, True),
    ],
)
def test_added_string_boundaries(length: int, bounded: bool) -> None:
    value = ("z " * (length // 2 + 1))[:length]
    output = render("{}", f'{{"payload":"{value}"}}')
    assert ("<long string:" in output) is bounded


def test_long_identity_value_is_bounded_in_move_provenance() -> None:
    identity = "k" * 10_000
    output = render(
        f'[{{"id":"a"}},{{"id":"{identity}"}}]',
        f'[{{"id":"{identity}"}},{{"id":"a"}}]',
    )

    assert "moved from $[1] to $[0]" in output
    assert 'matched by "id": <long string: 10000 code points;' in output
    assert output.count("k") == (REVIEW_EXCERPT_CELLS - 1) * 2
    assert len(output) < 1_000


def test_marker_like_input_and_terminal_controls_are_escaped() -> None:
    marker_output = render('"literal [-old-]"', '"literal [+new+]"')
    assert "\\u005b" in marker_output
    assert "\\u005d" in marker_output
    assert "literal [-old-]" not in marker_output
    assert "literal [+new+]" not in marker_output

    control_output = render('"\\u001b[31m"', '"safe"')
    assert "\x1b" not in control_output
    assert "\\u001b" in control_output


def test_marker_like_keys_values_paths_and_move_evidence_are_escaped() -> None:
    identity_key = "[-id-]"
    container_key = "[+items+]"
    old_value = {
        container_key: [
            {identity_key: "[-a-]"},
            {identity_key: "[+b+]"},
        ],
        "context": "[-literal-]",
    }
    new_value = {
        container_key: [
            {identity_key: "[+b+]"},
            {identity_key: "[-a-]"},
        ],
        "context": "[-literal-]",
        "[+added+]": "[-value-]",
    }
    tree = build_diff(
        parse(json.dumps(old_value)),
        parse(json.dumps(new_value)),
        (identity_key,),
    )
    output = serialize_plain(render_diff(tree, View.FULL))

    for literal in (
        identity_key,
        container_key,
        "[-a-]",
        "[+b+]",
        "[-literal-]",
        "[+added+]",
        "[-value-]",
    ):
        assert literal not in output
    assert "\\u005b" in output
    assert "\\u005d" in output
    assert "moved from $" in output


@pytest.mark.parametrize(
    ("old", "new", "escaped"),
    [
        ('"prefix[-tail"', '"prefix[+tail"', "prefix\\u005b"),
        ('"tail-]suffix"', '"tail+]suffix"', "\\u005dsuffix"),
    ],
)
def test_marker_delimiters_are_safe_across_fragment_boundaries(
    old: str,
    new: str,
    escaped: str,
) -> None:
    assert escaped in render(old, new)


@pytest.mark.parametrize("code_point", ["007f", "0085", "009b", "2028", "2029"])
def test_controls_and_unicode_line_separators_are_json_escaped(
    code_point: str,
) -> None:
    output = render(f'"\\u{code_point}31m"', '"safe"')
    character = chr(int(code_point, 16))
    assert character not in output
    assert f"\\u{code_point}" in output


def test_surrogate_code_points_are_safe_for_utf8_output() -> None:
    output = render('"\\ud800"', '"safe"')
    assert "\\ud800" in output
    output.encode("utf-8")


def test_ansi_roles_wrap_plain_markers_without_changing_text() -> None:
    spans = render_diff(
        build_diff(
            parse('[{"id":"a","value":"old"}]'),
            parse('[{"id":"a","value":"new"}]'),
        ),
        View.REVIEW,
    )
    plain = serialize_plain(spans)
    colored = serialize_ansi(spans)
    assert "\x1b[33m" in colored
    assert "\x1b[31m" in colored
    assert "\x1b[32m" in colored
    assert _ANSI_PATTERN.sub("", colored) == plain
    assert "\x1b[0m\n" in colored
    assert "\n\x1b[0m" not in colored


def test_output_has_one_lf_and_no_trailing_spaces() -> None:
    output = render('{"a":1}', '{"a":2}')
    assert output.endswith("\n")
    assert not output.endswith("\n\n")
    assert all(not line.endswith(" ") for line in output.splitlines())
