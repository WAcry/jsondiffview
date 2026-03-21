# Releasing jsondiffview

This document describes the release process for `jsondiffview` `1.x`.
The repository is expected to publish through GitHub Actions using Trusted Publishing for both TestPyPI and PyPI.

## One-Time Setup

Complete these steps before pushing the first release tag:

1. Create the GitHub repository that will host the release, or rename the existing remote repository to `jsondiffview`.
2. Confirm that `pyproject.toml` project URLs point to `https://github.com/WAcry/jsondiffview`.
3. Enable GitHub Actions for the repository.
4. Create GitHub environments named `testpypi` and `pypi`.
5. Configure a required reviewer for the `pypi` environment.
6. Create and verify accounts on TestPyPI and PyPI.
7. Enable 2FA on both package indexes.
8. Configure Trusted Publishers on TestPyPI and PyPI for `.github/workflows/publish.yml`.
9. Confirm that the package name `jsondiffview` is still available before the first public upload.

## Local Pre-Release Validation

Run all commands from the repository root:

```bash
uv run pytest
uv build --no-sources
uvx twine check dist/*
```

Validate the built wheel in a clean virtual environment:

```bash
python -m venv .venv-release
. .venv-release/bin/activate
python -m pip install dist/jsondiffview-1.0.0-py3-none-any.whl
jsondiffview --help
jsondiffview --version
```

On Windows PowerShell, use:

```powershell
py -3.11 -m venv .venv-release
.\.venv-release\Scripts\python -m pip install .\dist\jsondiffview-1.0.0-py3-none-any.whl
.\.venv-release\Scripts\jsondiffview --help
.\.venv-release\Scripts\jsondiffview --version
```

If you want an end-to-end diff smoke test, create two minimal JSON files and run:

```bash
jsondiffview before.json after.json --view changed --array-match smart --match id
```

## Release Procedure

1. Merge the release-ready branch into `main`.
2. Pull the latest `main` locally and rerun the local validation commands.
3. Create an annotated tag such as `v1.0.0`.
4. Push `main` and the tag.
5. Wait for `.github/workflows/publish.yml` to build the artifacts, validate them, and upload to TestPyPI.
6. Verify the TestPyPI project page, including README rendering and package metadata.
7. Install `jsondiffview==1.0.0` from TestPyPI in a fresh virtual environment and rerun `jsondiffview --help`.
8. Approve the `pypi` GitHub environment only after TestPyPI validation succeeds.
9. Wait for the workflow to publish to PyPI and create the GitHub Release.
10. Perform one final install test from PyPI in a fresh virtual environment.

## TestPyPI Smoke Test

Unix-like shells:

```bash
python -m venv .venv-testpypi
. .venv-testpypi/bin/activate
python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple jsondiffview==1.0.0
jsondiffview --help
```

Windows PowerShell:

```powershell
py -3.11 -m venv .venv-testpypi
.\.venv-testpypi\Scripts\python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple jsondiffview==1.0.0
.\.venv-testpypi\Scripts\jsondiffview --help
```

## Failure Handling

- If local tests or `twine check` fail, fix the branch before creating a tag.
- If TestPyPI upload or installation fails, do not approve the `pypi` environment.
- If the publish workflow is misconfigured, fix the workflow and create a new tag for the next attempt.
- If PyPI already accepted a broken release, publish a higher patch version instead of trying to overwrite the same files.
- If the package name becomes unavailable before the first upload, stop and update the release plan before proceeding.
