from __future__ import annotations

from collections.abc import Mapping, Sequence

from .errors import UserInputError
from .matcher import (
    build_object_identity,
    canonical_object_path,
    canonical_primitive_path,
    object_key_candidates,
    resolve_object_key_rule,
)
from .path_syntax import append_object_path
from .text_diff import TextDiff, diff_strings
from .types import DiffKind, DiffNode, JsonValue, MatchInfo, MatchRuleSet


def diff_values(
    path: str,
    left: JsonValue,
    right: JsonValue,
    *,
    array_mode: str = "position",
    match_rules: MatchRuleSet | None = None,
) -> DiffNode:
    effective_rules = match_rules or _empty_match_rules()

    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return _diff_object(
            path,
            left,
            right,
            array_mode=array_mode,
            match_rules=effective_rules,
        )
    if _is_list(left) and _is_list(right):
        return _diff_array(
            path,
            list(left),
            list(right),
            array_mode=array_mode,
            match_rules=effective_rules,
        )
    if _json_values_equal(left, right):
        return DiffNode(
            path=path,
            kind=DiffKind.UNCHANGED,
            left=left,
            right=right,
            children=_empty_children_for(left),
        )
    return DiffNode(
        path=path,
        kind=DiffKind.REPLACED,
        left=left,
        right=right,
        children={},
        text_diff=_build_text_diff(left, right),
    )


def _diff_object(
    path: str,
    left: Mapping[str, JsonValue],
    right: Mapping[str, JsonValue],
    *,
    array_mode: str,
    match_rules: MatchRuleSet,
) -> DiffNode:
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
        children[key] = diff_values(
            child_path,
            left[key],
            right[key],
            array_mode=array_mode,
            match_rules=match_rules,
        )

    if all(child.kind is DiffKind.UNCHANGED for child in children.values()):
        return DiffNode(
            path=path,
            kind=DiffKind.UNCHANGED,
            left=dict(left),
            right=dict(right),
            children={},
        )

    return DiffNode(
        path=path,
        kind=DiffKind.OBJECT,
        left=dict(left),
        right=dict(right),
        children=children,
    )


def _diff_array(
    path: str,
    left: list[JsonValue],
    right: list[JsonValue],
    *,
    array_mode: str,
    match_rules: MatchRuleSet,
) -> DiffNode:
    if array_mode == "smart":
        return _diff_array_smart(path, left, right, match_rules)
    if _json_values_equal(left, right):
        return DiffNode(
            path=path,
            kind=DiffKind.UNCHANGED,
            left=list(left),
            right=list(right),
            children=(),
        )
    return _diff_array_positionally(path, left, right, array_mode=array_mode, match_rules=match_rules)


def _diff_array_positionally(
    path: str,
    left: list[JsonValue],
    right: list[JsonValue],
    *,
    array_mode: str,
    match_rules: MatchRuleSet,
) -> DiffNode:
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
        children.append(
            diff_values(
                child_path,
                left[index],
                right[index],
                array_mode=array_mode,
                match_rules=match_rules,
            )
        )

    return DiffNode(
        path=path,
        kind=DiffKind.ARRAY,
        left=list(left),
        right=list(right),
        children=tuple(children),
    )


def _diff_array_smart(
    path: str,
    left: list[JsonValue],
    right: list[JsonValue],
    match_rules: MatchRuleSet,
) -> DiffNode:
    candidates = object_key_candidates(path, match_rules)
    merged_items: list[object] = [*left, *right]
    if not merged_items:
        return DiffNode(
            path=path,
            kind=DiffKind.UNCHANGED,
            left=list(left),
            right=list(right),
            children=(),
        )

    if _is_primitive_array(merged_items):
        if _json_values_equal(left, right):
            return DiffNode(
                path=path,
                kind=DiffKind.UNCHANGED,
                left=list(left),
                right=list(right),
                children=(),
            )
        return _diff_primitive_array_by_value(path, left, right)

    if not all(isinstance(item, Mapping) for item in merged_items):
        if candidates:
            raise UserInputError(f"Match rule for '{path}' requires object items")
        if _json_values_equal(left, right):
            return DiffNode(
                path=path,
                kind=DiffKind.UNCHANGED,
                left=list(left),
                right=list(right),
                children=(),
            )
        return _diff_array_positionally(
            path,
            left,
            right,
            array_mode="smart",
            match_rules=match_rules,
        )

    keys = resolve_object_key_rule(path, merged_items, match_rules)
    if keys is None:
        if _json_values_equal(left, right):
            return DiffNode(
                path=path,
                kind=DiffKind.UNCHANGED,
                left=list(left),
                right=list(right),
                children=(),
            )
        return _diff_array_positionally(
            path,
            left,
            right,
            array_mode="smart",
            match_rules=match_rules,
        )
    return _diff_object_array_by_identity(
        path,
        left,
        right,
        keys,
        array_mode="smart",
        match_rules=match_rules,
    )


