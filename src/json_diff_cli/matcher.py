from __future__ import annotations

import json
from dataclasses import dataclass
from collections.abc import Mapping, Sequence

from .errors import UserInputError
from .path_syntax import append_object_path
from .types import MatchRuleSet


@dataclass(frozen=True)
class _PathSegment:
    value: str
    is_wildcard: bool = False
    is_quoted_literal: bool = False


def resolve_object_key_rule(
    array_path: str,
    items: list[object],
    rules: MatchRuleSet,
) -> list[str] | None:
    candidate_groups = (
        _lookup_yaml_path_candidates(array_path, rules.yaml_path_keys),
        rules.yaml_global_keys,
        [[key] for key in rules.cli_global_keys],
    )

    for candidates in candidate_groups:
        resolved = _first_applicable_candidate(candidates or [], items)
        if resolved is not None:
            return resolved

    return None


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


def _lookup_yaml_path_candidates(
    runtime_path: str,
    yaml_path_keys: dict[str, list[list[str]]],
) -> list[list[str]] | None:
    runtime_segments = _split_runtime_path(runtime_path)
    matched_candidates: list[list[str]] = []
    for pattern, candidates in yaml_path_keys.items():
        if _path_pattern_matches(_split_rule_path(pattern), runtime_segments):
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


def _path_pattern_matches(
    pattern_segments: list[_PathSegment],
    runtime_segments: list[_PathSegment],
) -> bool:
    if len(pattern_segments) != len(runtime_segments):
        return False

    for pattern_segment, runtime_segment in zip(pattern_segments, runtime_segments):
        if pattern_segment.is_wildcard:
            if runtime_segment.is_quoted_literal:
                return False
            continue
        if pattern_segment.value != runtime_segment.value:
            return False
    return True


def _split_rule_path(path: str) -> list[_PathSegment]:
    if not path:
        return []

    segments: list[_PathSegment] = []
    buffer: list[str] = []
    index = 0
    while index < len(path):
        char = path[index]
        if char == ".":
            if not buffer:
                raise UserInputError(f"Invalid match path: {path}")
            token = "".join(buffer)
            segments.append(_PathSegment(value=token, is_wildcard=token == "*"))
            buffer.clear()
            index += 1
            continue
        if char == "[":
            if buffer:
                token = "".join(buffer)
                segments.append(_PathSegment(value=token, is_wildcard=token == "*"))
                buffer.clear()
            close_index = _find_selector_end(path, index)
            literal_segment = _decode_rule_literal_segment(
                path[index + 1 : close_index],
                path,
            )
            segments.append(
                _PathSegment(value=literal_segment, is_quoted_literal=True)
            )
            index = close_index + 1
            if index < len(path) and path[index] not in ".[":
                raise UserInputError(f"Invalid match path: {path}")
            if index < len(path) and path[index] == ".":
                index += 1
                if index == len(path):
                    raise UserInputError(f"Invalid match path: {path}")
            continue
        buffer.append(char)
        index += 1

    if buffer:
        token = "".join(buffer)
        segments.append(_PathSegment(value=token, is_wildcard=token == "*"))
    elif path.endswith("."):
        raise UserInputError(f"Invalid match path: {path}")

    return segments


def _split_runtime_path(path: str) -> list[_PathSegment]:
    if not path:
        return []

    segments: list[_PathSegment] = []
    buffer: list[str] = []
    index = 0
    while index < len(path):
        char = path[index]
        if char == ".":
            if buffer:
                segments.append(_PathSegment(value="".join(buffer)))
                buffer.clear()
            index += 1
            continue
        if char == "[":
            if buffer:
                segments.append(_PathSegment(value="".join(buffer)))
                buffer.clear()
            close_index = _find_selector_end(path, index)
            segments.append(_decode_runtime_bracket_segment(path[index + 1 : close_index]))
            index = close_index + 1
            continue
        buffer.append(char)
        index += 1

    if buffer:
        segments.append(_PathSegment(value="".join(buffer)))

    return segments


def _find_selector_end(path: str, start_index: int) -> int:
    in_string = False
    is_escaped = False
    index = start_index + 1

    while index < len(path):
        char = path[index]

        if in_string:
            if is_escaped:
                is_escaped = False
            elif char == "\\":
                is_escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "]":
            return index

        index += 1

    raise UserInputError(f"Invalid runtime path: {path}")


def _decode_rule_literal_segment(raw_segment: str, rule_path: str) -> str:
    decoded = _decode_json_string_segment(raw_segment)
    if decoded is None:
        raise UserInputError(f"Invalid match path: {rule_path}")
    return decoded


def _decode_runtime_bracket_segment(raw_segment: str) -> _PathSegment:
    decoded = _decode_json_string_segment(raw_segment)
    if decoded is not None:
        return _PathSegment(value=decoded, is_quoted_literal=True)
    return _PathSegment(value=raw_segment)


def _decode_json_string_segment(raw_segment: str) -> str | None:
    try:
        decoded = json.loads(raw_segment)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, str):
        return None
    return decoded


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
