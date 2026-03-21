from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from .errors import UserInputError
from .path_syntax import (
    append_object_path,
    match_rule_path,
    parse_rule_path,
    rule_path_specificity,
)
from .types import MatchRuleSet


def resolve_object_key_rule(
    array_path: str,
    items: list[object],
    rules: MatchRuleSet,
) -> list[str] | None:
    for candidate in object_key_candidates(array_path, rules):
        if _candidate_applies(candidate, items):
            return list(candidate)

    return None


def object_key_candidates(
    array_path: str,
    rules: MatchRuleSet,
) -> list[list[str]]:
    candidates: list[list[str]] = []
    candidates.extend(_lookup_yaml_path_candidates(array_path, rules.yaml_path_keys) or [])
    candidates.extend(list(group) for group in rules.yaml_global_keys)
    candidates.extend([[key] for key in rules.cli_global_keys])
    return candidates


def canonical_object_path(
    array_path: str,
    keys: Sequence[str],
    values: Sequence[object],
    child_key: str | None = None,
) -> str:
    if not keys:
        raise UserInputError("Object identity keys must not be empty")
    if len(keys) != len(values):
        raise UserInputError("Object identity keys and values must have the same length")

    selectors = ",".join(
        f"{key}={_format_identity_value(key, value)}"
        for key, value in zip(keys, values)
    )
    return _append_child_path(f"{array_path}[{selectors}]", child_key)


def canonical_primitive_path(array_path: str, value: object, occurrence: int) -> str:
    if occurrence < 0:
        raise UserInputError("Primitive identity occurrence must be non-negative")
    return f"{array_path}[value={_format_primitive_value(value)}#{occurrence}]"


def build_object_identity(
    item: Mapping[str, object],
    keys: Sequence[str],
) -> tuple[tuple[str, object], ...]:
    identity: list[tuple[str, object]] = []
    for key in keys:
        value = _resolve_dotted_key(item, key)
        if not _is_json_scalar(value):
            raise UserInputError(f"Match key '{key}' must resolve to a scalar")
        identity.append((key, value))
    return tuple(identity)


def _lookup_yaml_path_candidates(
    runtime_path: str,
    yaml_path_keys: dict[str, list[list[str]]],
) -> list[list[str]] | None:
    matched_patterns: list[tuple[int, int, list[list[str]]]] = []
    for order, (pattern, candidates) in enumerate(yaml_path_keys.items()):
        pattern_segments = parse_rule_path(pattern)
        if match_rule_path(pattern_segments, runtime_path):
            matched_patterns.append(
                (rule_path_specificity(pattern_segments), order, candidates)
            )

    matched_patterns.sort(key=lambda item: (-item[0], item[1]))

    matched_candidates: list[list[str]] = []
    for _, _, candidates in matched_patterns:
        matched_candidates.extend(candidates)
    return matched_candidates or None


def _first_applicable_candidate(
    candidates: list[list[str]],
    items: list[object],
) -> list[str] | None:
    if not items:
        return None

    for candidate in candidates:
        if _candidate_applies(candidate, items):
            return list(candidate)
    return None


def _candidate_applies(candidate: list[str], items: list[object]) -> bool:
    for item in items:
        if not isinstance(item, Mapping):
            return False
        for key in candidate:
            if not _has_dotted_key(item, key):
                return False
    return True


def _has_dotted_key(value: Mapping[str, object], dotted_key: str) -> bool:
    current: object = value
    for segment in dotted_key.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            return False
        current = current[segment]
    return True


def _resolve_dotted_key(value: Mapping[str, object], dotted_key: str) -> object:
    current: object = value
    for segment in dotted_key.split("."):
        if not isinstance(current, Mapping) or segment not in current:
            raise UserInputError(f"Missing match key '{dotted_key}'")
        current = current[segment]
    return current



def _format_identity_value(key: str, value: object) -> str:
    if not _is_json_scalar(value):
        raise UserInputError(f"Match key '{key}' must resolve to a scalar")
    return json.dumps(value, ensure_ascii=False)


def _format_primitive_value(value: object) -> str:
    if not _is_json_scalar(value):
        raise UserInputError("Primitive array identity values must be scalars")
    return json.dumps(value, ensure_ascii=False)


def _is_json_scalar(value: object) -> bool:
    return value is None or isinstance(value, (bool, int, float, str))


def _append_child_path(base_path: str, child_key: str | None) -> str:
    if child_key is None:
        return base_path
    return append_object_path(base_path, child_key)
