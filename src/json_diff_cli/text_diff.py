from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Literal


TOKEN_RE = re.compile(r"\w+|\s+|[^\w\s]+", re.UNICODE)


@dataclass(frozen=True)
class StringFragment:
    role: Literal["equal", "remove", "add"]
    text: str


@dataclass(frozen=True)
class TextDiff:
    fragments: tuple[StringFragment, ...]


def diff_strings(old_text: str, new_text: str) -> tuple[StringFragment, ...]:
    old_tokens = _tokenize(old_text)
    new_tokens = _tokenize(new_text)
    matcher = SequenceMatcher(a=old_tokens, b=new_tokens, autojunk=False)

    fragments: list[StringFragment] = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            _append_fragment(
                fragments,
                "equal",
                "".join(old_tokens[old_start:old_end]),
            )
            continue
        if tag == "delete":
            _append_fragment(
                fragments,
                "remove",
                "".join(old_tokens[old_start:old_end]),
            )
            continue
        if tag == "insert":
            _append_fragment(
                fragments,
                "add",
                "".join(new_tokens[new_start:new_end]),
            )
            continue
        if tag == "replace":
            _append_fragment(
                fragments,
                "remove",
                "".join(old_tokens[old_start:old_end]),
            )
            _append_fragment(
                fragments,
                "add",
                "".join(new_tokens[new_start:new_end]),
            )

    return tuple(fragment for fragment in fragments if fragment.text)


def _tokenize(text: str) -> list[str]:
    if any(character.isspace() for character in text):
        return TOKEN_RE.findall(text)
    return list(text)


def _append_fragment(
    fragments: list[StringFragment],
    role: Literal["equal", "remove", "add"],
    text: str,
) -> None:
    if not text:
        return
    if fragments and fragments[-1].role == role:
        previous = fragments[-1]
        fragments[-1] = StringFragment(role=role, text=previous.text + text)
        return
    fragments.append(StringFragment(role=role, text=text))
