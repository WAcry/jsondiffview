from __future__ import annotations

import re
from pathlib import Path

import pytest


def test_github_workflow_is_read_only_and_non_publishing() -> None:
    root = Path(__file__).parents[2]
    workflows = root / ".github" / "workflows"
    if not workflows.exists():
        # Workflows are deliberately excluded from the source distribution.
        assert (root / "PKG-INFO").is_file()
        return
    files = sorted(path for path in workflows.glob("*") if path.is_file())
    assert [path.name for path in files] == ["ci.yml"]

    text = files[0].read_text(encoding="utf-8")
    _assert_non_publishing_workflow(text)


@pytest.mark.parametrize(
    "publish_surface",
    [
        "on: {push: {tags: ['v*']}}",
        "permissions: {id-token: write}",
        "permissions: {contents: write}",
        "environment: pypi",
        "secrets: inherit",
        "run: python -m twine upload dist/*",
        "uses: actions/upload-artifact@0123456789012345678901234567890123456789",
    ],
)
def test_workflow_guard_rejects_inline_publish_surfaces(
    publish_surface: str,
) -> None:
    baseline = "permissions:\n  contents: read\njobs:\n  test:\n"
    with pytest.raises(AssertionError):
        _assert_non_publishing_workflow(baseline + "    " + publish_surface + "\n")


def _assert_non_publishing_workflow(text: str) -> None:
    folded = text.casefold()
    assert "permissions:\n  contents: read\n" in text
    assert not re.search(r"\btags(?:-ignore)?\s*:", folded)
    assert not re.search(r"\benvironment\s*:", folded)
    assert not re.search(r"\bsecrets\s*:", folded)
    assert not re.search(r"\b[a-z-]+\s*:\s*write\b", folded)
    _assert_read_only_permissions(text)
    for action in re.findall(r"(?m)^\s*uses:\s*(\S+)\s*(?:#.*)?$", text):
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action), action

    forbidden = (
        "actions/upload-artifact",
        "actions/download-artifact",
        "pypa/gh-action-pypi-publish",
        "gh-action-pypi-publish",
        "action-gh-release",
        "softprops/action-gh-release",
        "testpypi",
        "upload.pypi.org",
        "pypi.org/legacy",
        "uv publish",
        "twine upload",
        "gh release",
    )
    for token in forbidden:
        assert token not in folded


def _assert_read_only_permissions(text: str) -> None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "permissions:":
            continue
        indentation = len(line) - len(line.lstrip())
        entries: list[str] = []
        for nested in lines[index + 1 :]:
            if not nested.strip():
                continue
            nested_indentation = len(nested) - len(nested.lstrip())
            if nested_indentation <= indentation:
                break
            entries.append(nested.strip())
        assert entries == ["contents: read"]
