"""Preflight and verify immutable PyPI release files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

PROJECT = "jsondiffview"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class PublicationError(RuntimeError):
    """Raised when publication cannot proceed without changing release files."""


class PublishState(StrEnum):
    """Safe states of the requested version on PyPI."""

    ABSENT = "absent"
    EXACT = "exact"
    PARTIAL = "partial"


@dataclass(frozen=True)
class Distribution:
    """One immutable distribution filename and digest."""

    filename: str
    sha256: str


@dataclass(frozen=True)
class PreflightResult:
    """A classified PyPI release and the files that remain unpublished."""

    state: PublishState
    missing: tuple[str, ...]

    @property
    def needs_publish(self) -> bool:
        """Whether at least one expected file is absent from PyPI."""

        return bool(self.missing)


FetchRelease = Callable[[str, str], object | None]
Sleep = Callable[[float], None]


def local_distributions(
    dist: Path,
    version: str,
    *,
    project: str = PROJECT,
) -> tuple[Distribution, Distribution]:
    """Hash the exact wheel and sdist that may be published."""

    if project != PROJECT:
        raise PublicationError(f"unexpected project: {project}")
    if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) is None:
        raise PublicationError("version must be a final X.Y.Z release")
    wheel_name = f"{project}-{version}-py3-none-any.whl"
    sdist_name = f"{project}-{version}.tar.gz"
    expected_names = (wheel_name, sdist_name)
    if not dist.is_dir():
        raise PublicationError(f"distribution directory does not exist: {dist}")

    entries = tuple(dist.iterdir())
    if any(not path.is_file() or path.is_symlink() for path in entries):
        raise PublicationError("distribution directory contains a non-file entry")
    actual_names = tuple(sorted(path.name for path in entries))
    if actual_names != tuple(sorted(expected_names)):
        raise PublicationError(
            "distribution directory must contain exactly "
            f"{', '.join(expected_names)}; found {', '.join(actual_names) or 'nothing'}"
        )

    return (
        Distribution(filename=wheel_name, sha256=_sha256(dist / wheel_name)),
        Distribution(filename=sdist_name, sha256=_sha256(dist / sdist_name)),
    )


def fetch_pypi_release(project: str, version: str) -> object | None:
    """Fetch a version from PyPI's JSON API, returning None for a 404."""

    url = (
        "https://pypi.org/pypi/"
        f"{quote(project, safe='')}/{quote(version, safe='')}/json"
    )
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "User-Agent": "jsondiffview-publication-verifier/3",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
    except HTTPError as error:
        if error.code == 404:
            return None
        raise PublicationError(
            f"PyPI JSON request failed with HTTP {error.code}"
        ) from error
    except (TimeoutError, URLError) as error:
        raise PublicationError("PyPI JSON request failed") from error

    try:
        return cast(object, json.loads(body))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PublicationError("PyPI returned invalid JSON") from error


def classify_release(
    expected: Sequence[Distribution],
    payload: object | None,
    *,
    project: str,
    version: str,
) -> PreflightResult:
    """Classify remote files, rejecting every non-exact existing file."""

    expected_by_name = {item.filename: item.sha256 for item in expected}
    if len(expected_by_name) != len(expected):
        raise PublicationError("expected distribution filenames are not unique")
    if payload is None:
        return PreflightResult(PublishState.ABSENT, tuple(expected_by_name))

    release = _mapping(payload, "PyPI response")
    info = _mapping(release.get("info"), "PyPI info")
    remote_name = _string(info.get("name"), "PyPI project name")
    remote_version = _string(info.get("version"), "PyPI version")
    if _normalize_project(remote_name) != _normalize_project(project):
        raise PublicationError("PyPI returned a different project")
    if remote_version != version:
        raise PublicationError("PyPI returned a different version")

    urls = release.get("urls")
    if not isinstance(urls, list):
        raise PublicationError("PyPI response has no file list")

    remote_by_name: dict[str, str] = {}
    for index, raw_file in enumerate(urls):
        remote_file = _mapping(raw_file, f"PyPI file {index}")
        filename = _string(remote_file.get("filename"), f"PyPI file {index} name")
        digests = _mapping(remote_file.get("digests"), f"PyPI file {filename} digests")
        digest = _string(digests.get("sha256"), f"PyPI file {filename} SHA-256")
        if not _SHA256.fullmatch(digest):
            raise PublicationError(f"PyPI file {filename} has an invalid SHA-256")
        if filename in remote_by_name:
            raise PublicationError(f"PyPI lists duplicate filename {filename}")
        remote_by_name[filename] = digest

    unexpected = tuple(sorted(remote_by_name.keys() - expected_by_name.keys()))
    if unexpected:
        raise PublicationError(
            f"PyPI has unexpected release files: {', '.join(unexpected)}"
        )

    for filename, remote_digest in remote_by_name.items():
        if remote_digest != expected_by_name[filename]:
            raise PublicationError(
                f"PyPI file {filename} conflicts with the GitHub Release SHA-256"
            )
    if not remote_by_name:
        raise PublicationError("PyPI release exists but exposes no files")

    missing = tuple(
        filename for filename in expected_by_name if filename not in remote_by_name
    )
    state = PublishState.PARTIAL if missing else PublishState.EXACT
    return PreflightResult(state, missing)


