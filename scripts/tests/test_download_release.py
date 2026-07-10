from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

import scripts.download_release as release_module
from scripts.download_release import (
    REPOSITORY,
    ReleaseAsset,
    ReleaseError,
    ResolvedRelease,
    download_release,
    resolve_release,
)

VERSION = "3.0.0"
TAG = f"v{VERSION}"
COMMIT = "1" * 40
ANNOTATED_TAG = "2" * 40
WHEEL_NAME = f"jsondiffview-{VERSION}-py3-none-any.whl"
SDIST_NAME = f"jsondiffview-{VERSION}.tar.gz"
WHEEL_BYTES = b"exact wheel"
SDIST_BYTES = b"exact sdist"


@pytest.mark.parametrize("target", [COMMIT, "main"])
def test_resolve_release_requires_exact_assets_and_green_push(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    payloads = _valid_payloads(target=target)
    monkeypatch.setattr(release_module, "_fetch_json", _fetcher(payloads))

    release = resolve_release(REPOSITORY, TAG, VERSION)

    assert release.tag == TAG
    assert release.version == VERSION
    assert release.commit == COMMIT
    assert release.wheel.name == WHEEL_NAME
    assert release.wheel.sha256 == _digest(WHEEL_BYTES)
    assert release.sdist.name == SDIST_NAME
    assert release.sdist.sha256 == _digest(SDIST_BYTES)


def test_annotated_tag_is_peeled_to_the_exact_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = _valid_payloads()
    payloads[_tag_ref_url()] = {
        "object": {"type": "tag", "sha": ANNOTATED_TAG},
    }
    payloads[f"{_api()}/git/tags/{ANNOTATED_TAG}"] = {
        "object": {"type": "commit", "sha": COMMIT},
    }
    monkeypatch.setattr(release_module, "_fetch_json", _fetcher(payloads))

    assert resolve_release(REPOSITORY, TAG, VERSION).commit == COMMIT


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("draft", True, "must not be a draft"),
        ("prerelease", True, "must not be a prerelease"),
        ("published_at", None, "publication time is malformed"),
        ("published_at", "", "publication time is malformed"),
        ("tag_name", "v3.0.1", "different release tag"),
        ("target_commitish", "maintenance", "neither the tag commit"),
        ("target_commitish", "3" * 40, "differs from the tag commit"),
    ],
)
def test_release_state_mismatch_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    payloads = _valid_payloads()
    release = payloads[_release_url()]
    assert isinstance(release, dict)
    release[field] = value
    monkeypatch.setattr(release_module, "_fetch_json", _fetcher(payloads))

    with pytest.raises(ReleaseError, match=message):
        resolve_release(REPOSITORY, TAG, VERSION)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("head_sha", "4" * 40),
        ("head_branch", "feature"),
        ("event", "workflow_dispatch"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("name", "Other"),
        ("path", ".github/workflows/other.yml"),
        ("head_repository", {"full_name": "attacker/jsondiffview"}),
    ],
)
def test_quality_run_must_be_the_exact_successful_main_push(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    payloads = _valid_payloads()
    quality = payloads[_quality_url()]
    assert isinstance(quality, dict)
    runs = quality["workflow_runs"]
    assert isinstance(runs, list)
    run = runs[0]
    assert isinstance(run, dict)
    run[field] = value
    monkeypatch.setattr(release_module, "_fetch_json", _fetcher(payloads))

    with pytest.raises(ReleaseError, match="no successful Quality workflow"):
        resolve_release(REPOSITORY, TAG, VERSION)


@pytest.mark.parametrize("mutation", ["missing", "unexpected", "duplicate"])
def test_release_asset_set_must_be_exact(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    payloads = _valid_payloads()
    release = payloads[_release_url()]
    assert isinstance(release, dict)
    assets = release["assets"]
    assert isinstance(assets, list)
    if mutation == "missing":
        assets.pop()
    elif mutation == "unexpected":
        assets.append(_asset("notes.txt", b"notes"))
    else:
        assets.append(dict(assets[0]))
    monkeypatch.setattr(release_module, "_fetch_json", _fetcher(payloads))

    with pytest.raises(ReleaseError):
        resolve_release(REPOSITORY, TAG, VERSION)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("digest", "sha512:" + "0" * 64, "valid SHA-256"),
        ("state", "new", "is not uploaded"),
        ("size", 0, "is empty"),
        (
            "browser_download_url",
            "https://example.invalid/archive.whl",
            "unexpected URL",
        ),
    ],
)
def test_release_asset_metadata_must_be_exact(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    payloads = _valid_payloads()
    release = payloads[_release_url()]
    assert isinstance(release, dict)
    assets = release["assets"]
    assert isinstance(assets, list)
    asset = assets[0]
    assert isinstance(asset, dict)
    asset[field] = value
    monkeypatch.setattr(release_module, "_fetch_json", _fetcher(payloads))

    with pytest.raises(ReleaseError, match=message):
        resolve_release(REPOSITORY, TAG, VERSION)


def test_manual_tag_and_repository_are_not_general_inputs() -> None:
    with pytest.raises(ReleaseError, match="unexpected repository"):
        resolve_release("other/jsondiffview", TAG, VERSION)
    with pytest.raises(ReleaseError, match="must be exactly"):
        resolve_release(REPOSITORY, "v3.0.0;echo unsafe", VERSION)


def test_expected_release_values_detect_every_remote_mutation() -> None:
    release = _resolved_release()

    release_module._require_expected_release(
        release,
        commit=COMMIT,
        wheel_sha256=_digest(WHEEL_BYTES),
        sdist_sha256=_digest(SDIST_BYTES),
    )
    with pytest.raises(ReleaseError, match="commit changed"):
        release_module._require_expected_release(
            release,
            commit="9" * 40,
            wheel_sha256=None,
            sdist_sha256=None,
        )
    with pytest.raises(ReleaseError, match="wheel SHA-256 changed"):
        release_module._require_expected_release(
            release,
            commit=None,
            wheel_sha256="9" * 64,
            sdist_sha256=None,
        )


def test_download_verifies_both_hashes_before_exposing_dist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release = _resolved_release()
    content = {
        release.wheel.url: WHEEL_BYTES,
        release.sdist.url: SDIST_BYTES,
    }

    def download(url: str, target: Path) -> None:
        target.write_bytes(content[url])

    monkeypatch.setattr(release_module, "_download", download)
    dist = tmp_path / "dist"

    download_release(release, dist)

    assert (dist / WHEEL_NAME).read_bytes() == WHEEL_BYTES
    assert (dist / SDIST_NAME).read_bytes() == SDIST_BYTES


def test_download_hash_failure_leaves_no_partial_dist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release = _resolved_release()

    def download(_url: str, target: Path) -> None:
        target.write_bytes(b"wrong")

    monkeypatch.setattr(release_module, "_download", download)
    dist = tmp_path / "dist"

    with pytest.raises(ReleaseError, match="SHA-256 differs"):
        download_release(release, dist)

    assert not dist.exists()


def test_download_rejects_archive_path_traversal_before_writing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    release = _resolved_release()
    unsafe = ResolvedRelease(
        tag=release.tag,
        version=release.version,
        commit=release.commit,
        wheel=ReleaseAsset("../outside.whl", release.wheel.sha256, release.wheel.url),
        sdist=release.sdist,
    )
    called = False

    def download(_url: str, _target: Path) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(release_module, "_download", download)

    with pytest.raises(ReleaseError, match="unsafe archive name"):
        download_release(unsafe, tmp_path / "dist")

    assert not called
    assert not (tmp_path / "outside.whl").exists()


def _valid_payloads(*, target: str = COMMIT) -> dict[str, object]:
    return {
        _api(): {"default_branch": "main"},
        _release_url(): {
            "draft": False,
            "prerelease": False,
            "tag_name": TAG,
            "published_at": "2026-07-10T01:16:41Z",
            "target_commitish": target,
            "assets": [
                _asset(WHEEL_NAME, WHEEL_BYTES),
                _asset(SDIST_NAME, SDIST_BYTES),
            ],
        },
        _tag_ref_url(): {
            "object": {"type": "commit", "sha": COMMIT},
        },
        _quality_url(): {
            "workflow_runs": [
                {
                    "head_sha": COMMIT,
                    "head_branch": "main",
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                    "name": "Quality",
                    "path": ".github/workflows/ci.yml",
                    "head_repository": {"full_name": REPOSITORY},
                }
            ]
        },
    }


def _asset(name: str, content: bytes) -> dict[str, object]:
    return {
        "name": name,
        "digest": f"sha256:{_digest(content)}",
        "state": "uploaded",
        "size": len(content),
        "browser_download_url": (
            f"https://github.com/{REPOSITORY}/releases/download/{TAG}/{name}"
        ),
    }


def _resolved_release() -> ResolvedRelease:
    return ResolvedRelease(
        tag=TAG,
        version=VERSION,
        commit=COMMIT,
        wheel=ReleaseAsset(
            WHEEL_NAME,
            _digest(WHEEL_BYTES),
            f"https://github.com/{REPOSITORY}/releases/download/{TAG}/{WHEEL_NAME}",
        ),
        sdist=ReleaseAsset(
            SDIST_NAME,
            _digest(SDIST_BYTES),
            f"https://github.com/{REPOSITORY}/releases/download/{TAG}/{SDIST_NAME}",
        ),
    )


def _fetcher(payloads: dict[str, object]) -> Callable[[str], object]:
    def fetch(url: str) -> object:
        if url.startswith(f"{_api()}/actions/workflows/ci.yml/runs?"):
            return payloads[_quality_url()]
        return payloads[url]

    return fetch


def _api() -> str:
    return f"https://api.github.com/repos/{REPOSITORY}"


def _release_url() -> str:
    return f"{_api()}/releases/tags/{TAG}"


def _tag_ref_url() -> str:
    return f"{_api()}/git/ref/tags/{TAG}"


def _quality_url() -> str:
    return f"{_api()}/actions/workflows/ci.yml/runs"


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
