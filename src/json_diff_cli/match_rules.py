from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .errors import UserInputError


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


@dataclass(frozen=True)
class MatchRuleSet:
    cli_global_keys: list[str]
    yaml_global_keys: list[list[str]]
    yaml_path_keys: dict[str, list[list[str]]]


def build_match_rule_set(
    cli_keys: list[str],
    config: MatchConfig | None,
) -> MatchRuleSet:
    normalized_cli_keys = [
        _require_string(key, context="CLI match key")
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


def _validate_rule_path(path: str) -> None:
    segments = path.split(".")
    if any(segment == "" for segment in segments):
        raise UserInputError(f"Invalid match path: {path}")

    for segment in segments:
        if segment == "*":
            continue
        if segment.isdigit():
            raise UserInputError(f"Invalid match path: {path}")
