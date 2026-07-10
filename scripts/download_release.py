"""Resolve and download immutable jsondiffview GitHub Release archives."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

REPOSITORY = "WAcry/jsondiffview"
QUALITY_WORKFLOW = "ci.yml"
PROJECT = "jsondiffview"
_COMMIT = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ReleaseError(RuntimeError):
    """Raised when a release is not an immutable, quality-approved source."""


@dataclass(frozen=True)
class ReleaseAsset:
    """One exact downloadable GitHub Release asset."""

    name: str
    sha256: str
    url: str


@dataclass(frozen=True)
class ResolvedRelease:
    """The exact release identity used by the publication workflow."""

    tag: str
    version: str
    commit: str
    wheel: ReleaseAsset
    sdist: ReleaseAsset


def main(arguments: Sequence[str] | None = None) -> int:
    """Resolve, quality-check, and download a release."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-wheel-sha256")
    parser.add_argument("--expected-sdist-sha256")
    options = parser.parse_args(arguments)

    try:
        version = _project_version(Path("pyproject.toml"))
        release = resolve_release(options.repository, options.tag, version)
        _require_expected_release(
            release,
            commit=options.expected_commit,
            wheel_sha256=options.expected_wheel_sha256,
            sdist_sha256=options.expected_sdist_sha256,
        )
        download_release(release, options.dist)
        if options.github_output is not None:
            _write_github_output(options.github_output, release)
    except (OSError, ReleaseError, ValueError) as error:
        print(f"release download failed: {error}", file=sys.stderr)
        return 1

    print(
        f"downloaded {release.wheel.name} and {release.sdist.name} "
        f"from {release.tag} at {release.commit}"
    )
    return 0


def resolve_release(repository: str, tag: str, version: str) -> ResolvedRelease:
    """Resolve a published final release and its successful Quality run."""

    if repository != REPOSITORY:
        raise ReleaseError(f"unexpected repository: {repository}")
    expected_tag = f"v{version}"
    if tag != expected_tag:
        raise ReleaseError(f"release tag must be exactly {expected_tag}")

    api = f"https://api.github.com/repos/{repository}"
    repository_data = _mapping(_fetch_json(api), "GitHub repository")
    default_branch = _string(
        repository_data.get("default_branch"),
        "GitHub default branch",
    )
    release_data = _mapping(
        _fetch_json(f"{api}/releases/tags/{quote(tag, safe='')}"),
        "GitHub Release",
    )
    if release_data.get("draft") is not False:
        raise ReleaseError("GitHub Release must not be a draft")
    if release_data.get("prerelease") is not False:
        raise ReleaseError("GitHub Release must not be a prerelease")
    if _string(release_data.get("tag_name"), "GitHub Release tag") != tag:
        raise ReleaseError("GitHub returned a different release tag")
    _string(release_data.get("published_at"), "GitHub Release publication time")

    commit = _resolve_tag_commit(api, tag)
    target = _string(
        release_data.get("target_commitish"),
        "GitHub Release target",
    )
    if _COMMIT.fullmatch(target):
        if target != commit:
            raise ReleaseError("GitHub Release target differs from the tag commit")
    elif target != default_branch:
        raise ReleaseError(
            "GitHub Release target is neither the tag commit nor the default branch"
        )
    _require_successful_quality_run(api, commit, default_branch)

    wheel_name = f"{PROJECT}-{version}-py3-none-any.whl"
    sdist_name = f"{PROJECT}-{version}.tar.gz"
    assets = _release_assets(release_data, repository, tag)
    expected_names = {wheel_name, sdist_name}
    if set(assets) != expected_names:
        missing = sorted(expected_names - assets.keys())
        unexpected = sorted(assets.keys() - expected_names)
        raise ReleaseError(
            "GitHub Release assets differ from the exact wheel and sdist: "
            f"missing={missing}, unexpected={unexpected}"
        )

    return ResolvedRelease(
        tag=tag,
        version=version,
        commit=commit,
        wheel=assets[wheel_name],
        sdist=assets[sdist_name],
    )


