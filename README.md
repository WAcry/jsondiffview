# jsondiffview

`jdv` produces deterministic, JSON-shaped review text for humans. It
compares strict JSON only: the first argument is the old (before) document and
the second is the new (after) document.

The output is annotated review text, not valid JSON, JSON Patch, or an
applyable patch. Additions (`+`), removals (`-`), modifications (`~`), moves
(`>`), omissions (`…`), and intraline spans (`[-old-]`, `[+new+]`) remain
readable without color.

![Terminal screenshot of jdv reviewing nested JSON changes, moves, additions, and removals](https://raw.githubusercontent.com/WAcry/jsondiffview/main/playground/jdv-review.png)

> The package published on PyPI is named `jsondiffview`; the import package is
> also `jsondiffview`, while the installed CLI command is `jdv`.
>
> Upgrading from 2.1.2? Read
> [Migrating to 3.0.0](https://github.com/WAcry/jsondiffview/blob/main/MIGRATING.md).
> Version 3 publication uses only validated GitHub Release archives and the
> protected PyPI Trusted Publisher workflow.

## Install and run

For development:

```console
uv sync
uv run jdv --help
```

Or build and install the local wheel:

```console
uv build --no-sources
uv tool install ./dist/jsondiffview-3.0.0-py3-none-any.whl
```

Both entry points use the same implementation:

```console
jdv before.json after.json
python -m jsondiffview before.json after.json
```

One input may be read from stdin:

```console
cat before.json | jdv - after.json
```

Copy-ready PowerShell commands and editable sample documents are available in
the [playground](playground/README.md).

## Command

```text
Usage: jdv [OPTIONS] OLD_JSON NEW_JSON

  Compare strict OLD_JSON (before) with NEW_JSON (after).

Options:
  -v, --view [summary|review|full]
                                  Detail level.  [default: review]
  -k, --match-key FIELD           Array-object identity key; repeat in
                                  priority order. Any occurrence replaces
                                  defaults: id, key, name, title.
  -c, --color [auto|always|never]
                                  Review color policy.  [default: auto]
  -q, --quiet                     Suppress the equality notice only.
  --version                       Show the version and exit.
  -h, --help                      Show this message and exit.
```

Option choices and match-key names are case-sensitive. Repeating
`--match-key` preserves command-line priority and replaces all default keys;
supplying the same key twice is an error. `--` ends option parsing for paths
that begin with `-`. A file literally named `-` is not addressable, and both
arguments cannot use stdin.

### Views

- `review` (default) expands every changed, added, and removed value and keeps
  one adjacent unchanged sibling around each changed run.
- `summary` collapses every unchanged sibling run and may summarize large
  wholly added or removed containers with a bounded first-two-child preview
  and exact omitted-descendant count.
- `full` expands all structural context and added/removed subtrees.

All views use the same semantic comparison. Deterministic long-string safety
limits remain active even in `full`.

### Status and stream contract

| Status | Meaning | stdout | stderr |
| ---: | --- | --- | --- |
| `0` | Documents are equal | empty | `No semantic differences.` |
| `1` | Differences were reviewed successfully | one review | empty |
| `2` | Usage, input, parse, or output error | empty unless output failed | one diagnostic |

Status `1` is an expected `diff`-style result, not an operational failure.
`--quiet` suppresses only the equality notice. A closed stdout pipe exits `2`
without a diagnostic or traceback.

A CI-safe shell pattern is:

```sh
set +e
jdv --color never before.json after.json
status=$?
set -e
if [ "$status" -gt 1 ]; then
  exit "$status"
fi
```

## Review format

Every physical line starts with a two-column semantic prefix. Object keys are
JSON strings; array entries use new indexes such as `[2]:`, while unmatched
removals use old indexes such as `[old 4]:`.

```text
~ {
~   "services": [
      [0]: {
        "id": "api",
…       1 unchanged field omitted
      },
>     moved from $.services[2] to $.services[1] (matched by "id": "db")
      [1]: {
        "id": "db",
…       1 unchanged field omitted
      },
~     [2]: {
        "id": "worker",
~       "port": 9000 -> 9001
      }
    ],
~   "title": "Hello [-world-][+team+]",
-   "obsolete": true
  }
```

Modified short strings use Unicode grapheme-safe word-, whitespace-, and
punctuation-segment spans. When one identifier or number segment has a useful
shared prefix or suffix, finer grapheme detail is used without splitting a
user-perceived character. Multiline strings are compared as exact logical
lines, with line terminators visible as JSON escapes; sufficiently similar
replacement lines can show side-specific intraline spans. Over-budget
multiline changes retain bounded first/last previews with exact omitted line
and code-point counts. Adaptive classification keeps prose inline while
routing dense separators and opaque runs to bounded hunk output. Long
single-line strings report Unicode code-point lengths, half-open offsets,
display-cell-bounded excerpts, and exact omission counts. All matching and
output limits are deterministic work counters, including in `full`. Strings
shown only on one side or as unchanged context are also bounded at 512 code
points, including values containing line breaks.

The main review above includes a pure move (`db`). Array removals retain their
old index:

```text
~ [
    [0]: "keep",
-   [old 1]: "gone"
  ]
```

A moved entry can also contain a nested modification:

```text
~ [
>   moved from $[1] to $[0] (matched by "id": "b")
~   [0]: {
      "id": "b",
~     "v": 1 -> 2
    },
    [1]: {
      "id": "a",
…     1 unchanged field omitted
    }
  ]
```

Ambiguous identity values remain explicit additions and removals:

```text
~ [
+   [0]: {
+     "id": "x",
+     "v": 3
+   },
+   [1]: {
+     "id": "x",
+     "v": 4
+   },
-   [old 0]: {
-     "id": "x",
-     "v": 1
-   },
-   [old 1]: {
-     "id": "x",
-     "v": 2
-   }
  ]
```

Color is presentation only: yellow marks modifications, red removals, green
additions, and cyan move provenance. `--color auto` requires a terminal and an
absent or empty `NO_COLOR`; `always` overrides both redirection and
`NO_COLOR`; `never` disables ANSI. `FORCE_COLOR` is intentionally ignored.

## Strict JSON and matching

Inputs use RFC JSON syntax with unique object names and project-owned numeric
limits:

- UTF-8 and an optional leading UTF-8 BOM are accepted.
- Duplicate object keys, `NaN`, `Infinity`, and `-Infinity` are rejected.
- Integer literals are limited to 4,300 digits.
- Decimal/exponent lexemes are limited to 10,000 code points.
- Container nesting is limited to 256 levels; there is no global file-size
  limit.
- A decimal/exponent value whose binary64 conversion is non-finite, such as
  `1e999`, is rejected.
- Integer `1`, decimal/exponent `1.0`, boolean `true`, and string `"1"` are
  distinct. Decimal spellings `1.0` and `1.00` compare equal.
- Object member order is ignored; array order matters.

Array entries are never paired by position or fuzzy similarity. Object entries
pair only when a configured identity value is unique on both sides. The
defaults are `id`, `key`, `name`, and `title`; use `-k FIELD` to replace them.
Remaining globally unique entries pair by exact strict value. Repeated exact
values may align monotonically to stabilize the review, but that alignment is
not identity evidence and never fabricates a move. Other ambiguous values
remain a removal plus an addition. Null, object, and array identity-key values
are unavailable, and a lower-priority key cannot override conflicting
higher-priority scalar identities.

Moves are the minimal deterministic relative-order changes among matched
entries. Insertions and removals that merely shift absolute indexes do not
mark every survivor as moved. A moved entry keeps its old/new paths and can
also show nested modifications.

## Development

```console
uv sync --locked --group dev
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src tests scripts
uv run --locked python -m jsondiffview --help
uv run --locked jdv --version
uv build --no-sources
```

The package supports CPython 3.11 and newer.

## Release publication

`.github/workflows/publish.yml` is the only publication surface. A final
GitHub Release must point to a commit with a successful `Quality` run and
contain exactly the expected wheel and sdist. The workflow downloads those
archives without rebuilding them, validates their Metadata 2.5 contents, and
compares exact filenames and SHA-256 digests with PyPI.
The SHA-pinned PyPA action v1.14.0 bundles Twine 6.1.0 and Packaging 25.0.
Before OIDC starts, the workflow stages Packaging 26.2 from `uv.lock`, verifies
both its pinned wheel and source-tree SHA-256, and installs a fail-closed parser
overlay ahead of the action's bundled dependency. The overlay does not change
either archive.

An exact existing release is a successful no-op. Conflicting or unexpected
files stop publication; a partial exact release stages only its missing files.
Any required upload uses the configured PyPI Trusted Publisher and the `pypi`
GitHub environment, then the workflow polls for the exact files and verifies a
clean index install through both `jdv` and
`python -m jsondiffview`.

Maintainers should require approval by a trusted reviewer and configure
selected deployment refs separately for branch `main` and tags `v*`. Manual
dispatch is accepted only from `main`; a `release: published` run uses its
matching tag ref. The same workflow therefore handles future published releases
and deliberate repeat dispatches for existing final release tags.
