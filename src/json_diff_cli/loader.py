from __future__ import annotations

import json
from pathlib import Path

import yaml

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
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise UserInputError(f"Invalid YAML: {path}") from exc

    if data is None:
        data = {}

    return MatchConfig.from_mapping(data)


def _reject_non_standard_constant(token: str) -> None:
    raise ValueError(f"Invalid JSON constant: {token}")
