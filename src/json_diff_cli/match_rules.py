from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from .errors import UserInputError
from .types import MatchRuleSet


@dataclass(frozen=True)
class MatchConfig:
    global_matches: list[list[str]]
    path_matches: dict[str, list[list[str]]]

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | object) -> "MatchConfig":
        if not isinstance(data, Mapping):
            raise UserInputError("Match config must be a mapping")

        unknown_keys = set(data) - {"global_matches", "path_matches"}
        if unknown_keys:
            unknown_list = ", ".join(sorted(str(key) for key in unknown_keys))
            raise UserInputError(f"Unknown match config keys: {unknown_list}")

        global_matches = _parse_candidate_groups(
            data.get("global_matches", []),
            context="global_matches",
        )

        path_matches_raw = data.get("path_matches", {})
        if not isinstance(path_matches_raw, Mapping):
            raise UserInputError("path_matches must be a mapping")

        path_matches: dict[str, list[list[str]]] = {}
        for path, candidates in path_matches_raw.items():
            path_key = _require_string(path, context="path_matches key")
            path_matches[path_key] = _parse_candidate_groups(
                candidates,
                context=f"path_matches.{path_key}",
            )

        return cls(global_matches=global_matches, path_matches=path_matches)


def build_match_rule_set(
    cli_keys: list[str],
    config: MatchConfig | None,
) -> MatchRuleSet:
    normalized_cli_keys = [
        _validate_cli_match_key(key)
        for key in cli_keys
    ]
    effective_config = config or MatchConfig(global_matches=[], path_matches={})

    for path in effective_config.path_matches:
        _validate_rule_path(path)

    return MatchRuleSet(
        cli_global_keys=list(normalized_cli_keys),
        yaml_global_keys=[list(group) for group in effective_config.global_matches],
        yaml_path_keys={
            path: [list(group) for group in groups]
            for path, groups in effective_config.path_matches.items()
        },
    )


def _parse_candidate_groups(value: object, *, context: str) -> list[list[str]]:
    if not isinstance(value, list):
        raise UserInputError(f"{context} must be a list")

    normalized: list[list[str]] = []
    for candidate in value:
        if isinstance(candidate, str):
            normalized.append([_require_string(candidate, context=context)])
            continue

        if not isinstance(candidate, list):
            raise UserInputError(
                f"{context} entries must be strings or lists of strings"
            )

        if not candidate:
            raise UserInputError(f"{context} composite entries must not be empty")

        normalized.append(
            [_require_string(key, context=context) for key in candidate]
        )

    return normalized


def _require_string(value: object, *, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise UserInputError(f"{context} must be a non-empty string")
    return value


def _validate_cli_match_key(value: object) -> str:
    key = _require_string(value, context="CLI match key")
    if any(marker in key for marker in (".", "[", "]", "*")):
        raise UserInputError(f"Invalid CLI match key: {key}")
    return key


def _validate_rule_path(path: str) -> None:
    segments = _split_rule_path_segments(path)
    if not segments:
        raise UserInputError(f"Invalid match path: {path}")

    for index, (segment, is_escaped) in enumerate(segments):
        if segment == "*":
            if is_escaped:
                continue
            if index == 0 or index == len(segments) - 1:
                raise UserInputError(f"Invalid match path: {path}")
            previous_segment, previous_is_escaped = segments[index - 1]
            next_segment, next_is_escaped = segments[index + 1]
            if (
                previous_segment == "*" and not previous_is_escaped
            ) or (
                next_segment == "*" and not next_is_escaped
            ):
                raise UserInputError(f"Invalid match path: {path}")
            continue
        if not is_escaped and "*" in segment:
            raise UserInputError(f"Invalid match path: {path}")


def _split_rule_path_segments(path: str) -> list[tuple[str, bool]]:
    segments: list[tuple[str, bool]] = []
    buffer: list[str] = []
    index = 0

    while index < len(path):
        char = path[index]
        if char == ".":
            if not buffer:
                raise UserInputError(f"Invalid match path: {path}")
            segments.append(("".join(buffer), False))
            buffer.clear()
            index += 1
            continue
        if char == "[":
            if buffer:
                segments.append(("".join(buffer), False))
                buffer.clear()
            close_index = _find_segment_end(path, index)
            segments.append(
                (_decode_rule_literal_segment(path[index + 1 : close_index], path), True)
            )
            index = close_index + 1
            if index < len(path) and path[index] != ".":
                raise UserInputError(f"Invalid match path: {path}")
            if index < len(path) and path[index] == ".":
                index += 1
                if index == len(path):
                    raise UserInputError(f"Invalid match path: {path}")
            continue
        buffer.append(char)
        index += 1

    if buffer:
        segments.append(("".join(buffer), False))
    elif path.endswith("."):
        raise UserInputError(f"Invalid match path: {path}")

    return segments


def _find_segment_end(path: str, start_index: int) -> int:
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

    raise UserInputError(f"Invalid match path: {path}")


def _decode_rule_literal_segment(raw_segment: str, path: str) -> str:
    try:
        decoded = json.loads(raw_segment)
    except json.JSONDecodeError as exc:
        raise UserInputError(f"Invalid match path: {path}") from exc
    if not isinstance(decoded, str):
        raise UserInputError(f"Invalid match path: {path}")
    return decoded
