from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal, TypeAlias

from .text_diff import TextDiff


JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
DiffChildren: TypeAlias = dict[str, "DiffNode"] | tuple["DiffNode", ...]


class _MissingValue:
    __slots__ = ()

    def __repr__(self) -> str:
        return "MISSING"


MISSING = _MissingValue()


class DiffKind(str, Enum):
    UNCHANGED = "unchanged"
    ADDED = "added"
    REMOVED = "removed"
    REPLACED = "replaced"
    OBJECT = "object"
    ARRAY = "array"


@dataclass(frozen=True)
class MatchInfo:
    mode: Literal["position", "primitive-smart", "object-smart"]
    identity_keys: tuple[str, ...] = ()
    identity_values: tuple[JsonScalar, ...] = ()
    occurrence: int | None = None


@dataclass(frozen=True)
class DiffNode:
    path: str
    kind: DiffKind
    left: JsonValue | _MissingValue = MISSING
    right: JsonValue | _MissingValue = MISSING
    children: DiffChildren = ()
    text_diff: TextDiff | None = None
    display_path: str | None = None
    match_info: MatchInfo | None = None

    def __post_init__(self) -> None:
        if self.display_path is None:
            object.__setattr__(self, "display_path", self.path)

    @property
    def has_changes(self) -> bool:
        if self.kind in (DiffKind.ADDED, DiffKind.REMOVED, DiffKind.REPLACED):
            return True
        if isinstance(self.children, dict):
            return any(child.has_changes for child in self.children.values())
        return any(child.has_changes for child in self.children)


@dataclass(frozen=True)
class MatchRuleSet:
    cli_global_keys: list[str]
    yaml_global_keys: list[list[str]]
    yaml_path_keys: dict[str, list[list[str]]]