def preflight(
    expected: Sequence[Distribution],
    *,
    project: str,
    version: str,
    fetch: FetchRelease = fetch_pypi_release,
) -> PreflightResult:
    """Fetch and classify the current PyPI state once."""

    return classify_release(
        expected,
        fetch(project, version),
        project=project,
        version=version,
    )


def stage_missing_distributions(
    expected: Sequence[Distribution],
    result: PreflightResult,
    *,
    source: Path,
    destination: Path,
) -> None:
    """Atomically stage only files proven absent during the latest preflight."""

    expected_by_name = {item.filename: item for item in expected}
    missing = set(result.missing)
    if len(expected_by_name) != len(expected):
        raise PublicationError("expected distribution filenames are not unique")
    if len(missing) != len(result.missing) or not missing <= expected_by_name.keys():
        raise PublicationError("preflight returned an invalid missing-file set")
    if destination.exists():
        raise PublicationError(
            f"publication staging path already exists: {destination}"
        )
    if not destination.parent.is_dir():
        raise PublicationError(
            f"publication staging parent does not exist: {destination.parent}"
        )
    if not missing:
        return

    source_resolved = source.resolve()
    destination_resolved = destination.resolve(strict=False)
    if (
        destination_resolved == source_resolved
        or source_resolved in destination_resolved.parents
    ):
        raise PublicationError("publication staging path must be outside dist")

    with tempfile.TemporaryDirectory(
        prefix="jsondiffview-publish-",
        dir=destination.parent,
    ) as raw:
        staging = Path(raw) / destination.name
        staging.mkdir()
        for filename in result.missing:
            distribution = expected_by_name[filename]
            source_path = source / filename
            if (
                not source_path.is_file()
                or source_path.is_symlink()
                or _sha256(source_path) != distribution.sha256
            ):
                raise PublicationError(
                    f"distribution changed after preflight: {filename}"
                )
            target = staging / filename
            shutil.copyfile(source_path, target)
            if _sha256(target) != distribution.sha256:
                raise PublicationError(
                    f"staged distribution SHA-256 differs: {filename}"
                )
        staging.replace(destination)


def wait_for_exact_release(
    expected: Sequence[Distribution],
    *,
    project: str,
    version: str,
    attempts: int,
    delay_seconds: float,
    fetch: FetchRelease = fetch_pypi_release,
    sleep: Sleep = time.sleep,
) -> PreflightResult:
    """Poll a bounded number of times until PyPI exposes exactly the release."""

    if attempts < 1:
        raise ValueError("attempts must be positive")
    if delay_seconds < 0:
        raise ValueError("delay must be non-negative")

    last = PreflightResult(
        PublishState.ABSENT,
        tuple(item.filename for item in expected),
    )
    for attempt in range(attempts):
        last = preflight(
            expected,
            project=project,
            version=version,
            fetch=fetch,
        )
        if last.state is PublishState.EXACT:
            return last
        if attempt + 1 < attempts:
            sleep(delay_seconds)

    missing = ", ".join(last.missing) or "unknown files"
    raise PublicationError(
        f"PyPI did not expose the exact release after {attempts} attempts; "
        f"still missing: {missing}"
    )


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the preflight or bounded verification command."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--github-output", type=Path)
    preflight_parser.add_argument("--stage-dir", type=Path)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--attempts", type=int, default=18)
    verify_parser.add_argument("--delay-seconds", type=float, default=10)

    options = parser.parse_args(arguments)
    try:
        expected = local_distributions(
            options.dist,
            options.version,
            project=PROJECT,
        )
        if options.command == "preflight":
            result = preflight(
                expected,
                project=PROJECT,
                version=options.version,
            )
            if options.stage_dir is not None:
                stage_missing_distributions(
                    expected,
                    result,
                    source=options.dist,
                    destination=options.stage_dir,
                )
            if options.github_output is not None:
                _write_github_output(options.github_output, result)
        else:
            result = wait_for_exact_release(
                expected,
                project=PROJECT,
                version=options.version,
                attempts=options.attempts,
                delay_seconds=options.delay_seconds,
            )
    except (OSError, PublicationError, ValueError) as error:
        print(f"publication check failed: {error}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "state": result.state,
                "needs_publish": result.needs_publish,
                "missing": result.missing,
            },
            sort_keys=True,
        )
    )
    return 0


def _write_github_output(path: Path, result: PreflightResult) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as output:
        output.write(f"state={result.state}\n")
        output.write(f"needs-publish={str(result.needs_publish).lower()}\n")
        output.write(f"missing-files={json.dumps(result.missing)}\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise PublicationError(f"{label} is malformed")
    return cast(Mapping[str, object], value)


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise PublicationError(f"{label} is malformed")
    return value


def _normalize_project(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


if __name__ == "__main__":
    raise SystemExit(main())
