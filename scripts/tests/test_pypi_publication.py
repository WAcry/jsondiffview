from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator, Mapping, MutableSequence, Set
from pathlib import Path

import pytest

from scripts.prepare_publisher_compat import prepare
from scripts.publisher_compat import (
    ACTION_COMMIT,
    ACTION_TAG,
    MANIFEST_NAME,
    PACKAGING_TREE_SHA256,
    PACKAGING_VERSION,
    packaging_tree_sha256,
    patch_metadata_parser,
    publisher_manifest,
)
from scripts.pypi_publication import (
    Distribution,
    PreflightResult,
    PublicationError,
    PublishState,
    classify_release,
    local_distributions,
    preflight,
    stage_missing_distributions,
    wait_for_exact_release,
)

PROJECT = "jsondiffview"
VERSION = "3.0.0"


@pytest.fixture
def expected(tmp_path: Path) -> tuple[Distribution, Distribution]:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / f"{PROJECT}-{VERSION}-py3-none-any.whl").write_bytes(b"wheel")
    (dist / f"{PROJECT}-{VERSION}.tar.gz").write_bytes(b"sdist")
    return local_distributions(dist, VERSION)


def test_absent_release_needs_every_file(
    expected: tuple[Distribution, Distribution],
) -> None:
    result = classify_release(
        expected,
        None,
        project=PROJECT,
        version=VERSION,
    )

    assert result == PreflightResult(
        PublishState.ABSENT,
        tuple(item.filename for item in expected),
    )
    assert result.needs_publish


def test_exact_release_is_a_successful_noop(
    expected: tuple[Distribution, Distribution],
) -> None:
    result = classify_release(
        expected,
        _payload(expected),
        project=PROJECT,
        version=VERSION,
    )

    assert result == PreflightResult(PublishState.EXACT, ())
    assert not result.needs_publish


@pytest.mark.parametrize("present_index", [0, 1])
def test_partial_exact_release_identifies_only_the_missing_file(
    expected: tuple[Distribution, Distribution],
    present_index: int,
) -> None:
    result = classify_release(
        expected,
        _payload((expected[present_index],)),
        project=PROJECT,
        version=VERSION,
    )

    missing = expected[1 - present_index].filename
    assert result == PreflightResult(PublishState.PARTIAL, (missing,))
    assert result.needs_publish


@pytest.mark.parametrize("present_index", [0, 1])
def test_partial_release_stages_only_the_proven_missing_file(
    tmp_path: Path,
    expected: tuple[Distribution, Distribution],
    present_index: int,
) -> None:
    result = classify_release(
        expected,
        _payload((expected[present_index],)),
        project=PROJECT,
        version=VERSION,
    )
    destination = tmp_path / "publish-dist"

    stage_missing_distributions(
        expected,
        result,
        source=tmp_path / "dist",
        destination=destination,
    )

    missing = expected[1 - present_index]
    assert [path.name for path in destination.iterdir()] == [missing.filename]
    assert (destination / missing.filename).read_bytes() in {b"wheel", b"sdist"}


def test_absent_release_stages_both_exact_files(
    tmp_path: Path,
    expected: tuple[Distribution, Distribution],
) -> None:
    result = classify_release(
        expected,
        None,
        project=PROJECT,
        version=VERSION,
    )
    destination = tmp_path / "publish-dist"

    stage_missing_distributions(
        expected,
        result,
        source=tmp_path / "dist",
        destination=destination,
    )

    assert {path.name for path in destination.iterdir()} == {
        item.filename for item in expected
    }


def test_exact_release_creates_no_publication_staging_directory(
    tmp_path: Path,
    expected: tuple[Distribution, Distribution],
) -> None:
    result = classify_release(
        expected,
        _payload(expected),
        project=PROJECT,
        version=VERSION,
    )
    destination = tmp_path / "publish-dist"

    stage_missing_distributions(
        expected,
        result,
        source=tmp_path / "dist",
        destination=destination,
    )

    assert not destination.exists()


