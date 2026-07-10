"""Recursive construction of the complete semantic diff tree."""

from __future__ import annotations

from .matching import ArrayMatch, match_array
from .model import (
    ArrayEntry,
    DiffNode,
    DiffStatus,
    JsonPath,
    JsonValue,
    ObjectMember,
)
from .parser import strict_equal

DEFAULT_MATCH_KEYS = ("id", "key", "name", "title")


def build_diff(
    old: JsonValue,
    new: JsonValue,
    match_keys: tuple[str, ...] = DEFAULT_MATCH_KEYS,
) -> DiffNode:
    """Compare two strict JSON documents into one complete semantic tree."""

    return _build_node(old, new, (), (), match_keys)


def _build_node(
    old: JsonValue,
    new: JsonValue,
    old_path: JsonPath,
    new_path: JsonPath,
    match_keys: tuple[str, ...],
) -> DiffNode:
    if strict_equal(old, new):
        return DiffNode(
            DiffStatus.UNCHANGED,
            old,
            new,
            old_path,
            new_path,
        )
    if isinstance(old, dict) and isinstance(new, dict):
        members = _build_object_members(
            old,
            new,
            old_path,
            new_path,
            match_keys,
        )
        return DiffNode(
            DiffStatus.MODIFIED,
            old,
            new,
            old_path,
            new_path,
            object_members=members,
        )
    if isinstance(old, list) and isinstance(new, list):
        entries = _build_array_entries(
            old,
            new,
            old_path,
            new_path,
            match_keys,
        )
        return DiffNode(
            DiffStatus.MODIFIED,
            old,
            new,
            old_path,
            new_path,
            array_entries=entries,
        )
    return DiffNode(
        DiffStatus.MODIFIED,
        old,
        new,
        old_path,
        new_path,
    )


def _build_object_members(
    old: dict[str, JsonValue],
    new: dict[str, JsonValue],
    old_path: JsonPath,
    new_path: JsonPath,
    match_keys: tuple[str, ...],
) -> tuple[ObjectMember, ...]:
    common = old.keys() & new.keys()
    anchors: dict[str, list[str]] = {}
    pending: list[str] = []
    for key in old:
        if key in common:
            if pending:
                anchors[key] = pending
                pending = []
        else:
            pending.append(key)
    trailing = pending

    result: list[ObjectMember] = []
    for key, new_value in new.items():
        for removed_key in anchors.get(key, []):
            result.append(
                ObjectMember(
                    removed_key,
                    DiffNode(
                        DiffStatus.REMOVED,
                        old[removed_key],
                        None,
                        (*old_path, removed_key),
                        None,
                    ),
                )
            )
        if key in old:
            node = _build_node(
                old[key],
                new_value,
                (*old_path, key),
                (*new_path, key),
                match_keys,
            )
        else:
            node = DiffNode(
                DiffStatus.ADDED,
                None,
                new_value,
                None,
                (*new_path, key),
            )
        result.append(ObjectMember(key, node))

    for removed_key in trailing:
        result.append(
            ObjectMember(
                removed_key,
                DiffNode(
                    DiffStatus.REMOVED,
                    old[removed_key],
                    None,
                    (*old_path, removed_key),
                    None,
                ),
            )
        )
    return tuple(result)


def _build_array_entries(
    old: list[JsonValue],
    new: list[JsonValue],
    old_path: JsonPath,
    new_path: JsonPath,
    match_keys: tuple[str, ...],
) -> tuple[ArrayEntry, ...]:
    matches = match_array(old, new, match_keys)
    by_new = {match.new_index: match for match in matches}
    by_old = {match.old_index: match for match in matches}
    anchors: dict[int, list[int]] = {}
    pending: list[int] = []
    for old_index in range(len(old)):
        match = by_old.get(old_index)
        if match is not None:
            if pending:
                anchors[match.new_index] = pending
                pending = []
        else:
            pending.append(old_index)
    trailing = pending

    result: list[ArrayEntry] = []
    for new_index, new_value in enumerate(new):
        for removed_index in anchors.get(new_index, []):
            result.append(
                ArrayEntry(
                    DiffNode(
                        DiffStatus.REMOVED,
                        old[removed_index],
                        None,
                        (*old_path, removed_index),
                        None,
                    ),
                    old_index=removed_index,
                    new_index=None,
                )
            )

        match = by_new.get(new_index)
        if match is None:
            result.append(
                ArrayEntry(
                    DiffNode(
                        DiffStatus.ADDED,
                        None,
                        new_value,
                        None,
                        (*new_path, new_index),
                    ),
                    old_index=None,
                    new_index=new_index,
                )
            )
        else:
            result.append(
                _build_matched_entry(
                    old,
                    new_value,
                    old_path,
                    new_path,
                    match_keys,
                    match,
                )
            )

    for removed_index in trailing:
        result.append(
            ArrayEntry(
                DiffNode(
                    DiffStatus.REMOVED,
                    old[removed_index],
                    None,
                    (*old_path, removed_index),
                    None,
                ),
                old_index=removed_index,
                new_index=None,
            )
        )
    return tuple(result)


def _build_matched_entry(
    old: list[JsonValue],
    new_value: JsonValue,
    old_path: JsonPath,
    new_path: JsonPath,
    match_keys: tuple[str, ...],
    match: ArrayMatch,
) -> ArrayEntry:
    node = _build_node(
        old[match.old_index],
        new_value,
        (*old_path, match.old_index),
        (*new_path, match.new_index),
        match_keys,
    )
    return ArrayEntry(
        node,
        old_index=match.old_index,
        new_index=match.new_index,
        alignment_basis=match.alignment_basis,
        evidence=match.evidence,
        moved=match.moved,
    )
