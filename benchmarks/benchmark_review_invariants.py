"""Non-gating regression measurements, runnable against old and new sources.

Parsing and tree construction are excluded from rendering measurements.
Elapsed time is a median of untraced repeats; peak allocation is measured
separately. Nothing in the product or tests depends on these timings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import time
import tracemalloc
from collections.abc import Callable
from typing import Any

from jsondiffview.color import serialize_plain
from jsondiffview.diff import build_diff
from jsondiffview.matching import match_array
from jsondiffview.model import JsonValue, View
from jsondiffview.parser import decode_json_bytes
from jsondiffview.render import render_diff
from jsondiffview.strings import bounded_excerpt


def _positive_int(value: str) -> int:
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def _prepare(case: str, size: int) -> Callable[[], dict[str, Any]]:
    if case == "full-context":
        stable = {f"key_{index:06d}": index for index in range(size)}
        tree = build_diff(
            _parse({"stable": stable, "flag": False}),
            _parse({"stable": stable, "flag": True}),
        )

        def render() -> dict[str, Any]:
            output = serialize_plain(render_diff(tree, View.FULL)).encode()
            return {
                "output_bytes": len(output),
                "output_sha256": hashlib.sha256(output).hexdigest(),
            }

        return render
    if case == "mixed-duplicates":
        old: list[JsonValue] = ["anchor", *(["repeat"] * size)]
        new: list[JsonValue] = ["repeat", "anchor", *(["repeat"] * (size - 1))]

        def match() -> dict[str, Any]:
            matches = match_array(old, new, ())
            return {
                "pairs": len(matches),
                "trusted_moves": sum(item.moved for item in matches),
            }

        return match
    text = "e" + "\u0301" * size

    def excerpt() -> dict[str, Any]:
        result = bounded_excerpt(text)
        return {"excerpt_code_points": len(result.text), "omitted": result.omitted}

    return excerpt


def _parse(value: object) -> JsonValue:
    return decode_json_bytes(json.dumps(value).encode(), "benchmark.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        choices=["full-context", "mixed-duplicates", "zero-width"],
        default="full-context",
    )
    parser.add_argument("--size", type=_positive_int, default=16_000)
    parser.add_argument("--repeat", type=_positive_int, default=5)
    parser.add_argument("--label", default="working-tree")
    arguments = parser.parse_args()
    measure = _prepare(arguments.case, arguments.size)
    observations = measure()  # Warm up imports/caches, outside the sample.
    samples: list[float] = []
    for _ in range(arguments.repeat):
        started = time.perf_counter()
        current = measure()
        samples.append(time.perf_counter() - started)
        assert current == observations, "non-deterministic benchmark result"
    tracemalloc.start()
    measure()
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        json.dumps(
            {
                "label": arguments.label,
                "case": arguments.case,
                "size": arguments.size,
                "repeat": arguments.repeat,
                "python": platform.python_version(),
                "platform": platform.system(),
                "median_seconds_observation": round(statistics.median(samples), 6),
                "peak_traced_bytes_observation": peak,
                **observations,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
