from json_diff_cli.diff_engine import diff_values
from json_diff_cli.renderers.changed import render_changed


def diff_node_for(left, right):
    return diff_values("", left, right)


def test_changed_renderer_emits_leaf_blocks_only():
    rendered = render_changed(
        diff_node_for(
            {"demographics": {"population": 1}},
            {"demographics": {"population": 2, "timezone": [-4, -3]}},
        ),
        color="never",
    )

    blocks = rendered.split("\n\n")

    assert len(blocks) == 2
    assert blocks[0].splitlines()[0] == "demographics.population (replace)"
    assert blocks[1].splitlines()[0] == "demographics.timezone (add)"


def test_changed_renderer_does_not_emit_parent_container_snippets():
    rendered = render_changed(
        diff_node_for({"a": {"b": 1}}, {"a": {"b": 2}}),
        color="never",
    )

    assert rendered.splitlines()[0] == "a.b (replace)"
    assert "{\n" not in rendered