def test_staging_fails_if_a_distribution_changes_after_preflight(
    tmp_path: Path,
    expected: tuple[Distribution, Distribution],
) -> None:
    result = classify_release(
        expected,
        None,
        project=PROJECT,
        version=VERSION,
    )
    (tmp_path / "dist" / expected[0].filename).write_bytes(b"changed")

    with pytest.raises(PublicationError, match="changed after preflight"):
        stage_missing_distributions(
            expected,
            result,
            source=tmp_path / "dist",
            destination=tmp_path / "publish-dist",
        )

    assert not (tmp_path / "publish-dist").exists()


def test_conflicting_existing_filename_fails_without_upload(
    expected: tuple[Distribution, Distribution],
) -> None:
    conflicting = Distribution(expected[0].filename, "0" * 64)

    with pytest.raises(PublicationError, match="conflicts"):
        classify_release(
            expected,
            _payload((conflicting,)),
            project=PROJECT,
            version=VERSION,
        )


def test_unexpected_existing_filename_fails_without_upload(
    expected: tuple[Distribution, Distribution],
) -> None:
    unexpected = Distribution(
        f"{PROJECT}-{VERSION}-cp314-cp314-win_amd64.whl",
        "1" * 64,
    )

    with pytest.raises(PublicationError, match="unexpected release files"):
        classify_release(
            expected,
            _payload((*expected, unexpected)),
            project=PROJECT,
            version=VERSION,
        )


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"info": {"name": "other", "version": VERSION}, "urls": []},
            "different project",
        ),
        (
            {"info": {"name": PROJECT, "version": "3.0.1"}, "urls": []},
            "different version",
        ),
        (
            {"info": {"name": PROJECT, "version": VERSION}, "urls": "bad"},
            "no file list",
        ),
    ],
)
def test_malformed_or_misdirected_pypi_release_fails_closed(
    expected: tuple[Distribution, Distribution],
    payload: object,
    message: str,
) -> None:
    with pytest.raises(PublicationError, match=message):
        classify_release(
            expected,
            payload,
            project=PROJECT,
            version=VERSION,
        )


def test_duplicate_remote_filename_fails_closed(
    expected: tuple[Distribution, Distribution],
) -> None:
    payload = _payload((expected[0], expected[0]))

    with pytest.raises(PublicationError, match="duplicate filename"):
        classify_release(
            expected,
            payload,
            project=PROJECT,
            version=VERSION,
        )


def test_existing_release_with_no_files_is_not_treated_as_absent(
    expected: tuple[Distribution, Distribution],
) -> None:
    with pytest.raises(PublicationError, match="exists but exposes no files"):
        classify_release(
            expected,
            _payload(()),
            project=PROJECT,
            version=VERSION,
        )


def test_invalid_remote_digest_fails_closed(
    expected: tuple[Distribution, Distribution],
) -> None:
    payload = _payload(expected)
    assert isinstance(payload, dict)
    urls = payload["urls"]
    assert isinstance(urls, list)
    first = urls[0]
    assert isinstance(first, dict)
    first["digests"] = {"sha256": "not-a-digest"}

    with pytest.raises(PublicationError, match="invalid SHA-256"):
        classify_release(
            expected,
            payload,
            project=PROJECT,
            version=VERSION,
        )


def test_preflight_uses_injected_offline_fetch(
    expected: tuple[Distribution, Distribution],
) -> None:
    calls: list[tuple[str, str]] = []

    def fetch(project: str, version: str) -> object:
        calls.append((project, version))
        return _payload(expected)

    result = preflight(
        expected,
        project=PROJECT,
        version=VERSION,
        fetch=fetch,
    )

    assert result.state is PublishState.EXACT
    assert calls == [(PROJECT, VERSION)]