def download_release(release: ResolvedRelease, dist: Path) -> None:
    """Download both assets, verify their digests, then expose them atomically."""

    expected_names = (
        f"{PROJECT}-{release.version}-py3-none-any.whl",
        f"{PROJECT}-{release.version}.tar.gz",
    )
    actual_names = (release.wheel.name, release.sdist.name)
    if actual_names != expected_names:
        raise ReleaseError("resolved release contains an unsafe archive name")
    if dist.exists() and (not dist.is_dir() or any(dist.iterdir())):
        raise ReleaseError(f"distribution directory must be absent or empty: {dist}")
    if not dist.parent.is_dir():
        raise ReleaseError(f"distribution parent does not exist: {dist.parent}")

    with tempfile.TemporaryDirectory(
        prefix="jsondiffview-release-",
        dir=dist.parent,
    ) as raw:
        staging = Path(raw)
        for asset in (release.wheel, release.sdist):
            target = staging / asset.name
            _download(asset.url, target)
            actual = _sha256(target)
            if actual != asset.sha256:
                raise ReleaseError(
                    f"downloaded {asset.name} SHA-256 differs from GitHub"
                )

        dist.mkdir(exist_ok=True)
        for asset in (release.wheel, release.sdist):
            (staging / asset.name).replace(dist / asset.name)


def _resolve_tag_commit(api: str, tag: str) -> str:
    reference = _mapping(
        _fetch_json(f"{api}/git/ref/tags/{quote(tag, safe='')}"),
        "Git tag reference",
    )
    target = _mapping(reference.get("object"), "Git tag target")
    for _ in range(5):
        target_type = _string(target.get("type"), "Git tag target type")
        sha = _string(target.get("sha"), "Git tag target commit")
        if not _COMMIT.fullmatch(sha):
            raise ReleaseError("Git tag target has an invalid commit")
        if target_type == "commit":
            return sha
        if target_type != "tag":
            raise ReleaseError(f"Git tag resolves to unsupported type {target_type}")
        annotated = _mapping(
            _fetch_json(f"{api}/git/tags/{sha}"),
            "annotated Git tag",
        )
        target = _mapping(annotated.get("object"), "annotated Git tag target")
    raise ReleaseError("Git tag indirection is too deep")


def _require_successful_quality_run(
    api: str,
    commit: str,
    default_branch: str,
) -> None:
    query = urlencode(
        {
            "head_sha": commit,
            "status": "completed",
            "per_page": "100",
        }
    )
    workflow = quote(QUALITY_WORKFLOW, safe="")
    payload = _mapping(
        _fetch_json(f"{api}/actions/workflows/{workflow}/runs?{query}"),
        "Quality workflow runs",
    )
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise ReleaseError("GitHub returned no Quality workflow run list")

    for raw_run in runs:
        run = _mapping(raw_run, "Quality workflow run")
        head_repository = run.get("head_repository")
        if (
            run.get("head_sha") == commit
            and run.get("head_branch") == default_branch
            and run.get("event") == "push"
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and run.get("name") == "Quality"
            and run.get("path") == ".github/workflows/ci.yml"
            and isinstance(head_repository, dict)
            and head_repository.get("full_name") == REPOSITORY
        ):
            return
    raise ReleaseError(
        "no successful Quality workflow exists for the exact tag commit "
        f"on {default_branch}"
    )


