from __future__ import annotations

import json
from pathlib import Path

import pytest

from jdv.diff import diff_json
from jdv.layout import build_display_layout
from jdv.model import ColorMode, DiffSettings, ReviewMode
from jdv.render import render_review_view


FIXTURES_DIR = Path(__file__).parent / "fixtures"
EXPECTED_DIR = FIXTURES_DIR / "expected"


@pytest.mark.parametrize(
    ("view", "old_name", "new_name", "expected_name"),
    [
        (ReviewMode.COMPACT, "compact-move-edit-old.json", "compact-move-edit-new.json", "compact_move_edit.txt"),
        (ReviewMode.FOCUS, "focus-pure-add-old.json", "focus-pure-add-new.json", "focus_pure_add.txt"),
        (ReviewMode.FULL, "full-move-edit-old.json", "full-move-edit-new.json", "full_move_edit.txt"),
        (ReviewMode.COMPACT, "exact-value-move-old.json", "exact-value-move-new.json", "exact_value_move.txt"),
        (ReviewMode.COMPACT, "multiline-string-old.json", "multiline-string-new.json", "multiline_block.txt"),
        (ReviewMode.COMPACT, "string-inline-word-old.json", "string-inline-word-new.json", "string_inline_word_replace.txt"),
        (ReviewMode.COMPACT, "string-inline-micro-old.json", "string-inline-micro-new.json", "string_inline_microdiff.txt"),
        (ReviewMode.COMPACT, "string-blob-old.json", "string-blob-new.json", "string_blob_compact.txt"),
        (ReviewMode.FULL, "string-blob-old.json", "string-blob-new.json", "string_blob_full.txt"),
        (ReviewMode.COMPACT, "root-string-multiline-old.json", "root-string-multiline-new.json", "root_string_multiline.txt"),
        (
            ReviewMode.COMPACT,
            "string-block-trailing-comma-old.json",
            "string-block-trailing-comma-new.json",
            "string_block_trailing_comma.txt",
        ),
        (ReviewMode.COMPACT, "complex-anchor-old.json", "complex-anchor-new.json", "complex_anchor.txt"),
        (ReviewMode.COMPACT, "root-replace-old.json", "root-replace-new.json", "root_replace.txt"),
    ],
)
def test_render_snapshot(view: ReviewMode, old_name: str, new_name: str, expected_name: str) -> None:
    old_value = _load_json(FIXTURES_DIR / old_name)
    new_value = _load_json(FIXTURES_DIR / new_name)
    expected = _read_text(EXPECTED_DIR / expected_name)

    root = diff_json(old_value, new_value, DiffSettings())
    plan = build_display_layout(root, view, DiffSettings())
    actual = render_review_view(plan, ColorMode.NEVER)

    assert actual == expected


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n")
