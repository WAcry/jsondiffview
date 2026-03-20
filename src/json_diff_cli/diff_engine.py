from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from .types import DiffKind, DiffNode, JsonValue


def diff_values(path: str, left: JsonValue, right: JsonValue) -> DiffNode:
    if _json_values_equal(left, right):
        return DiffNode(
            path=path,
            kind=DiffKind.UNCHANGED,
            left=left,
            right=right,
            children=_empty_children_for(left),
        )
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return _diff_object(path, left, right)
    if _is_list(left) and _is_list(right):
        return _diff_array(path, left, right)
    return DiffNode(
        path=path,
        kind=DiffKind.REPLACED,
        left=left,
        right=right,
        children={},
    )


def _diff_object(path: str, left: Mapping[str, JsonValue], right: Mapping[str, JsonValue]) -> DiffNode:
    children: dict[str, DiffNode] = {}
    for key in _iter_object_keys(left, right):
        child_path = _append_object_path(path, key)
        if key not in left:
            children[key] = DiffNode(
                path=child_path,
                kind=DiffKind.ADDED,
                right=right[key],
                children={},
            )
            continue
        if key not in right:
            children[key] = DiffNode(
                path=child_path,
                kind=DiffKind.REMOVED,
                left=left[key],
                children={},
            )
            continue
        children[key] = diff_values(child_path, left[key], right[key])

    return DiffNode(
        path=path,
        kind=DiffKind.OBJECT,
        left=dict(left),
        right=dict(right),
        children=children,
    )


def _diff_array(path: str, left: list[JsonValue], right: list[JsonValue]) -> DiffNode:
    children: list[DiffNode] = []
    max_length = max(len(left), len(right))
    for index in range(max_length):
        child_path = _append_array_path(path, index)
        if index >= len(left):
            children.append(
                DiffNode(
                    path=child_path,
                    kind=DiffKind.ADDED,
                    right=right[index],
                    children={},
                )
            )
            continue
        if index >= len(right):
            children.append(
                DiffNode(
                    path=child_path,
                    kind=DiffKind.REMOVED,
                    left=left[index],
                    children={},
                )
            )
            continue
        children.append(diff_values(child_path, left[index], right[index]))

    return DiffNode(
        path=path,
        kind=DiffKind.ARRAY,
        left=list(left),
        right=list(right),
        children=tuple(children),
    )


def _append_object_path(base_path: str, key: str) -> str:
    if _needs_path_escape(key):
        escaped_key = json.dumps(key, ensure_ascii=False)
        return f"{base_path}[{escaped_key}]" if base_path else f"[{escaped_key}]"
    if not base_path:
        return key
    return f"{base_path}.{key}"


def _append_array_path(base_path: str, index: int) -> str:
    return f"{base_path}[{index}]"


def _is_list(value: JsonValue) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _json_values_equal(left: JsonValue, right: JsonValue) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return dict(left) == dict(right)
    if _is_list(left) and _is_list(right):
        return list(left) == list(right)
    if left is right:
        return True
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if _is_number(left) and _is_number(right):
        return left == right
    return type(left) is type(right) and left == right


def _is_number(value: JsonValue) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _empty_children_for(value: JsonValue) -> dict[str, DiffNode] | tuple[DiffNode, ...]:
    if isinstance(value, Mapping):
        return {}
    if _is_list(value):
        return ()
    return {}


def _iter_object_keys(
    left: Mapping[str, JsonValue],
    right: Mapping[str, JsonValue],
) -> list[str]:
    ordered_keys: list[str] = []
    seen: set[str] = set()

    for source in (left, right):
        for key in source:
            if key in seen:
                continue
            seen.add(key)
            ordered_keys.append(key)

    return ordered_keys


def _needs_path_escape(key: str) -> bool:
    return any(char in key for char in ".[]")
