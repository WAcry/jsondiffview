from __future__ import annotations

from collections.abc import Mapping, Sequence

from .types import DiffKind, DiffNode, JsonValue


def diff_values(path: str, left: JsonValue, right: JsonValue) -> DiffNode:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return _diff_object(path, left, right)
    if _is_list(left) and _is_list(right):
        return _diff_array(path, left, right)
    if _json_scalars_equal(left, right):
        return DiffNode(path=path, kind=DiffKind.UNCHANGED, left=left, right=right)
    return DiffNode(path=path, kind=DiffKind.REPLACED, left=left, right=right)


def _diff_object(path: str, left: Mapping[str, JsonValue], right: Mapping[str, JsonValue]) -> DiffNode:
    children: list[DiffNode] = []
    for key in sorted(set(left) | set(right)):
        child_path = _append_object_path(path, key)
        if key not in left:
            children.append(
                DiffNode(path=child_path, kind=DiffKind.ADDED, right=right[key])
            )
            continue
        if key not in right:
            children.append(
                DiffNode(path=child_path, kind=DiffKind.REMOVED, left=left[key])
            )
            continue
        children.append(diff_values(child_path, left[key], right[key]))

    return DiffNode(
        path=path,
        kind=DiffKind.OBJECT,
        left=dict(left),
        right=dict(right),
        children=tuple(children),
    )


def _diff_array(path: str, left: list[JsonValue], right: list[JsonValue]) -> DiffNode:
    children: list[DiffNode] = []
    max_length = max(len(left), len(right))
    for index in range(max_length):
        child_path = _append_array_path(path, index)
        if index >= len(left):
            children.append(
                DiffNode(path=child_path, kind=DiffKind.ADDED, right=right[index])
            )
            continue
        if index >= len(right):
            children.append(
                DiffNode(path=child_path, kind=DiffKind.REMOVED, left=left[index])
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
    if not base_path:
        return key
    return f"{base_path}.{key}"


def _append_array_path(base_path: str, index: int) -> str:
    return f"{base_path}[{index}]"


def _is_list(value: JsonValue) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _json_scalars_equal(left: JsonValue, right: JsonValue) -> bool:
    if left is right:
        return True
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if _is_number(left) and _is_number(right):
        return left == right
    return type(left) is type(right) and left == right


def _is_number(value: JsonValue) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
