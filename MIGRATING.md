# Migrating from jsondiffview 2.1.2 to 3.0.0

Version 3 is an intentional hard break. The `jsondiffview` distribution and
`jdv` command keep their names, but the Python package, module entry point,
views, matching behavior, and review grammar changed.

| v2.1.2 | v3.0.0 |
| --- | --- |
| Distribution `jsondiffview` | unchanged |
| Command `jdv` | unchanged |
| Import package `jdv` | `jsondiffview` |
| `python -m jdv` | `python -m jsondiffview` |
| Default view `compact` | default view `review` |
| `--view compact` | `--view summary` |
| `--view focus` | `--view review` |
| `--view full` | unchanged |
| v2 annotated output | v3 explicit two-column grammar |

There are no runtime aliases or deprecation shims. In particular,
`python -m jdv`, `compact`, and `focus` are rejected rather than translated.
The v3 output is not byte-compatible with v2, and review text remains a
human-facing format rather than stable machine output. Automation should use
the stream and status contract:

- `0`: equal; stdout is empty
- `1`: different; the review is on stdout
- `2`: usage, input, parse, or output error; the diagnostic is on stderr

Array matching now separates safe duplicate-value alignment from evidence
strong enough to report identity or movement. String output uses grapheme-safe
segmentation, display-cell-bounded excerpts, adaptive single-line
classification, and bounded multiline pairing. Existing output snapshots
should therefore be reviewed and regenerated.

Python 3.11 and newer remain supported; the 3.0.0 quality matrix covers
CPython 3.11 through 3.14. Imports of v2 internals were never a supported public
Python API and are not carried forward.

This source tree prepares local 3.0.0 artifacts but does not publish them.
Until a separate release is performed, a generic package-index install may
still resolve the public 2.1.2 release. Build and install the local wheel when
testing this migration.
