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
        return json.loads(raw_text, parse_constant=_reject_non_standard_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise UserInputError(f"Invalid JSON: {path}") from exc


def load_match_config(path: Path) -> MatchConfig:
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UserInputError(f"Could not read match config: {path}") from exc

    try:
        data = yaml.load(raw_text, Loader=_UniqueKeySafeLoader)
    except yaml.YAMLError as exc:
        raise UserInputError(f"Invalid YAML: {path}") from exc

    if data is None:
        data = {}

    return MatchConfig.from_mapping(data)


def _reject_non_standard_constant(token: str) -> None:
    raise ValueError(f"Invalid JSON constant: {token}")


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
        if key in mapping:
            raise UserInputError(f"Duplicate YAML key: {key}")
        mapping[key] = loader.construct_object(value_node, deep=deep)

    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)
