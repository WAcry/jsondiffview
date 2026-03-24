from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from .match import match_array_items
from .model import (
    DiffNode,
    DiffSettings,
    DiffStatus,
    MoveBasis,
    MoveDetail,
    StringChunk,
    StringDetail,
)
from .paths import canonical_json


def diff_json(old_value: Any, new_value: Any, settings: DiffSettings) -> DiffNode:
    return _diff_value(old_value, new_value, (), (), settings)


def _diff_value(
    old_value: Any,
    new_value: Any,
    old_path: tuple[str | int, ...],
    new_path: tuple[str | int, ...],
    settings: DiffSettings,
) -> DiffNode:
    if isinstance(old_value, dict) and isinstance(new_value, dict):
        return _diff_object(old_value, new_value, old_path, new_path, settings)

    if isinstance(old_value, list) and isinstance(new_value, list):
        return _diff_array(old_value, new_value, old_path, new_path, settings)

    if canonical_json(old_value) == canonical_json(new_value):
        return DiffNode(
            old_path=old_path,
            new_path=new_path,
            status=DiffStatus.UNCHANGED,
            old_value=old_value,
            new_value=new_value,
        )

    string_detail = None
    if isinstance(old_value, str) and isinstance(new_value, str):
        string_detail = _build_string_detail(old_value, new_value, settings.inline_string_limit)

    return DiffNode(
        old_path=old_path,
        new_path=new_path,
        status=DiffStatus.MODIFIED,
        old_value=old_value,
        new_value=new_value,
        string_detail=string_detail,
    )


def _diff_object(
    old_value: dict[str, Any],
    new_value: dict[str, Any],
    old_path: tuple[str | int, ...],
    new_path: tuple[str | int, ...],
    settings: DiffSettings,
) -> DiffNode:
    old_keys = list(old_value.keys())
    new_keys = list(new_value.keys())
    old_positions = {key: index for index, key in enumerate(old_keys)}
    new_positions = {key: index for index, key in enumerate(new_keys)}
    children: list[DiffNode] = []

    for key in new_keys:
        child_old_path = old_path + (key,)
        child_new_path = new_path + (key,)
        if key in old_value:
            child = _diff_value(old_value[key], new_value[key], child_old_path, child_new_path, settings)
            child.old_index = old_positions[key]
            child.new_index = new_positions[key]
        else:
            child = _build_added_node(new_value[key], child_new_path)
            child.new_index = new_positions[key]
        children.append(child)

    for key in old_keys:
        if key in new_value:
            continue
        child_old_path = old_path + (key,)
        child = _build_removed_node(old_value[key], child_old_path)
        child.old_index = old_positions[key]
        children.append(child)

    return DiffNode(
        old_path=old_path,
        new_path=new_path,
        status=DiffStatus.MODIFIED if _children_have_changes(children) else DiffStatus.UNCHANGED,
        old_value=old_value,
        new_value=new_value,
        children=children,
    )


def _diff_array(
    old_value: list[Any],
    new_value: list[Any],
    old_path: tuple[str | int, ...],
    new_path: tuple[str | int, ...],
    settings: DiffSettings,
) -> DiffNode:
    children: list[DiffNode] = []
    matches = match_array_items(old_value, new_value, new_path, settings)
    for match in matches:
        if match.old_index is not None and match.new_index is not None:
            child = _diff_value(
                old_value[match.old_index],
                new_value[match.new_index],
                old_path + (match.old_index,),
                new_path + (match.new_index,),
                settings,
            )
            child.same_item_basis = match.same_item_basis
            child.alignment_basis = match.alignment_basis
            child.identity_label = match.identity_label
            child.old_index = match.old_index
            child.new_index = match.new_index
            if match.move_basis is not MoveBasis.NONE:
                child.move_detail = MoveDetail(
                    old_path=old_path + (match.old_index,),
                    new_path=new_path + (match.new_index,),
                    basis=match.move_basis,
                    identity_label=match.identity_label,
                )
        elif match.new_index is not None:
            child = _build_added_node(new_value[match.new_index], new_path + (match.new_index,))
            child.new_index = match.new_index
        else:
            assert match.old_index is not None
            child = _build_removed_node(old_value[match.old_index], old_path + (match.old_index,))
            child.old_index = match.old_index
        children.append(child)

    return DiffNode(
        old_path=old_path,
        new_path=new_path,
        status=DiffStatus.MODIFIED if _children_have_changes(children) else DiffStatus.UNCHANGED,
        old_value=old_value,
        new_value=new_value,
        children=children,
    )


def _build_added_node(value: Any, path: tuple[str | int, ...]) -> DiffNode:
    if isinstance(value, dict):
        children: list[DiffNode] = []
        for index, key in enumerate(value.keys()):
            child = _build_added_node(value[key], path + (key,))
            child.new_index = index
            children.append(child)
        return DiffNode(
            old_path=path,
            new_path=path,
            status=DiffStatus.ADDED,
            old_value=None,
            new_value=value,
            children=children,
        )
    if isinstance(value, list):
        children = []
        for index, item in enumerate(value):
            child = _build_added_node(item, path + (index,))
            child.new_index = index
            children.append(child)
        return DiffNode(
            old_path=path,
            new_path=path,
            status=DiffStatus.ADDED,
            old_value=None,
            new_value=value,
            children=children,
        )
    return DiffNode(
        old_path=path,
        new_path=path,
        status=DiffStatus.ADDED,
        old_value=None,
        new_value=value,
    )


def _build_removed_node(value: Any, path: tuple[str | int, ...]) -> DiffNode:
    if isinstance(value, dict):
        children: list[DiffNode] = []
        for index, key in enumerate(value.keys()):
            child = _build_removed_node(value[key], path + (key,))
            child.old_index = index
            children.append(child)
        return DiffNode(
            old_path=path,
            new_path=path,
            status=DiffStatus.REMOVED,
            old_value=value,
            new_value=None,
            children=children,
        )
    if isinstance(value, list):
        children = []
        for index, item in enumerate(value):
            child = _build_removed_node(item, path + (index,))
            child.old_index = index
            children.append(child)
        return DiffNode(
            old_path=path,
            new_path=path,
            status=DiffStatus.REMOVED,
            old_value=value,
            new_value=None,
            children=children,
        )
    return DiffNode(
        old_path=path,
        new_path=path,
        status=DiffStatus.REMOVED,
        old_value=value,
        new_value=None,
    )


def _children_have_changes(children: list[DiffNode]) -> bool:
    return any(child.status is not DiffStatus.UNCHANGED or child.move_detail is not None for child in children)


def _build_string_detail(old_text: str, new_text: str, inline_limit: int) -> StringDetail:
    if "\n" in old_text or "\n" in new_text or max(len(old_text), len(new_text)) > inline_limit:
        return StringDetail(mode="block", old_text=old_text, new_text=new_text)

    chunks: list[StringChunk] = []
    matcher = SequenceMatcher(a=old_text, b=new_text)
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal" and old_start != old_end:
            chunks.append(StringChunk(role="same", text=old_text[old_start:old_end]))
        elif tag == "delete":
            chunks.append(StringChunk(role="removed", text=old_text[old_start:old_end]))
        elif tag == "insert":
            chunks.append(StringChunk(role="added", text=new_text[new_start:new_end]))
        elif tag == "replace":
            if old_start != old_end:
                chunks.append(StringChunk(role="removed", text=old_text[old_start:old_end]))
            if new_start != new_end:
                chunks.append(StringChunk(role="added", text=new_text[new_start:new_end]))

    return StringDetail(mode="inline", old_text=old_text, new_text=new_text, chunks=chunks)
