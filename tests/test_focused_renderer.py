from json_diff_cli.diff_engine import diff_values
from json_diff_cli.renderers.focused import render_focused


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


def test_focused_renderer_unions_context_windows():
    rendered = render_focused(
        diff_node_for(
            {"a": 1, "b": 2, "c": 3, "d": 4},
            {"a": 9, "b": 2, "c": 8, "d": 4},
        ),
        color="never",
        context_lines=1,
    )

    blocks = rendered.split("\n\n")

    assert len(blocks) == 1
    assert blocks[0].splitlines()[0] == ""
    assert '"a": [-1-][+9+],' in blocks[0]
    assert '"b": 2,' in blocks[0]
    assert '"c": [-3-][+8+],' in blocks[0]


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

    assert rendered.index('"a": [-2-][+4+],') < rendered.index('"b": [-1-][+3+]')


def test_focused_renderer_preserves_object_closing_delimiter_with_context_lines():
    rendered = render_focused(
        diff_node_for(
            {"a": 1, "b": 2, "c": 3, "d": 4},
            {"a": 9, "b": 8, "c": 3, "d": 4},
        ),
        color="never",
        context_lines=1,
    )

    lines = rendered.splitlines()

    assert lines[0] == ""
    assert lines[1] == "{"
    assert lines[-1] == "}"


def test_focused_renderer_preserves_array_closing_delimiter_with_context_lines():
    rendered = render_focused(
        diff_node_for(
            [1, 2, 3, 4],
            [9, 8, 3, 4],
        ),
        color="never",
        context_lines=1,
    )

    lines = rendered.splitlines()

    assert lines[0] == ""
    assert lines[1] == "["
    assert lines[-1] == "]"
