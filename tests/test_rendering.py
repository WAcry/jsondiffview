from __future__ import annotations

from jdv.diff import diff_json
from jdv.layout import build_display_layout
from jdv.model import ColorMode, DiffSettings, ReviewMode
from jdv.render import render_review_view


def test_compact_view_collapses_unchanged_and_keeps_move_note() -> None:
    old_value = {
        "items": [
            {"id": "a", "name": "candidate", "legacy": True, "kind": "service", "owner": "team-a"},
            {"id": "b", "name": "beta", "v": 2},
            {"id": "c", "name": "charlie", "v": 3},
        ],
        "env": "prod",
        "generated_by": "sync",
    }
    new_value = {
        "items": [
            {"id": "b", "name": "beta", "v": 2},
            {"id": "c", "name": "charlie", "v": 3},
            {"id": "a", "name": "canrevate", "active": True, "kind": "service", "owner": "team-a"},
        ],
        "env": "prod",
        "generated_by": "sync",
    }

    text = _render(old_value, new_value, ReviewMode.COMPACT)

    assert "… 2 unchanged items" in text
    assert '> moved $.items[0] -> $.items[2] (id="a")' in text
    assert '~ "name": "can[-did-][+rev+]ate"' in text
    assert '- "legacy": true' in text
    assert '+ "active": true' in text


def test_focus_view_shows_full_change_material() -> None:
    old_value = {"meta": {"a": 1, "b": 2, "c": 3}, "env": "prod"}
    new_value = {"meta": {"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}, "env": "prod"}

    text = _render(old_value, new_value, ReviewMode.FOCUS)

    assert '+ "d": 4' in text
    assert '+ "e": 5' in text
    assert "… 3 unchanged keys" in text


def test_full_view_expands_same_diff() -> None:
    old_value = {"items": [{"id": "a", "v": 1}, {"id": "b", "v": 2}]}
    new_value = {"items": [{"id": "b", "v": 2}, {"id": "a", "v": 3}]}

    text = _render(old_value, new_value, ReviewMode.FULL)

    assert '"id": "b"' in text
    assert '> moved $.items[0] -> $.items[1] (id="a")' in text
    assert '~ "v": 1 -> 3' in text


def test_exact_value_move_snapshot() -> None:
    old_value = {"items": [{"x": 1}, {"y": 2}]}
    new_value = {"items": [{"y": 2}, {"x": 1}]}

    text = _render(old_value, new_value, ReviewMode.COMPACT)

    assert '> moved $.items[0] -> $.items[1] (exact value)' in text
    assert '"y": 2' in text
    assert '"x": 1' in text


def test_root_replace_snapshot() -> None:
    old_value = {"feature_flags": {"legacy": True}}
    new_value = ["preview"]

    text = _render(old_value, new_value, ReviewMode.COMPACT)

    assert text.startswith("~ $")
    assert "- {" in text
    assert '+ "preview"' in text


def _render(old_value, new_value, review_mode: ReviewMode) -> str:
    root = diff_json(old_value, new_value, DiffSettings())
    plan = build_display_layout(root, review_mode, DiffSettings())
    return render_review_view(plan, ColorMode.NEVER)
