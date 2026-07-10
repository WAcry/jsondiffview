from __future__ import annotations

import re
from pathlib import Path

import pytest

CHECKOUT_ACTION = "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
SETUP_UV_ACTION = "astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b"
PUBLISH_ACTION = "pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b"


def test_github_workflows_isolate_the_exact_publish_surface() -> None:
    root = Path(__file__).parents[2]
    workflows = root / ".github" / "workflows"
    if not workflows.exists():
        # Workflows are deliberately excluded from the source distribution.
        assert (root / "PKG-INFO").is_file()
        return

    files = {
        path.name: path.read_text(encoding="utf-8")
        for path in workflows.glob("*")
        if path.is_file()
    }
    assert set(files) == {"ci.yml", "publish.yml"}
    _assert_quality_workflow(files["ci.yml"])
    _assert_publish_workflow(files["publish.yml"])


@pytest.mark.parametrize(
    "publish_surface",
    [
        "on: {push: {tags: ['v*']}}",
        "permissions: {id-token: write}",
        "permissions: {contents: write}",
        "environment: pypi",
        "secrets: inherit",
        "run: python -m twine upload dist/*",
        "uses: pypa/gh-action-pypi-publish@release/v1",
        "uses: actions/upload-artifact@0123456789012345678901234567890123456789",
    ],
)
def test_quality_guard_rejects_inline_publish_surfaces(
    publish_surface: str,
) -> None:
    baseline = _workflow_text("ci.yml")
    with pytest.raises(AssertionError):
        _assert_quality_workflow(baseline + "\n" + publish_surface + "\n")


@pytest.mark.parametrize(
    "forbidden_surface",
    [
        "password: not-allowed",
        "username: not-allowed",
        "secrets: inherit",
        "repository-url: https://example.invalid/",
        "run: twine upload dist/*",
        "run: uv publish dist/*",
        "run: uv build --no-sources",
        "run: echo data > ~/.pypirc",
        "run: curl https://test.pypi.org/",
        "api-token: not-allowed",
        "user: not-allowed",
        "github-token: not-allowed",
        "run: echo ${{ secrets.PYPI }}",
    ],
)
def test_publish_guard_rejects_credentials_and_alternate_uploads(
    forbidden_surface: str,
) -> None:
    workflow = _workflow_text("publish.yml")
    with pytest.raises(AssertionError):
        _assert_publish_workflow(workflow + "\n" + forbidden_surface + "\n")


def _assert_quality_workflow(text: str) -> None:
    folded = text.casefold()
    assert text.startswith("name: Quality\n")
    assert "permissions:\n  contents: read\n" in text
    assert _permission_blocks(text) == [(0, ("contents: read",))]
    assert not re.search(r"\btags(?:-ignore)?\s*:", folded)
    assert not re.search(r"\benvironment\s*:", folded)
    assert not re.search(r"\bsecrets\s*:", folded)
    assert not re.search(r"\b[a-z-]+\s*:\s*write\b", folded)
    _assert_actions_are_pinned(text)
    assert set(_action_uses(text)) == {CHECKOUT_ACTION, SETUP_UV_ACTION}
    assert _action_uses(text).count(CHECKOUT_ACTION) == 4
    assert _action_uses(text).count(SETUP_UV_ACTION) == 4

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


