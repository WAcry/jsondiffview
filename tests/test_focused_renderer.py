from json_diff_cli.diff_engine import diff_values
from json_diff_cli.renderers.focused import render_focused, _select_context_lines


def diff_node_for(left, right):
    return diff_values("", left, right)


def test_focused_renderer_emits_only_leaf_replacements_and_added_subtrees():
    rendered = render_focused(
        diff_node_for(
            {"demographics": {"population": 1}},
            {"demographics": {"population": 2, "timezone": [-4, -3]}},
        ),
        color="never",
        context_lines=0,
    )

    blocks = rendered.split("\n\n")

    assert len(blocks) == 2
    assert blocks[0].splitlines()[0] == "demographics.population"
    assert '[-1-]' in blocks[0]
    assert '[+2+]' in blocks[0]
    assert blocks[1].splitlines()[0] == "demographics.timezone"
    assert '"population"' not in blocks[1]


def test_focused_renderer_keeps_leaf_scoped_blocks_with_context_lines():
    rendered = render_focused(
        diff_node_for(
            {"demographics": {"population": 1}},
            {"demographics": {"population": 2, "timezone": [-4, -3]}},
        ),
        color="never",
        context_lines=1,
    )

    blocks = rendered.split("\n\n")

    assert len(blocks) == 2
    assert blocks[0].splitlines()[0] == "demographics.population"
    assert blocks[1].splitlines()[0] == "demographics.timezone"
    assert blocks[0].splitlines()[0] != "demographics"
    assert blocks[1].splitlines()[0] != "demographics"


def test_focused_renderer_sort_keys_reorders_focused_block_fields():
    rendered = render_focused(
        diff_node_for(
            {"b": 1, "a": 2},
            {"b": 3, "a": 4},
        ),
        color="never",
        context_lines=1,
        sort_keys=True,
    )

    assert rendered.index("a\n[-2-][+4+]") < rendered.index("b\n[-1-][+3+]")


def test_focused_renderer_preserves_object_closing_delimiter_with_context_lines():
    rendered = render_focused(
        diff_node_for(
            {"unchanged": 1},
            {"unchanged": 1, "details": {"a": 1, "b": 2}},
        ),
        color="never",
        context_lines=1,
    )

    lines = rendered.splitlines()

    assert lines[0] == "details"
    assert lines[1] == "[+{"
    assert lines[-1] == "}+]"


def test_focused_renderer_preserves_array_closing_delimiter_with_context_lines():
    rendered = render_focused(
        diff_node_for(
            {"unchanged": 1},
            {"unchanged": 1, "items": [1, 2, 3]},
        ),
        color="never",
        context_lines=1,
    )

    lines = rendered.splitlines()

    assert lines[0] == "items"
    assert lines[1] == "[+["
    assert lines[-1] == "]+]"


def test_select_context_lines_ignores_unchanged_literal_marker_strings():
    selected = _select_context_lines(
        [
            "{",
            '  "note": "[+literal+]",',
            '  "value": [-1-][+2+],',
            '  "tail": 3',
            "}",
        ],
        changed_indexes=[2],
        context_lines=0,
    )

    assert selected == [
        "{",
        '  "value": [-1-][+2+],',
        "}",
    ]
