from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias


JsonScalar: TypeAlias = None | bool | int | float | str


@dataclass(frozen=True)
class MatchRuleSet:
    cli_global_keys: list[str]
    yaml_global_keys: list[list[str]]
    yaml_path_keys: dict[str, list[list[str]]]
