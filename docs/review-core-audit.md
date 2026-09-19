# Review-core audit and design decisions

Baseline: `09e10d1` on `main`, inspected on September 19, 2026. The starting
Windows / CPython 3.13.5 test suite passed all 387 tests. This is an audit of
the checked-out source and reproducible local behavior, not a claim that
every possible input or the entire publication infrastructure is proven safe.

## Decision: strengthen the semantic and presentation boundaries

Keep the existing strict JSON product and its typed pipeline:

```text
bytes -> strict typed values -> semantic DiffNode tree
      -> view projection and string analysis -> styled spans -> output
```

The baseline already has useful separation: strict numeric categories,
duplicate-key rejection, conservative matching evidence, immutable semantic
nodes, plain/ANSI separation, deterministic work budgets, and explicit CLI
stream contracts. Its tests include exhaustive small-sequence references,
golden output hashes, workflow policy, and installation checks. Replacing
this with a general-purpose fuzzy diff, a UI framework, or an unrelated
language would discard valuable guarantees without addressing the observed
failures.

This change instead repairs four concrete failures at those boundaries.
It adds no runtime dependencies, does not change CLI options or exit codes,
and does not change the publication workflow or publish a package.

## Findings and fixes

### 1. High priority: a real array reorder could disappear from the review

Reproduction:

```json
["a", "b", "a"]
```

compared with:

```json
["a", "a", "b"]
```

The baseline pairs the two repeated `a` values monotonically, and pairs the
globally unique `b` by exact value. In new-index order, their old indexes are
`[0, 2, 1]`. An unconstrained longest increasing subsequence (LIS) can keep
`[0, 1]`, leaving one repeated value outside the backbone. The subsequent
classification suppresses moves without identity evidence, so it suppresses
that repeated value's move too. Every entry is then marked stationary even
though the pairs cross. The summary becomes:

```text
~ [
…   3 unchanged items omitted
  ]
```

The process still exits `1`, so this is not a false equality status; it is a
misleading review that fails to explain the actual difference. The same
failure affects identity matches, including moved-and-modified objects.

**Implemented design.** Evidence-less duplicate alignments are mandatory
stationary anchors. Split the trusted pairs into the gaps between successive
anchors, retain only pairs inside both old/new bounds for each gap, and find
the lexically tie-broken LIS within each gap. Trusted pairs not retained are
moved. Duplicate pairs remain evidence-less and never receive move labels.

**Why this is sufficient.** Any monotone stationary backbone containing all
anchors can contain only pairs inside the corresponding gaps. Conversely,
concatenating the anchors and a monotone subsequence from each gap is a valid
backbone. The gaps are independent, so maximizing their retained lengths
minimizes the number of moved trusted pairs. The previous lexical tie rule
is preserved within each gap and on the all-trusted fast path. Total work is
`O(k log k)` and auxiliary storage is `O(k)` for `k` matched pairs.

This is a constrained minimum for the already-selected duplicate alignment,
not a claim of globally optimal edit distance across every possible pairing.
Re-optimizing duplicate pairing jointly with identity matching is a separate
product decision and is not needed to eliminate this correctness failure.

The example now explicitly moves `b` from `$[1]` to `$[2]` in every view.

### 2. Medium priority: bidirectional controls could alter visual interpretation

The renderer escaped C0/C1 controls, line separators, and surrogate code
points, but left Unicode bidirectional formatting controls such as U+202E
unescaped. The diagnostic boundary had the same omission. Raw controls could
therefore survive in keys, string values, move paths/evidence, and errors.
Their visual effect depends on the terminal or downstream bidi-aware viewer.

**Implemented design.** A dependency-free `terminal.py` owns the shared
`requires_visible_escape` predicate. It covers the existing terminal-unsafe
characters and the twelve Unicode `Bidi_Control` characters. Both render and
diagnostic paths call it. The output uses visible `\uXXXX` escapes; the
underlying JSON value and comparison semantics remain unchanged.

