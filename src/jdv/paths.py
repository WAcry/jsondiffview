from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any


SAFE_OBJECT_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def format_display_path(path: tuple[str | int, ...]) -> str:
    result = "$"
    for part in path:
        if isinstance(part, int):
            result += f"[{part}]"
            continue
        if SAFE_OBJECT_KEY_RE.match(part):
            result += f".{part}"
            continue
        result += f"[{json.dumps(part, ensure_ascii=False)}]"
    return result


def format_identity_label(field_name: str, value: Any) -> str:
    return f"{field_name}={render_json_scalar(value)}"


def canonical_json(value: Any) -> str:
    return json.dumps(
        _canonicalize(value),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def pretty_json_lines(value: Any) -> list[str]:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        indent=2,
        sort_keys=False,
    )
    return rendered.splitlines() or [rendered]


def render_json_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("identity labels must not contain non-finite numbers")
        return json.dumps(value, allow_nan=False)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_string_fragment(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)[1:-1]


def _canonicalize(value: Any) -> Any:
    if value is None:
        return ["null"]
    if value is True:
        return ["bool", True]
    if value is False:
        return ["bool", False]
    if isinstance(value, int) and not isinstance(value, bool):
        return ["int", str(value)]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical_json() does not accept non-finite numbers")
        return ["float", json.dumps(value, allow_nan=False)]
    if isinstance(value, str):
        return ["string", value]
    if isinstance(value, list):
        return ["array", [_canonicalize(item) for item in value]]
    if isinstance(value, dict):
        return [
            "object",
            [[key, _canonicalize(value[key])] for key in sorted(value.keys())],
        ]
    raise TypeError(f"Unsupported JSON value type: {type(value)!r}")
