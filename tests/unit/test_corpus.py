from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsondiffview.matching import match_array
from jsondiffview.model import JsonValue
from jsondiffview.parser import decode_json_bytes
from jsondiffview.strings import StringMode, classify_string_mode

CORPUS = Path(__file__).parents[1] / "corpus"


def test_labeled_string_mode_corpus() -> None:
    for record in _records(CORPUS / "string_cases.jsonl"):
        mode = classify_string_mode(record["old"], record["new"])
        assert mode is StringMode(record["expected_mode"]), record["id"]
        assert record["rationale"]


def test_labeled_array_matching_corpus() -> None:
    for record in _records(CORPUS / "array_cases.jsonl"):
        old = _parse(record["old_json"])
        new = _parse(record["new_json"])
        assert isinstance(old, list)
        assert isinstance(new, list)
        matches = match_array(old, new, tuple(record["keys"]))
        assert [[match.old_index, match.new_index] for match in matches] == record[
            "expected_pairs"
        ], record["id"]
        assert [
            [match.old_index, match.new_index] for match in matches if match.moved
        ] == record["expected_moves"], record["id"]
        assert record["rationale"]


def _records(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _parse(text: str) -> JsonValue:
    return decode_json_bytes(text.encode(), "corpus.json")