Do not blanket-escape category `Cf`: that would damage normal text using
ZWNJ and emoji using ZWJ. Tests explicitly preserve Arabic, Hebrew, Chinese,
combining accents, emoji families, and Persian joiners.

References: Unicode [UAX #9, Explicit Directional Formatting Characters](https://www.unicode.org/reports/tr9/)
and [Unicode 17.0 PropList.txt](https://www.unicode.org/Public/17.0.0/ucd/PropList.txt).

### 3. Medium priority: display cells were not a real output-size bound

A string consisting of `e` followed by thousands of combining acute accents
can form one extended grapheme. A run of zero-width characters can occupy no
display cells at all. The baseline `bounded_excerpt` admitted these strings
despite arbitrarily large code-point counts. Its suffix deque could also
retain an arbitrarily long zero-width run. Long-hunk context had the same
problem even when the changed fragment itself was short.

**Implemented design.** Every excerpt has two independent allowances:
view-specific escaped display cells and 512 code points including the
omission mark. Prefix and suffix collection are bounded by both allowances.
An oversized individual grapheme is omitted whole without copying it into
the display escaper. Long-hunk context receives only the remaining
code-point allowance after the changed fragment. Counts and source ranges
continue to account for omitted text exactly.

Scanning source grapheme boundaries still takes input-dependent work. This
fix bounds retained excerpt text and output, not total file size, parsing
memory, or all preprocessing time. It deliberately does not split a grapheme
or silently normalize Unicode. See [UAX #29](https://www.unicode.org/reports/tr29/)
for the segmentation rules used by the existing `regex` implementation.

### 4. Medium priority: unchanged full-view objects incurred quadratic key work

For each displayed child of an unchanged object, the baseline selected its
key with `list(value)[item]`. Rendering an `n`-field context object in `full`
therefore copied `n` keys `n` times. Large otherwise-unchanged configuration
objects paid this cost simply because a neighboring field changed.

**Implemented design.** Use one iterator for the unchanged object's keys.
The current projections need a prefix: every key for `full`, the first key
for `review`, and no keys for `summary`. Key traversal is now linear in the
displayed prefix, without changing ordering, commas, or output bytes.
This is not a claim that every other rendering operation is now linear.

## Regression strategy

`tests/unit/test_review_invariants.py` checks cross-layer invariants instead
of only snapshots or elapsed-time thresholds:

- All 14,641 ordered pairs of arrays over a three-value alphabet up to length
  four: one-to-one exact pairing, monotone non-moved pairs, and no unsupported
  duplicate moves. A separate exhaustive subsequence oracle checks the
  constrained minimum and lexical tie rule on permutations up to length five.
- Explicit unique-exact, identity, and moved-plus-modified regressions in
  all three views; all twelve bidi controls in plain/ANSI provenance and
  diagnostics; preservation of legitimate Unicode text.
- Combining clusters, zero-width runs, joined emoji, boundary/zero/negative
  budgets, exact omission counts, and an escaper spy that rejects oversized
  copied fragments. Added, removed, unchanged, replacement, multiline, hunk
  context, and identity-evidence routes are covered.
- A counting dictionary checks that full-view key traversal is at most one
  pass. It would fail deterministically on the old quadratic implementation,
  without using machine-dependent timing assertions.

The first regression group was run against the baseline before the fixes:
72 parametrized cases failed and the normal-script preservation case passed.
These represent four root causes, not 72 independent defects. CLI subprocess
tests additionally enforce exit status, stream isolation, visible moves,
bidi-safe usage errors, and bounded output for a 100,001-code-point grapheme.

The existing output corpus and its SHA-256 expectations are not rewritten to
make the fixes pass. The archive allowlists explicitly include the new module,
tests, benchmark, and this document rather than weakening archive validation.

## Measurements

`benchmarks/benchmark_review_invariants.py` is intentionally non-gating and
can run against either revision. It uses the same interpreter/dependencies
for both, prepares parsed values and the semantic tree before measurement,
warms up once, and reports the median of five untraced repeats. For
`full-context`, each repeat includes rendering, serialization, UTF-8 encoding,
and SHA-256. Peak traced allocation is measured in a separate invocation of
the case, never used to select the product's behavior. Measurements are local
observations, not portable latency guarantees.

The comparison uses an untouched detached worktree at `09e10d1` with its
`src` directory selected by `PYTHONPATH`; the working-tree benchmark script
and interpreter are identical. The reported import path was checked before
running each revision. The observed Windows / CPython 3.13.5 results were:

| Unchanged fields in full context | Baseline median | Revised median | Ratio |
| ---: | ---: | ---: | ---: |
| 2,000 | 0.028085 s | 0.012057 s | 2.33x |
| 4,000 | 0.099086 s | 0.023836 s | 4.16x |
| 8,000 | 0.361271 s | 0.052101 s | 6.93x |
| 16,000 | 1.577682 s | 0.103791 s | 15.20x |

Output size and SHA-256 matched across revisions at every size. The
16,000-field output was 420,946 bytes, with digest
`9b083086d0b9f6d4303a6ab86e060a3c227c0c0be624e6f681dc584593ae5917`.
Peak traced allocation for that case was approximately 7.96 MB in both
revisions: the fix removes repeated traversal, not the buffered output model.

For a trusted anchor shifted within 16,000 duplicate values, both revisions
paired all 16,001 items. The baseline incorrectly reported zero moves; the
revised matcher reported one. Median matching time was 0.088465 s versus
0.066326 s, and peak traced allocation was 9,469,612 versus 8,539,372 bytes.

For a 16,001-code-point combining cluster, the baseline excerpt emitted all
16,001 code points and reported no omission. The revised excerpt emitted a
single ellipsis and reported exactly 16,001 omitted code points. This is an
intentional safety correction, not a byte-compatible formatting optimization.

## Remaining redesign opportunities and tradeoffs

**First: document-wide resource policy.** The CLI currently reads both inputs
fully and retains parsed values, a semantic tree, render blocks/spans, and the
serialized review. There is no global input-size or structural-output cap.
String bounds are not a bound on the whole document. Object keys and full
move paths can also be long. A future resource policy should distinguish
input admission, analysis work, retained memory, and output volume, with
explicit diagnostics or exact omission accounting. Truncating keys without
unambiguous disambiguation would make the review less trustworthy.

**Second: transactional output iteration.** Replacing blocks with a line/span
iterator could reduce copies. Directly writing it to stdout is not equivalent
to today's contract: a late analysis error would leak partial review text.
Design iteration together with a temporary-file spool or a complete analysis
phase, and preserve the broken-pipe and UTF-8 behavior. This is a larger
change worth its own compatibility and memory benchmarks, not an incidental
rewrite bundled with correctness fixes.

**Third: narrower internal modules and reusable analysis.** `strings.py` is
large and combines tokenization, matching, projection, and excerpt handling.
Move those responsibilities behind typed interfaces when adding the next
string capability. Reusing view-neutral analysis and subtree summaries could
avoid repeated work across projections; profile repeated fingerprinting and
descendant counting before choosing caches. Caches must have per-comparison
lifetimes and cannot assume arbitrary caller-owned mutable objects never
change. Deeper traversals deserve iterative designs only when supported
depths or real workloads require them; probes at the current 256-container
limit did not reproduce a failure in the exercised shapes and views.

**Fourth: release maintenance.** Exact artifact allowlists are valuable
fail-closed checks but require deliberate updates for each new file. Version
and metadata expectations also appear in multiple files. A separately
reviewed release-schema refactor could reduce duplication while retaining
independent validation; generating every expectation from the same build
code would reduce independence. No publication permission or workflow change
is necessary for these review-core fixes.

Do not replace strict JSON with permissive parsing, infer object identity
from array position, introduce fuzzy moves, escape all Unicode formatting
characters, or use wall-clock time to choose diff output. Those shortcuts
would contradict the project's existing product guarantees.
