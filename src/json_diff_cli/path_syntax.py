from __future__ import annotations

import json


def append_object_path(base_path: str, key: str) -> str:
    if needs_path_escape(key):
        escaped_key = json.dumps(key, ensure_ascii=False)
        return f"{base_path}[{escaped_key}]" if base_path else f"[{escaped_key}]"
    if not base_path:
        return key
    return f"{base_path}.{key}"


def needs_path_escape(key: str) -> bool:
    return not key.isidentifier()