def test_propagation_polls_absent_then_partial_then_exact(
    expected: tuple[Distribution, Distribution],
) -> None:
    responses: Iterator[object | None] = iter(
        [
            None,
            _payload((expected[0],)),
            _payload(expected),
        ]
    )
    sleeps: list[float] = []

    result = wait_for_exact_release(
        expected,
        project=PROJECT,
        version=VERSION,
        attempts=3,
        delay_seconds=2.5,
        fetch=lambda _project, _version: next(responses),
        sleep=sleeps.append,
    )

    assert result.state is PublishState.EXACT
    assert sleeps == [2.5, 2.5]


def test_propagation_timeout_is_bounded(
    expected: tuple[Distribution, Distribution],
) -> None:
    calls = 0
    sleeps: list[float] = []

    def fetch(_project: str, _version: str) -> object:
        nonlocal calls
        calls += 1
        return _payload((expected[0],))

    with pytest.raises(PublicationError, match="after 4 attempts"):
        wait_for_exact_release(
            expected,
            project=PROJECT,
            version=VERSION,
            attempts=4,
            delay_seconds=1,
            fetch=fetch,
            sleep=sleeps.append,
        )

    assert calls == 4
    assert sleeps == [1, 1, 1]


def test_conflict_during_propagation_fails_immediately(
    expected: tuple[Distribution, Distribution],
) -> None:
    conflict = Distribution(expected[1].filename, "f" * 64)
    sleeps: list[float] = []

    with pytest.raises(PublicationError, match="conflicts"):
        wait_for_exact_release(
            expected,
            project=PROJECT,
            version=VERSION,
            attempts=5,
            delay_seconds=1,
            fetch=lambda _project, _version: _payload((conflict,)),
            sleep=sleeps.append,
        )

    assert sleeps == []


def test_local_distribution_set_rejects_non_release_files(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / f"{PROJECT}-{VERSION}-py3-none-any.whl").write_bytes(b"wheel")
    (dist / f"{PROJECT}-{VERSION}.tar.gz").write_bytes(b"sdist")
    (dist / "unreviewed.txt").write_text("extra", encoding="utf-8")

    with pytest.raises(PublicationError, match="exactly"):
        local_distributions(dist, VERSION)


@pytest.mark.parametrize(
    ("project", "version"),
    [("other", VERSION), (PROJECT, "3.0.0;unsafe")],
)
def test_local_distribution_identity_is_not_user_configurable(
    tmp_path: Path,
    project: str,
    version: str,
) -> None:
    with pytest.raises(PublicationError):
        local_distributions(tmp_path, version, project=project)


def test_metadata25_compatibility_patch_is_narrow_and_idempotent() -> None:
    tables = _FakeMetadataTables()

    patch_metadata_parser(
        tables,
        packaging_version="26.2",
        publisher_version="6.1.0",
    )
    patch_metadata_parser(
        tables,
        packaging_version="26.2",
        publisher_version="6.1.0",
    )

    assert tables._VALID_METADATA_VERSIONS == ["2.4", "2.5"]


def test_publisher_action_pin_and_overlay_contract_are_synchronized() -> None:
    workflow = (
        Path(__file__).parents[2] / ".github" / "workflows" / "publish.yml"
    ).read_text(encoding="utf-8")

    assert (
        f"uses: pypa/gh-action-pypi-publish@{ACTION_COMMIT} # {ACTION_TAG}" in workflow
    )
    assert "PYTHONPATH: /github/workspace/.pypi-action-compat" in workflow


@pytest.mark.parametrize(
    ("packaging_version", "publisher_version"),
    [("26.1", "6.1.0"), ("26.2", "6.2.0")],
)
def test_metadata25_compatibility_rejects_dependency_drift(
    packaging_version: str,
    publisher_version: str,
) -> None:
    with pytest.raises(RuntimeError, match="expected"):
        patch_metadata_parser(
            _FakeMetadataTables(),
            packaging_version=packaging_version,
            publisher_version=publisher_version,
        )