def _diff_primitive_array_by_value(
    path: str,
    left: list[JsonValue],
    right: list[JsonValue],
) -> DiffNode:
    left_index, left_order = _index_primitive_items(path, left)
    right_index, right_order = _index_primitive_items(path, right)
    ordered_identities = _merge_identity_order(left_order, right_order)

    children: list[DiffNode] = []
    for identity in ordered_identities:
        _, occurrence = identity
        if identity in left_index:
            value = left_index[identity]
        else:
            value = right_index[identity]
        child_path = canonical_primitive_path(path, value, occurrence)
        if identity not in left_index:
            children.append(
                DiffNode(
                    path=child_path,
                    kind=DiffKind.ADDED,
                    right=right_index[identity],
                    children={},
                    match_info=MatchInfo(
                        mode="primitive-smart",
                        identity_values=(value,),
                        occurrence=occurrence,
                    ),
                )
            )
            continue
        if identity not in right_index:
            children.append(
                DiffNode(
                    path=child_path,
                    kind=DiffKind.REMOVED,
                    left=left_index[identity],
                    children={},
                    match_info=MatchInfo(
                        mode="primitive-smart",
                        identity_values=(value,),
                        occurrence=occurrence,
                    ),
                )
            )
            continue
        child_node = diff_values(
            child_path,
            left_index[identity],
            right_index[identity],
            array_mode="smart",
            match_rules=_empty_match_rules(),
        )
        children.append(
            _with_match_info(
                child_node,
                MatchInfo(
                    mode="primitive-smart",
                    identity_values=(value,),
                    occurrence=occurrence,
                ),
            )
        )

    return DiffNode(
        path=path,
        kind=DiffKind.ARRAY,
        left=list(left),
        right=list(right),
        children=tuple(children),
    )


def _diff_object_array_by_identity(
    path: str,
    left: list[JsonValue],
    right: list[JsonValue],
    keys: list[str],
    *,
    array_mode: str,
    match_rules: MatchRuleSet,
) -> DiffNode:
    left_index, left_order = _index_object_items(path, left, keys)
    right_index, right_order = _index_object_items(path, right, keys)
    if _json_values_equal(left, right):
        return DiffNode(
            path=path,
            kind=DiffKind.UNCHANGED,
            left=list(left),
            right=list(right),
            children=(),
        )
    ordered_identities = _merge_identity_order(left_order, right_order)

    children: list[DiffNode] = []
    for identity in ordered_identities:
        identity_keys = [key for key, _ in identity]
        identity_values = [value for _, value in identity]
        child_path = canonical_object_path(path, identity_keys, identity_values)
        if identity not in left_index:
            children.append(
                DiffNode(
                    path=child_path,
                    kind=DiffKind.ADDED,
                    right=right_index[identity],
                    children={},
                    match_info=MatchInfo(
                        mode="object-smart",
                        identity_keys=tuple(identity_keys),
                        identity_values=tuple(identity_values),
                    ),
                )
            )
            continue
        if identity not in right_index:
            children.append(
                DiffNode(
                    path=child_path,
                    kind=DiffKind.REMOVED,
                    left=left_index[identity],
                    children={},
                    match_info=MatchInfo(
                        mode="object-smart",
                        identity_keys=tuple(identity_keys),
                        identity_values=tuple(identity_values),
                    ),
                )
            )
            continue
        child_node = diff_values(
            child_path,
            left_index[identity],
            right_index[identity],
            array_mode=array_mode,
            match_rules=match_rules,
        )
        children.append(
            _with_match_info(
                child_node,
                MatchInfo(
                    mode="object-smart",
                    identity_keys=tuple(identity_keys),
                    identity_values=tuple(identity_values),
                ),
            )
        )

    return DiffNode(
        path=path,
        kind=DiffKind.ARRAY,
        left=list(left),
        right=list(right),
        children=tuple(children),
    )


