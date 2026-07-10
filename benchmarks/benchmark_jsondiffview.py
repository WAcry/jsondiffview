"""Non-gating deterministic corpus benchmarks for jsondiffview."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from jsondiffview.color import serialize_plain
from jsondiffview.diff import build_diff
from jsondiffview.matching import match_array_with_stats
from jsondiffview.model import JsonValue, View
from jsondiffview.parser import decode_json_bytes, strict_equal
from jsondiffview.render import render_diff
from jsondiffview.strings import build_string_diff


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--size", type=int)
    arguments = parser.parse_args()
    size = arguments.size or (1_000 if arguments.quick else 10_000)

    cases: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        ("identity-array", lambda: _identity_array(size)),
        ("duplicate-array", lambda: _duplicate_array(size)),
        ("move-backbone", lambda: _move_backbone(size)),
        ("object-anchoring", lambda: _object_anchoring(size)),
        ("unicode-inline", _unicode_inline),
        ("multiline-window", lambda: _multiline(size)),
        ("opaque-blob", lambda: _opaque_blob(size)),
    ]
    for name, case in cases:
        tracemalloc.start()
        started = time.perf_counter()
        observations = case()
        elapsed = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        print(
            json.dumps(
                {
                    "case": name,
                    "elapsed_seconds_observation": round(elapsed, 6),
                    "peak_traced_bytes_observation": peak,
                    **observations,
                },
                sort_keys=True,
            )
        )
    return 0


def _identity_array(size: int) -> dict[str, Any]:
    old = _parse(json.dumps([{"id": index, "v": 1} for index in range(size)]))
    new = _parse(
        json.dumps(
            [{"id": -1, "v": 1}]
            + [
                {"id": index, "v": 2 if index == size // 2 else 1}
                for index in range(size)
            ]
        )
    )
    assert isinstance(old, list)
    assert isinstance(new, list)
    matches, stats = match_array_with_stats(old, new, ("id",))
    assert len(matches) == size
    assert sum(match.moved for match in matches) == 0
    return {
        "pairs": len(matches),
        "moves": 0,
        "counters": asdict(stats),
    }


def _duplicate_array(size: int) -> dict[str, Any]:
    old = _parse(json.dumps([index % 17 for index in range(size)]))
    new = _parse(json.dumps([index % 17 for index in range(1, size + 1)]))
    assert isinstance(old, list)
    assert isinstance(new, list)
    matches, stats = match_array_with_stats(old, new, ())
    assert all(
        strict_equal(old[match.old_index], new[match.new_index]) for match in matches
    )
    assert all(not match.moved for match in matches)
    return {
        "pairs": len(matches),
        "moves": 0,
        "counters": asdict(stats),
    }


def _move_backbone(size: int) -> dict[str, Any]:
    old = _parse(json.dumps(list(range(size))))
    new = _parse(json.dumps([*range(1, size), 0]))
    assert isinstance(old, list)
    assert isinstance(new, list)
    matches, stats = match_array_with_stats(old, new, ())
    assert len(matches) == size
    assert sum(match.moved for match in matches) == 1
    return {
        "pairs": len(matches),
        "moves": 1,
        "counters": asdict(stats),
    }


def _object_anchoring(size: int) -> dict[str, Any]:
    old_data = {f"key_{index:06d}": index for index in range(size)}
    new_data = {
        key: value
        for offset, (key, value) in enumerate(reversed(old_data.items()))
        if offset % 10 == 0
    }
    tree = build_diff(
        _parse(json.dumps(old_data)),
        _parse(json.dumps(new_data)),
    )
    output = serialize_plain(render_diff(tree, View.SUMMARY))
    return {
        "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
        "output_bytes": len(output.encode()),
    }


def _unicode_inline() -> dict[str, Any]:
    result = build_string_diff(
        "family 👨‍👩‍👧‍👦 release candidate café",
        "family 👨‍👩‍👧‍👦 release canrevate cafe\u0301",
    )
    return {"analysis_type": type(result).__name__}


def _multiline(size: int) -> dict[str, Any]:
    line_count = min(size, 10_000)
    old = "\n".join(
        f"service-{index}: old" if index % 257 == 0 else f"service-{index}: stable"
        for index in range(line_count)
    )
    new = "\n".join(
        f"service-{index}: new" if index % 257 == 0 else f"service-{index}: stable"
        for index in range(line_count)
    )
    result = build_string_diff(old, new)
    return {"analysis_type": type(result).__name__, "logical_lines": line_count}


def _opaque_blob(size: int) -> dict[str, Any]:
    length = max(size, 512)
    result = build_string_diff(
        "A" * (length // 2) + "OLD" + "B" * (length // 2),
        "A" * (length // 2) + "NEW" + "B" * (length // 2),
    )
    return {"analysis_type": type(result).__name__, "code_points": length * 2 + 6}


def _parse(text: str) -> JsonValue:
    return decode_json_bytes(text.encode(), "benchmark.json")


if __name__ == "__main__":
    raise SystemExit(main())
