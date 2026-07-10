# jsondiffview playground

These fixtures are intentionally small and hand-editable. Run every command
from the repository root in PowerShell. Prepare the locked development
environment and confirm that the current command is v3:

```powershell
uv sync --locked --group dev
$LASTEXITCODE
uv run --locked jdv --version
$LASTEXITCODE
```

The sync and version commands should each print status `0`; the version line is
`jdv 3.0.0`.

`jdv` follows the traditional diff exit-code convention:

- `0` means the documents are semantically equal.
- `1` means differences were found and rendered successfully.
- `2` means invalid usage, invalid input, or another operational error.

PowerShell keeps the native process status in `$LASTEXITCODE`. Status `1` in a
difference example is expected, not a tool failure. Review text goes to stdout;
equality notices and errors go to stderr.

## Review additions, removals, changes, and a move

```powershell
uv run --locked jdv --color never .\playground\review-before.json .\playground\review-after.json
$LASTEXITCODE
```

Expected status: `1`. This is the broad review sample: it shows additions,
removals, nested scalar and string changes, an integer-to-decimal type change,
and a relative-order move with identity provenance. `--color never` makes every
semantic marker visible as plain text.

## Compare all three views

Only `setting_05` changes in this pair, so omitted-context behavior is easy to
compare:

```powershell
uv run --locked jdv --color never --view summary .\playground\context-before.json .\playground\context-after.json
$LASTEXITCODE
uv run --locked jdv --color never --view review .\playground\context-before.json .\playground\context-after.json
$LASTEXITCODE
uv run --locked jdv --color never --view full .\playground\context-before.json .\playground\context-after.json
$LASTEXITCODE
```

Expected status: `1` after each command. `summary` collapses both unchanged
runs, `review` retains the unchanged settings adjacent to the change, and
`full` shows every setting. All three views report the same semantic change.

## Exercise v3 matching safeguards

Use `full` so every safely aligned duplicate remains visible:

```powershell
uv run --locked jdv --color never --view full .\playground\matching-before.json .\playground\matching-after.json
$LASTEXITCODE
```

Expected status: `1`. The three fields demonstrate separate v3 rules:

- `higher_priority_conflict` has the same `name` but conflicting scalar `id`
  values. The lower-priority `name` cannot override that conflict, so the
  objects remain an explicit removal and addition.
- `null_identity_fallback` treats `id: null` as unavailable, falls through to
  the scalar `name`, and retains both a move and the nested `replicas` change.
  The move note says it matched by `"name": "worker"`.
- `duplicate_exact_sequence` aligns repeated exact strings monotonically for a
  stable review. The unmatched edge remains explicit, and the duplicate
  alignment emits no fabricated `>` move provenance.

## Match array objects with a custom identity key

First run with the default identity keys:

```powershell
uv run --locked jdv --color never .\playground\custom-key-before.json .\playground\custom-key-after.json
$LASTEXITCODE
```

Expected status: `1`. Because `uuid` is not a default key, the changed
`node-c` object cannot be paired and appears as a removal plus an addition.

Now replace the defaults with `uuid`:

```powershell
uv run --locked jdv --color never --match-key uuid .\playground\custom-key-before.json .\playground\custom-key-after.json
$LASTEXITCODE
```

Expected status: `1`. The matcher now retains `node-c` as one item, so the
review shows its move and nested `replicas` modification.

## Exercise v3 string rendering

```powershell
uv run --locked jdv --color never .\playground\strings-before.json .\playground\strings-after.json
$LASTEXITCODE
```

Expected status: `1`. Each field targets a distinct string strategy:

- `short` uses ordinary inline word-level spans.
- `graphemes` keeps each skin-tone/ZWJ emoji and each CJK character intact
  while marking the changed emoji and city.
- `dense` is a separator-heavy, whitespace-free URL below 512 code points. It
  demonstrates adaptive blob classification and bounded, display-width-aware
  hunks rather than a single hard length cutoff.
- `multiline` pairs similar logical lines, shows intraline spans and escaped
  `\n` terminators, and retains the added line.
- `long` preserves the existing long payload example with exact code-point
  lengths, offsets, and bounded excerpts.

## Force ANSI color

```powershell
uv run --locked jdv --color always .\playground\review-before.json .\playground\review-after.json
$LASTEXITCODE
```

Expected status: `1`. This forces ANSI yellow, red, green, and cyan roles even
when stdout is redirected. Color wraps the same literal markers as the plain
review; it does not carry unique semantics.

## Read the old document from stdin

```powershell
Get-Content -Raw -Encoding utf8 .\playground\review-before.json |
  uv run --locked jdv --color never - .\playground\review-after.json
$LASTEXITCODE
```

Expected status: `1`. `-` occupies the old-document position, so the output is
the same directional comparison as the file-to-file review.

## Use the module entry point

```powershell
uv run --locked python -m jsondiffview --color never .\playground\review-before.json .\playground\review-after.json
$LASTEXITCODE
```

Expected status: `1`. This demonstrates that `python -m jsondiffview` and
`jdv` share the same implementation, output, and status contract.

## Check equality

```powershell
uv run --locked jdv --color never .\playground\equal.json .\playground\equal.json
$LASTEXITCODE
uv run --locked jdv --quiet .\playground\equal.json .\playground\equal.json
$LASTEXITCODE
```

Expected status: `0` after each command. The first command writes no stdout and
prints `No semantic differences.` to stderr. The quiet form suppresses only
that equality notice, leaving both streams empty.

## Check strict-input errors

The checked-in error fixture repeats an object key:

```powershell
uv run --locked jdv --color never .\playground\invalid-duplicate-key.json .\playground\equal.json
$LASTEXITCODE
```

Expected status: `2`, empty stdout, and one `jdv: error:` diagnostic on stderr
identifying the duplicate key.

A non-finite numeric result is also rejected through stdin:

```powershell
'1e999' | uv run --locked jdv --color never - .\playground\equal.json
$LASTEXITCODE
```

Expected status: `2`, empty stdout, and one `jdv: error:` diagnostic explaining
that the number exceeds the supported finite range. Neither error prints a
traceback or partial review.

Edit copies of any fixture to explore additional cases. The first input is
always the old document and the second input is always the new document.