def _validate_object_match_items(
    path: str,
    items: list[object],
    keys: list[str],
) -> None:
    for item in items:
        if not isinstance(item, Mapping):
            raise UserInputError(f"Match rule for '{path}' requires object items")
        try:
            build_object_identity(item, keys)
        except UserInputError as exc:
            raise UserInputError(f"Invalid match rule for '{path}': {exc}") from exc


def _index_primitive_items(
    path: str,
    items: list[JsonValue],
) -> tuple[dict[tuple[object, int], JsonValue], list[tuple[object, int]]]:
    counts: dict[object, int] = {}
    indexed: dict[tuple[object, int], JsonValue] = {}
    order: list[tuple[object, int]] = []

    for item in items:
        scalar_identity = _scalar_identity(item)
        occurrence = counts.get(scalar_identity, 0)
        counts[scalar_identity] = occurrence + 1
        identity = (scalar_identity, occurrence)
        if identity in indexed:
            raise UserInputError(f"Duplicate primitive identity at {canonical_primitive_path(path, item, occurrence)}")
        indexed[identity] = item
        order.append(identity)

    return indexed, order


def _index_object_items(
    path: str,
    items: list[JsonValue],
    keys: list[str],
) -> tuple[
    dict[tuple[tuple[str, object], ...], JsonValue],
    list[tuple[tuple[str, object], ...]],
]:
    indexed: dict[tuple[tuple[str, object], ...], JsonValue] = {}
    order: list[tuple[tuple[str, object], ...]] = []

    for item in items:
        if not isinstance(item, Mapping):
            raise UserInputError(f"Match rule for '{path}' requires object items")
        try:
            identity = build_object_identity(item, keys)
        except UserInputError as exc:
            raise UserInputError(f"Invalid match rule for '{path}': {exc}") from exc
        identity_values = [value for _, value in identity]
        child_path = canonical_object_path(path, keys, identity_values)
        if identity in indexed:
            raise UserInputError(f"Duplicate object identity at {child_path}")
        indexed[identity] = item
        order.append(identity)

    return indexed, order


def _merge_identity_order(
    left_order: Sequence[object],
    right_order: Sequence[object],
) -> list[object]:
    ordered: list[object] = []
    seen: set[object] = set()

    for source in (left_order, right_order):
        for identity in source:
            if identity in seen:
                continue
            seen.add(identity)
            ordered.append(identity)

    return ordered


def _append_object_path(base_path: str, key: str) -> str:
    return append_object_path(base_path, key)


def _append_array_path(base_path: str, index: int) -> str:
    return f"{base_path}[{index}]"


def _is_list(value: JsonValue) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _is_primitive_array(items: Sequence[JsonValue]) -> bool:
    return all(_is_json_scalar(item) for item in items)


def _json_values_equal(left: JsonValue, right: JsonValue) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if len(left) != len(right):
            return False
        for key, left_value in left.items():
            if key not in right:
                return False
            if not _json_values_equal(left_value, right[key]):
                return False
        return True
    if _is_list(left) and _is_list(right):
        if len(left) != len(right):
            return False
        return all(
            _json_values_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    if left is right:
        return True
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if _is_number(left) and _is_number(right):
        return left == right
    return type(left) is type(right) and left == right


def _is_number(value: JsonValue) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_json_scalar(value: JsonValue) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _scalar_identity(value: JsonValue) -> object:
    if _is_number(value):
        return ("number", value)
    return (type(value), value)


def _empty_match_rules() -> MatchRuleSet:
    return MatchRuleSet(cli_global_keys=[], yaml_global_keys=[], yaml_path_keys={})


def _build_text_diff(left: JsonValue, right: JsonValue) -> TextDiff | None:
    if not isinstance(left, str) or not isinstance(right, str):
        return None
    return TextDiff(diff_strings(left, right))


def _with_match_info(node: DiffNode, match_info: MatchInfo) -> DiffNode:
    return DiffNode(
        path=node.path,
        kind=node.kind,
        left=node.left,
        right=node.right,
        children=node.children,
        text_diff=node.text_diff,
        display_path=node.display_path,
        match_info=match_info,
    )


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