def _assert_publish_workflow(text: str) -> None:
    folded = text.casefold()
    assert text.startswith(
        "name: Publish\n"
        "\n"
        "on:\n"
        "  release:\n"
        "    types: [published]\n"
        "  workflow_dispatch:\n"
        "    inputs:\n"
        "      tag:\n"
        "        description: Existing final GitHub Release tag "
        "(for example, v3.0.0)\n"
        "        required: true\n"
        "        type: string\n"
        "\n"
        "permissions:\n"
    )
    assert not re.search(r"(?m)^  push\s*:", text)
    assert "permissions:\n  contents: read\n" in text
    assert _permission_blocks(text) == [
        (0, ("contents: read",)),
        (4, ("contents: read", "id-token: write")),
    ]
    assert re.findall(r"(?m)^\s*environment:\s*(\S+)\s*$", text) == ["pypi"]
    assert re.findall(
        r"(?m)^\s*uses:\s*(pypa/[^#\s]+)\s*(?:#.*)?$",
        text,
    ) == [PUBLISH_ACTION]
    _assert_actions_are_pinned(text)
    assert set(_action_uses(text)) == {
        CHECKOUT_ACTION,
        SETUP_UV_ACTION,
        PUBLISH_ACTION,
    }
    assert _action_uses(text).count(CHECKOUT_ACTION) == 3
    assert _action_uses(text).count(SETUP_UV_ACTION) == 3
    assert _action_uses(text).count(PUBLISH_ACTION) == 1
    assert re.findall(r"\b([a-z-]+)\s*:\s*write\b", folded) == ["id-token"]

    inspect_job = _job_block(text, "inspect")
    assert 'case "$EVENT_NAME" in' in inspect_job
    assert 'test "$WORKFLOW_REF" = "refs/heads/$DEFAULT_BRANCH"' in inspect_job
    assert 'test "$WORKFLOW_REF" = "refs/tags/$REQUESTED_TAG"' in inspect_job
    assert 'test "$commit" = "$WORKFLOW_SHA"' in inspect_job
    assert "--stage-dir" not in inspect_job
    publish_job = _job_block(text, "publish")
    assert "environment: pypi" in publish_job
    assert "id-token: write" in publish_job
    assert f"uses: {PUBLISH_ACTION}" in publish_job
    assert "packages-dir: .publish-dist" in publish_job
    assert "preflight\n          --stage-dir .publish-dist" in publish_job
    assert "skip-existing: true" in publish_job
    assert "attestations: true" in publish_job
    assert "verify-metadata: true" in publish_job
    assert "verbose: false" in publish_job
    assert "print-hash: true" in publish_job
    assert "scripts.prepare_publisher_compat" in publish_job
    assert "PYTHONPATH: /github/workspace/.pypi-action-compat" in publish_job
    for job in ("inspect", "verify"):
        job_text = _job_block(text, job)
        assert "environment:" not in job_text
        assert "id-token:" not in job_text
        assert "gh-action-pypi-publish" not in job_text

    assert text.count("scripts/download_release.py") == 3
    assert text.count("scripts/validate_artifacts.py") == 2
    assert text.count("scripts/pypi_publication.py") == 3
    assert "scripts/validate_clean_install.py" in text
    assert "--pypi-version" in text
    assert "persist-credentials: false" in text
    assert "ref: ${{ github.workflow_sha }}" in text
    assert text.count("source-commit") == 3
    assert text.count("github.event.release.tag_name || inputs.tag") == 3
    assert text.count('--tag "$REQUESTED_TAG"') == 3

    forbidden = (
        "actions/upload-artifact",
        "actions/download-artifact",
        "action-gh-release",
        "softprops/action-gh-release",
        "testpypi",
        "test.pypi.org",
        "repository-url:",
        ".pypirc",
        "twine ",
        "twine_",
        "uv publish",
        "uv build",
        "python -m build",
        "hatch build",
        "gh release",
        "password:",
        "username:",
        "user:",
        "secrets:",
        "github.token",
        "github_token",
        "api-token",
        "pypi-token",
        "permissions: write-all",
        "permissions: read-all",
        "workflow_call:",
        "schedule:",
    )
    for surface in forbidden:
        assert surface not in folded
    assert not re.search(
        r"(?m)^\s*(?:user|username|password|secrets|api-token|pypi-token)\s*:",
        folded,
    )
    assert not re.search(r"\bsecrets[.:]", folded)
    assert not re.search(r"\brepository[_-]url\s*:", folded)
    assert not re.search(r"\btwine\s+upload\b", folded)

    token_words = re.findall(r"\b[\w-]*token[\w-]*\b", folded)
    assert token_words == ["id-token"]


def test_repository_contains_no_secondary_credential_or_upload_surface() -> None:
    root = Path(__file__).parents[2]
    guarded_paths = [
        root / ".github" / "workflows" / "ci.yml",
        root / ".github" / "workflows" / "publish.yml",
        root / "pyproject.toml",
        *sorted((root / "scripts").glob("*.py")),
        *sorted((root / "src").rglob("*.py")),
    ]
    folded = "\n".join(
        path.read_text(encoding="utf-8").casefold() for path in guarded_paths
    )

    for surface in (
        ".pypirc",
        "secrets:",
        "${{ secrets.",
        "username:",
        "password:",
        "api-token:",
        "pypi-token:",
        "repository-url:",
        "repository_url:",
        "twine upload",
        "uv publish",
        "test.pypi",
        "testpypi",
        "extra-index-url",
    ):
        assert surface not in folded
    assert folded.count("pypa/gh-action-pypi-publish@") == 1
    assert folded.count("--index-url") == 1
    assert "https://pypi.org/simple/" in folded
    assert not (root / ".pypirc").exists()
    for base in (root / ".github", root / "scripts", root / "src"):
        assert not any(base.rglob(".pypirc"))


def _permission_blocks(text: str) -> list[tuple[int, tuple[str, ...]]]:
    blocks: list[tuple[int, tuple[str, ...]]] = []
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
        blocks.append((indentation, tuple(entries)))
    return blocks


def _assert_actions_are_pinned(text: str) -> None:
    actions = _action_uses(text)
    assert actions
    for action in actions:
        assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action), action


def _action_uses(text: str) -> list[str]:
    return re.findall(r"(?m)^\s*uses:\s*(\S+)\s*(?:#.*)?$", text)


def _job_block(text: str, job: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(job)}:\n(?P<body>.*?)(?=^  [a-z][\w-]*:\n|\Z)",
        text,
    )
    assert match is not None
    return match.group("body")


def _workflow_text(name: str) -> str:
    return (Path(__file__).parents[2] / ".github" / "workflows" / name).read_text(
        encoding="utf-8"
    )