def test_publisher_compatibility_overlay_uses_locked_parser(tmp_path: Path) -> None:
    destination = tmp_path / "publisher-compat"

    prepare(destination)

    assert (destination / "packaging" / "__init__.py").is_file()
    assert packaging_tree_sha256(destination / "packaging") == PACKAGING_TREE_SHA256
    assert (
        json.loads((destination / MANIFEST_NAME).read_text(encoding="utf-8"))
        == publisher_manifest()
    )
    assert (
        (destination / "sitecustomize.py")
        .read_text(encoding="utf-8")
        .startswith('"""Narrow compatibility bridge')
    )
    assert not list(destination.rglob("__pycache__"))
    with pytest.raises(RuntimeError, match="already exists"):
        prepare(destination)


def test_overlay_wins_after_the_action_prepends_its_packaging(
    tmp_path: Path,
) -> None:
    overlay = tmp_path / "publisher-compat"
    prepare(overlay)
    action_site = _fake_action_site(tmp_path, twine_version="6.1.0")

    result = _run_overlay_python(
        overlay,
        action_site,
        (
            "import packaging\n"
            "from packaging import metadata\n"
            f"assert packaging.__version__ == {PACKAGING_VERSION!r}\n"
            "assert '2.5' in metadata._VALID_METADATA_VERSIONS\n"
            "print('overlay-active')\n"
        ),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "overlay-active\n"
    assert result.stderr == ""


@pytest.mark.parametrize(
    "mutation",
    ["packaging", "twine"],
)
def test_sitecustomize_activation_failure_stops_before_uploader_code(
    tmp_path: Path,
    mutation: str,
) -> None:
    overlay = tmp_path / "publisher-compat"
    prepare(overlay)
    twine_version = "6.2.0" if mutation == "twine" else "6.1.0"
    action_site = _fake_action_site(tmp_path, twine_version=twine_version)
    if mutation == "packaging":
        with (overlay / "packaging" / "__init__.py").open(
            "a",
            encoding="utf-8",
            newline="\n",
        ) as source:
            source.write("\n# unexpected mutation\n")

    result = _run_overlay_python(
        overlay,
        action_site,
        "print('uploader-code-ran')\n",
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert "publisher compatibility activation failed" in result.stderr
    assert "uploader-code-ran" not in result.stderr


def _payload(files: tuple[Distribution, ...]) -> object:
    return {
        "info": {
            "name": PROJECT,
            "version": VERSION,
        },
        "urls": [
            {
                "filename": item.filename,
                "digests": {"sha256": item.sha256},
            }
            for item in files
        ],
    }


def _fake_action_site(tmp_path: Path, *, twine_version: str) -> Path:
    action_site = tmp_path / f"action-site-{twine_version}"
    action_site.mkdir()
    packaging_package = action_site / "packaging"
    packaging_package.mkdir()
    (packaging_package / "__init__.py").write_text(
        '__version__ = "25.0"\n',
        encoding="utf-8",
        newline="\n",
    )
    (packaging_package / "metadata.py").write_text(
        "_VALID_METADATA_VERSIONS = ['2.4']\n"
        "_EMAIL_TO_RAW_MAPPING = {}\n"
        "_LIST_FIELDS = set()\n",
        encoding="utf-8",
        newline="\n",
    )
    twine_package = action_site / "twine"
    twine_package.mkdir()
    (twine_package / "__init__.py").write_text("", encoding="utf-8")
    (twine_package / "package.py").write_text(
        "from packaging import metadata\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_distribution_metadata(action_site, "packaging", "25.0")
    _write_distribution_metadata(action_site, "twine", twine_version)
    return action_site


def _write_distribution_metadata(
    site: Path,
    name: str,
    version: str,
) -> None:
    dist_info = site / f"{name}-{version}.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
        newline="\n",
    )


def _run_overlay_python(
    overlay: Path,
    action_site: Path,
    code: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONPATH"] = os.pathsep.join((str(action_site), str(overlay)))
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=overlay.parent,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )


class _FakeMetadataTables:
    def __init__(self) -> None:
        self._VALID_METADATA_VERSIONS: MutableSequence[str] = ["2.4"]
        self._EMAIL_TO_RAW_MAPPING: Mapping[str, str] = {"import-name": "import_names"}
        self._LIST_FIELDS: Set[str] = {"import_names"}