def _release_assets(
    release: Mapping[str, object],
    repository: str,
    tag: str,
) -> dict[str, ReleaseAsset]:
    raw_assets = release.get("assets")
    if not isinstance(raw_assets, list):
        raise ReleaseError("GitHub Release has no asset list")

    assets: dict[str, ReleaseAsset] = {}
    for index, raw_asset in enumerate(raw_assets):
        asset = _mapping(raw_asset, f"GitHub Release asset {index}")
        name = _string(asset.get("name"), f"GitHub Release asset {index} name")
        if name in assets:
            raise ReleaseError(f"GitHub Release has duplicate asset {name}")
        if asset.get("state") != "uploaded":
            raise ReleaseError(f"GitHub Release asset {name} is not uploaded")
        if not isinstance(asset.get("size"), int) or cast(int, asset["size"]) <= 0:
            raise ReleaseError(f"GitHub Release asset {name} is empty")
        raw_digest = _string(
            asset.get("digest"),
            f"GitHub Release asset {name} digest",
        )
        algorithm, separator, digest = raw_digest.partition(":")
        if algorithm != "sha256" or not separator or not _SHA256.fullmatch(digest):
            raise ReleaseError(f"GitHub Release asset {name} has no valid SHA-256")
        url = _string(
            asset.get("browser_download_url"),
            f"GitHub Release asset {name} URL",
        )
        expected_path = f"/{repository}/releases/download/{tag}/{name}"
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "github.com"
            or parsed.path != expected_path
            or parsed.query
            or parsed.fragment
        ):
            raise ReleaseError(f"GitHub Release asset {name} has an unexpected URL")
        assets[name] = ReleaseAsset(name=name, sha256=digest, url=url)
    return assets


def _require_expected_release(
    release: ResolvedRelease,
    *,
    commit: str | None,
    wheel_sha256: str | None,
    sdist_sha256: str | None,
) -> None:
    expected = (
        ("commit", commit, release.commit, _COMMIT),
        ("wheel SHA-256", wheel_sha256, release.wheel.sha256, _SHA256),
        ("sdist SHA-256", sdist_sha256, release.sdist.sha256, _SHA256),
    )
    for label, requested, actual, pattern in expected:
        if requested is None:
            continue
        if not pattern.fullmatch(requested) or requested != actual:
            raise ReleaseError(f"{label} changed since the initial preflight")


def _write_github_output(path: Path, release: ResolvedRelease) -> None:
    values = {
        "tag": release.tag,
        "version": release.version,
        "commit": release.commit,
        "wheel-name": release.wheel.name,
        "wheel-sha256": release.wheel.sha256,
        "sdist-name": release.sdist.name,
        "sdist-sha256": release.sdist.sha256,
    }
    with path.open("a", encoding="utf-8", newline="\n") as output:
        for name, value in values.items():
            output.write(f"{name}={value}\n")


def _project_version(pyproject: Path) -> str:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = _mapping(data.get("project"), "pyproject project")
    name = _string(project.get("name"), "pyproject project name")
    if name != PROJECT:
        raise ReleaseError(f"unexpected pyproject project name: {name}")
    version = _string(project.get("version"), "pyproject project version")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ReleaseError("pyproject version must be a final X.Y.Z release")
    return version


def _fetch_json(url: str) -> object:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "jsondiffview-release-verifier/3",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
    except HTTPError as error:
        raise ReleaseError(
            f"GitHub API request failed with HTTP {error.code}"
        ) from error
    except (TimeoutError, URLError) as error:
        raise ReleaseError("GitHub API request failed") from error
    try:
        return cast(object, json.loads(body))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseError("GitHub returned invalid JSON") from error


def _download(url: str, target: Path) -> None:
    request = Request(
        url,
        headers={"User-Agent": "jsondiffview-release-verifier/3"},
    )
    try:
        with (
            urlopen(request, timeout=60) as response,
            target.open("xb") as output,
        ):
            _copy_and_hash(response, output)
    except HTTPError as error:
        raise ReleaseError(
            f"GitHub asset download failed with HTTP {error.code}"
        ) from error
    except (TimeoutError, URLError) as error:
        raise ReleaseError("GitHub asset download failed") from error


def _copy_and_hash(source: BinaryIO, target: BinaryIO) -> None:
    shutil.copyfileobj(source, target, length=1024 * 1024)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ReleaseError(f"{label} is malformed")
    return cast(Mapping[str, object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReleaseError(f"{label} is malformed")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
