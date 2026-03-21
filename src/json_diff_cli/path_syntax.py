from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json

from .errors import UserInputError


@dataclass(frozen=True)
class PathSegment:
    value: str
    is_wildcard: bool = False
    is_quoted_literal: bool = False
    is_array_index: bool = False


def append_object_path(base_path: str, key: str) -> str:
    if needs_path_escape(key):
        escaped_key = json.dumps(key, ensure_ascii=False)
        return f"{base_path}[{escaped_key}]" if base_path else f"[{escaped_key}]"
    if not base_path:
        return key
    return f"{base_path}.{key}"


def needs_path_escape(key: str) -> bool:
    return not key.isidentifier()


@lru_cache(maxsize=None)
def parse_rule_path(path: str) -> tuple[PathSegment, ...]:
    segments = _parse_path(path, allow_array_indexes=False, error_label="match")
    _validate_rule_segments(path, segments)
    return tuple(segments)


@lru_cache(maxsize=None)
def parse_object_key_path(path: str) -> tuple[str, ...]:
    segments = _parse_path(path, allow_array_indexes=False, error_label="match")
    if not segments:
        raise UserInputError(f"Invalid match key path: {path}")

    normalized: list[str] = []
    for segment in segments:
        if segment.is_wildcard and not segment.is_quoted_literal:
            raise UserInputError(f"Invalid match key path: {path}")
        if not segment.is_quoted_literal and "*" in segment.value:
            raise UserInputError(f"Invalid match key path: {path}")
        normalized.append(segment.value)

    return tuple(normalized)


def match_rule_path(
    pattern: tuple[PathSegment, ...] | list[PathSegment],
    runtime_path: str,
) -> bool:
    runtime_segments = _parse_path(
        runtime_path,
        allow_array_indexes=True,
        error_label="runtime",
    )
    if len(pattern) != len(runtime_segments):
        return False

    for pattern_segment, runtime_segment in zip(pattern, runtime_segments):
        if pattern_segment.is_wildcard:
            continue
        if runtime_segment.is_array_index:
            return False
        if pattern_segment.value != runtime_segment.value:
            return False
    return True


def rule_path_specificity(
    pattern: tuple[PathSegment, ...] | list[PathSegment],
) -> int:
    return sum(not segment.is_wildcard for segment in pattern)


def _validate_rule_segments(path: str, segments: list[PathSegment]) -> None:
    if not segments:
        raise UserInputError(f"Invalid match path: {path}")

    for index, segment in enumerate(segments):
        if segment.is_wildcard:
            if segment.is_quoted_literal:
                continue
            if index == 0 or index == len(segments) - 1:
                raise UserInputError(f"Invalid match path: {path}")
            previous_segment = segments[index - 1]
            next_segment = segments[index + 1]
            if (
                previous_segment.is_wildcard
                and not previous_segment.is_quoted_literal
            ) or (
                next_segment.is_wildcard
                and not next_segment.is_quoted_literal
            ):
                raise UserInputError(f"Invalid match path: {path}")
            continue
        if not segment.is_quoted_literal and "*" in segment.value:
            raise UserInputError(f"Invalid match path: {path}")


def _parse_path(
    path: str,
    *,
    allow_array_indexes: bool,
    error_label: str,
) -> list[PathSegment]:
    if not path:
        return []

    segments: list[PathSegment] = []
    buffer: list[str] = []
    index = 0

    while index < len(path):
        char = path[index]
        if char == ".":
            if not buffer:
                raise _path_error(path, error_label)
            token = "".join(buffer)
            segments.append(PathSegment(value=token, is_wildcard=token == "*"))
            buffer.clear()
            index += 1
            continue
        if char == "[":
            if buffer:
                token = "".join(buffer)
                segments.append(PathSegment(value=token, is_wildcard=token == "*"))
                buffer.clear()
            close_index = _find_segment_end(path, index, error_label)
            raw_segment = path[index + 1 : close_index]
            if allow_array_indexes:
                segments.append(_decode_runtime_bracket_segment(raw_segment))
            else:
                literal_segment = _decode_rule_literal_segment(raw_segment, path)
                segments.append(
                    PathSegment(
                        value=literal_segment,
                        is_quoted_literal=True,
                    )
                )
            index = close_index + 1
            if index < len(path) and path[index] not in ".[":  # pragma: no branch
                raise _path_error(path, error_label)
            if index < len(path) and path[index] == ".":
                index += 1
                if index == len(path):
                    raise _path_error(path, error_label)
            continue
        buffer.append(char)
        index += 1

    if buffer:
        token = "".join(buffer)
        segments.append(PathSegment(value=token, is_wildcard=token == "*"))
    elif path.endswith("."):
        raise _path_error(path, error_label)

    return segments


def _find_segment_end(path: str, start_index: int, error_label: str) -> int:
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

    raise _path_error(path, error_label)


def _decode_rule_literal_segment(raw_segment: str, path: str) -> str:
    decoded = _decode_json_string_segment(raw_segment)
    if decoded is None:
        raise UserInputError(f"Invalid match path: {path}")
    return decoded


def _decode_runtime_bracket_segment(raw_segment: str) -> PathSegment:
    decoded = _decode_json_string_segment(raw_segment)
    if decoded is not None:
        return PathSegment(value=decoded, is_quoted_literal=True)
    return PathSegment(value=raw_segment, is_array_index=raw_segment.isdigit())


def _decode_json_string_segment(raw_segment: str) -> str | None:
    try:
        decoded = json.loads(raw_segment)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, str):
        return None
    return decoded


def _path_error(path: str, error_label: str) -> UserInputError:
    if error_label == "runtime":
        return UserInputError(f"Invalid runtime path: {path}")
    return UserInputError(f"Invalid match path: {path}")
