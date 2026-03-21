from __future__ import annotations

import json
from pathlib import Path

import yaml
from yaml.nodes import MappingNode

from .errors import UserInputError
from .match_rules import MatchConfig


def load_json_file(path: Path) -> object:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UserInputError(f"Could not read JSON file: {path}") from exc

    try:
        return json.loads(
            raw_text,
            parse_constant=_reject_non_standard_constant,
            object_pairs_hook=_build_unique_json_object,
        )
    except json.JSONDecodeError as exc:
        raise UserInputError(_format_json_decode_error(path, exc)) from exc
    except ValueError as exc:
        raise UserInputError(_format_json_value_error(path, exc)) from exc


def load_match_config(path: Path) -> MatchConfig:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UserInputError(f"Could not read match config: {path}") from exc

    try:
        data = yaml.load(raw_text, Loader=_UniqueKeySafeLoader)
    except UserInputError as exc:
        raise UserInputError(f"Invalid match config: {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise UserInputError(_format_yaml_error(path, exc)) from exc

    if data is None:
        data = {}

    try:
        return MatchConfig.from_mapping(data)
    except UserInputError as exc:
        raise UserInputError(f"Invalid match config: {path}: {exc}") from exc


def _reject_non_standard_constant(token: str) -> None:
    raise ValueError(f"Invalid JSON constant: {token}")


def _format_json_decode_error(path: Path, exc: json.JSONDecodeError) -> str:
    return (
        f"Invalid JSON: {path} "
        f"(line {exc.lineno}, column {exc.colno}): {exc.msg}"
    )


def _format_json_value_error(path: Path, exc: ValueError) -> str:
    return f"Invalid JSON: {path}: {exc}"


def _format_yaml_error(path: Path, exc: yaml.YAMLError) -> str:
    mark = getattr(exc, "problem_mark", None)
    if mark is None:
        return f"Invalid YAML: {path}"
    return (
        f"Invalid YAML: {path} "
        f"(line {mark.line + 1}, column {mark.column + 1})"
    )


def _build_unique_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> object:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}

    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            hash(key)
        except TypeError as exc:
            raise UserInputError(f"Invalid YAML key: {key}") from exc
        if key in mapping:
            raise UserInputError(f"Duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)

    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)
