# Releasing jsondiffview

This repository now produces the `jsondiffview` package while keeping `jdv` as the only supported CLI command. The intended GitHub destination is `https://github.com/WAcry/jsondiffview`, and the intended first takeover release from this codebase is `v2.1.0`.

The publish workflow keeps the same operational shape as the previous repository:

1. Build and validate artifacts.
2. Publish automatically to TestPyPI.
3. Install and smoke test the uploaded TestPyPI package.
4. Wait for manual approval on the `pypi` GitHub environment.
5. Publish to the official PyPI index.
6. Create a GitHub Release with the built artifacts attached.

## External prerequisites

These settings live outside git and must still exist after force-pushing this repository into `WAcry/jsondiffview`:

1. GitHub environments named `testpypi` and `pypi`.
2. A required reviewer configured on the `pypi` environment.
3. Trusted Publisher entries on both TestPyPI and PyPI that point at `.github/workflows/publish.yml` in `WAcry/jsondiffview`.

If any of those settings were lost, the workflow YAML in this repository is not enough to restore publishing by itself.

## Local validation

Run all commands from the repository root:

```bash
uv run pytest -q
uv build --no-sources
uvx twine check dist/*
python -m venv .venv-release
. .venv-release/Scripts/activate
python -m pip install dist/jsondiffview-2.1.0-py3-none-any.whl
jdv --help
jdv --version
python -m jdv --help
```

For a quick behavior smoke test:

```bash
cat > left.json <<'JSON'
{"value":1}
JSON

cat > right.json <<'JSON'
{"value":2}
JSON

jdv left.json right.json --color never
```

Expected output includes:

```text
~ "value": 1 -> 2
```

## Takeover procedure

1. Confirm the current contents of `WAcry/jsondiffview` can be replaced.
2. Point this repository at the target remote:

   ```bash
   git remote add origin https://github.com/WAcry/jsondiffview
   git push --force-with-lease origin HEAD:main
   ```

   If `origin` already exists, update it with `git remote set-url origin https://github.com/WAcry/jsondiffview` before pushing. If you prefer to merge or fast-forward your local `main` first, confirm that `main` already points at the reviewed takeover commit before pushing it.

3. Re-check the external prerequisites listed above in GitHub, TestPyPI, and PyPI.
4. Re-run the local validation commands.
5. Create and push the release tag:

   ```bash
   git tag -a v2.1.0 -m "Release 2.1.0"
   git push origin v2.1.0
   ```

6. Wait for `.github/workflows/publish.yml` to:
   - build and validate the distributions
   - publish to TestPyPI automatically
   - smoke test `jsondiffview==2.1.0` from TestPyPI
7. Verify the TestPyPI project page, including README rendering and package metadata.
8. Verify the TestPyPI installation by checking `jdv --help` and `jdv --version` in a fresh environment.
9. Approve the `pypi` environment only after both TestPyPI validations succeed.
10. Wait for the PyPI publish and GitHub Release jobs to finish.

## About `1.0.0`

Repository code cannot disable the existing `jsondiffview==1.0.0` release on PyPI. If you want to de-emphasize or disable it, do that as a separate manual PyPI action after `2.1.0` is live.

The safest option is to yank `1.0.0` from the PyPI web UI so new installers no longer pick it by default while existing locked installations keep working.
