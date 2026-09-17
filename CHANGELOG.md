# Unreleased

- **Fixed the DigestAuth per-file symbol-selection bug** the external
  holdout benchmark found (`httpx-digest-auth`: found the right file,
  `_auth.py`, but selected helper methods `_parse_challenge`/
  `_build_auth_header` over the actually-relevant class `DigestAuth`).
  Distinct from PR #3's graph-aware ranking (which fixes a *different*
  failure shape -- a top-level distractor function reached via
  caller-graph evidence): here the outranking symbols are the class's own
  nested methods, so no caller-graph signal applies. Root cause: a
  class-level symbol's extracted body always includes its own methods, but
  a lone method's *signature* (with type-annotated parameters) can rack up
  more name-term matches than the class's own bare `class Foo:` line, and
  a class's `__init__`/dispatch code doesn't carry its methods' body-match
  credit at all -- so a helper can outscore and displace the class it
  belongs to, even though the class's window would show that same
  helper's code anyway.

  Fixed by crediting a matching parent symbol with its single
  best-matching child's score (not the sum of all matching children --
  tried that first, and it let a class with many mediocre-but-nonzero
  matching methods out-accumulate a more precisely-matching standalone
  function, regressing 2 self-benchmark tasks; reverted and used max
  instead of sum). Children are not excluded from the running -- a
  specific method can still legitimately win when nothing else in its
  class is independently relevant (verified against an existing test
  expecting exactly a method name, not its class, in the result).

  Verified: 325 tests passing (was 324), self-benchmark unchanged at the
  PR #3 baseline (92% file recall / 96% symbol recall, only the
  pre-existing `snippet`/`pack-cli` self-referential-corpus drift), and
  the original motivating case now selects `DigestAuth` directly (checked
  against the real httpx source, not the frozen holdout as a tuning loop).

- **Attempted and reverted: a "terse implementation" file-ranking signal**
  to address the external holdout benchmark's `zod-email-regex` finding
  (a file of bare regex constants losing the file-ranking competition to a
  larger, prose-richer file merely discussing the same topic). Two
  designs were tried, each validated against this repository's own
  25-task self-benchmark (per the explicit instruction not to tune
  against the external holdout that found the weakness):
  1. A flat bonus for any query term exactly matching a defined symbol
     name. Regressed 2 self-benchmark tasks: common English words used as
     ordinary parameter/fixture names (`input`, `baseline`, `enabled`)
     got the same bonus as a genuinely rare, specific name, and
     verbosely-named test functions (whose names decompose into many
     individual word-tokens) racked up several such "matches" at once.
  2. A version requiring most of a *whole, short* (<=3-token) symbol
     name to be covered by the query, with an IDF-style discount for
     names that recur across many files. This fixed design 1's failures,
     but introduced 2 new ones: in a codebase whose actual subject matter
     is symbol/outline extraction (this one), short words like `extract`,
     `outline`, and `symbol` aren't rare identifiers -- they're the
     domain's own vocabulary, appearing as short-name components across
     many genuinely-different files, so the IDF discount wasn't steep
     enough to suppress them.

  Reverted rather than ship either regression. Root cause understood
  well enough to say why it's hard, not just that it failed: a
  file-ranking signal based on symbol-name matching alone can't
  distinguish "this name is specific to the one right answer" from "this
  name is common domain vocabulary that recurs everywhere on-topic,"
  without something like caller/import-graph or compiler-resolved
  reference signals -- which is exactly what the original diagnosis
  (CHANGELOG's frozen external holdout entry) proposed as fix #1, not
  fix #2. Left for a future attempt with that additional signal, or with
  a more conservative version of the IDF discount tuned against a fresh,
  never-seen suite rather than iterated against this one.

Note: PR #1 (`feat/index-backed-retrieval`) and PR #2
(`feat/semantic-retrieval-v2`) merged directly to `main` after 1.1.0 was cut,
adding index-backed retrieval performance, stronger JS/TS module semantics,
adaptive retrieval budgeting, provider-aware exact token counting,
multi-repository/frozen-holdout evaluation, a TypeScript-compiler semantic
overlay, and `token-saver host-check` -- without their own version bump or
CHANGELOG entry. Not re-documented here in detail; see the PR descriptions.
This entry covers only the validation work below, done against that merged
state.

- **First frozen external holdout benchmark actually executed.** The
  multi-repository/frozen-holdout infrastructure existed but had never been
  run against real, independently-authored repositories. Built a 6-task
  suite against two well-known public repos at pinned revisions --
  [encode/httpx](https://github.com/encode/httpx) `b5addb6` and
  [colinhacks/zod](https://github.com/colinhacks/zod) `59bbc03` -- with
  ground truth (target files/symbols for a natural-language query) written
  from reading the actual source before ever running the tool, then frozen
  via `--print-ground-truth-hash` and `--require-holdout`.

  Result: **83.3% mean file recall, 16.7% mean symbol recall**, ~98.5%
  estimated token reduction (`benchmarks/holdout-external.json` /
  `.result.json`). This is the honest number, not a cherry-picked one -- and
  it is materially worse on symbol recall than the tool's own repository
  self-benchmark (88-92%), which is exactly the generalization-gap risk
  freezing ground truth in advance exists to catch.

  Two disclosed, unfixed root causes (deliberately not patched against this
  frozen suite -- doing so would defeat holdout evaluation's purpose):
  1. Per-file symbol sub-ranking can pick densely-worded helper methods
     over the semantically-correct but sparser class/function the query
     was actually about (`httpx-digest-auth`: found `_auth.py` but
     selected `_parse_challenge`/`_build_auth_header` over `DigestAuth`).
  2. BM25 file ranking favors prose-rich files over terse-but-correct ones
     (`zod-email-regex`: `regexes.ts`, mostly bare regex constants, lost to
     `schemas.ts`, which merely discusses email validation in fuller
     sentences).
- **Fixed a real bug found while validating `host-check` against an actual
  live host** (not a simulated payload): spawned a genuinely separate
  `claude -p --debug-file` session (2.1.274) against a scratch project with
  Token Saver's hooks installed, and inspected its real debug log. It
  proved genuine acceptance (`Hook PostToolUse (token-saver hook) replaced
  tool output`), but `_host_evidence()`'s exact-string check
  (`"token-saver: filtered output"`) still reported no acceptance, because
  the host's own debug-log redaction independently rewrote "filtered" to
  "[REDACTED]" inside the marker text (confirmed unrelated to Token Saver:
  invoking the hook directly produces the unmangled note). Fixed by
  checking for the recovery command's generated hex id instead of exact
  prose, since nothing but Token Saver produces
  `token-saver output <32-hex-chars>` and generic redaction of the
  surrounding sentence doesn't remove it.
- **Paired coding-agent trials against real bug-fix tasks**, same model/
  prompt/revision, full-context baseline vs. Token Saver's hooks installed,
  independently verified by running the target tests directly (not by
  trusting either agent's self-report). Two trials against
  [encode/httpx](https://github.com/encode/httpx):
  1. A small, targeted fix (NO_PROXY handling in a ~500-line file).
  2. A fix requiring locating a bug in a 2019-line file
     (`httpx/_client.py`), specifically to exercise the read guard.

  **Both trials: both conditions produced the byte-for-byte identical,
  correct fix**, verified by independently running the target tests
  (`tests/test_utils.py`'s `test_get_environment_proxies`, 12/12;
  `tests/client/test_redirects.py`, 31/31) -- Token Saver's hooks do not
  change *what* gets fixed. On cost: trial 1 showed Token Saver 27% more
  expensive; trial 2 showed it 56% cheaper. Inspecting the actual hook
  debug logs (not inferring from cost alone) shows why neither number
  should be trusted as a real effect: **Token Saver's filtering/guard
  mechanism never actually activated in either trial** -- `hook.py`'s
  `main()` only writes output when there is something to filter, and in
  both trials every Read/Bash call stayed under the size thresholds that
  would trigger it. In trial 2 specifically, the agent used `Grep` to
  locate the bug directly rather than reading the whole 2019-line file,
  avoiding the expensive read the guard exists to prevent, in both
  conditions identically. The observed cost differences are inter-run
  variance in how much each independent agent run explored/re-verified
  after the fix, not a demonstrated effect of the tool.

  This is a genuine, disciplined finding, not a null result to paper over:
  across the validation done this session, Token Saver's clearest,
  best-evidenced value is in the pre-compiled context path (`pack`/
  `pack-diff` curating context up front, as in the external holdout
  benchmark and the earlier pikivo review validation) rather than the
  reactive hook-based guard/filter layer, at least for a capable agent
  doing normal file-editing work that already tends to avoid expensive
  full reads on its own. A task genuinely forcing an expensive full read or
  very verbose command output (neither of these two did) remains untested.

# 1.1.0

- Fixed `pack-diff`/`review` silently returning an empty pack (exit 0, no
  output) on large diffs: the ranking query embedded every changed
  file/symbol name uncapped, which could itself exceed `max_tokens` before
  any file content was even considered.
- Fixed a 20-30x performance cliff in impact analysis on large diffs:
  `RepositoryIndex` now caches reverse caller/neighbor/test-file indexes
  once per build instead of rescanning every record on every
  `symbol_callers()`/`neighbors()` call -- verified byte-for-byte identical
  output via differential testing against the old per-call scan.
- Fixed `pack-diff`'s changed-file boost being a no-op for a historical
  `--base` range: it only ever checked live working-tree git status, so a
  diff review never got the boost or closure-seeding it was meant to give.
- Fixed small, genuinely-modified files losing selection to large newly-added
  files at tight budgets: `build_context_pack()` now takes `priority_files`,
  which orders selection ahead of raw BM25 score (with a fair-share cap so
  one large priority file can't consume the whole budget either).
- Widened indexing beyond source code to `.sql`, `.json`, `.yaml`/`.yml`, and
  safe `.env.example`-style templates (real secret files stay blocked;
  `redact_secrets()` remains a backstop). Added dedicated extractors so
  these are real evidence with meaningful symbols -- SQL tables, npm
  scripts, CI job ids, env vars -- reusing the existing symbol/call-graph
  machinery rather than a parallel relationship-graph subsystem.
- Added budgeted evidence allocation: database/config/CI/test evidence that
  is entirely newly-added (so the priority-file mechanism can't reach it)
  gets a small, fair-share-capped budget reservation instead of competing
  purely on BM25 score against large new source files.
- Added a coverage manifest (`build_diff_context`'s `coverage` key, and a
  `# coverage: N/M changed files represented (...)` footer in `pack-diff`'s
  text output) that distinguishes selected, closure-only, policy-excluded,
  and simply-didn't-fit evidence -- so a caller can tell "nothing relevant
  here" from "this pack has a real, disclosed blind spot."
- Fixed `should_skip_dir()` excluding `.github/workflows` (and
  `.gitlab`/`.circleci`) under a blanket "starts with dot" rule -- these are
  committed, human-authored CI config, not VCS/tooling internals like `.git`
  or `.venv`.

Validated end-to-end against a real 129-file diff from a separate production
application (a private third-party codebase, not included in this
repository): reviewed independently by an isolated model instance with no
access to the source repository, at a fixed 4,000-token `pack-diff` budget,
against a full-repository-access baseline and an independently-built 15-item
ground-truth list, before any of this session's fixes existed and again
after each stage:

```
before these fixes:  pack-diff returned an empty pack (the query-size bug)
after the bug fixes:            4/15 ground-truth items, 37,306 tokens
after evidence widening:       11/15 ground-truth items, 38,186 tokens
after fair-share allocation:   12/15 ground-truth items, 37,036 tokens,
                                plus 2 findings a 100,416-token,
                                full-repository-access baseline missed
```

This is a single diff and a single reviewing model, not a statistically
validated benchmark -- no claim here generalizes beyond it. A synthetic
regression fixture reproducing the diff's key structural properties (a
genuinely modified file carrying real risk, mixed with a large batch of
newly-added source, SQL, CI, config, and test files) is checked in at
`tests/test_evidence.py::test_mixed_diff_represents_every_evidence_category_within_budget`
so these results are guarded going forward without depending on the private
repository the original diff came from.

# 1.0.0

- Added bounded, confidence-decayed dependency closure with explicit provenance.
- Replaced regex-only JS/TS definition ranges with Tree-sitter-backed exact
  function, class, method, interface, type, enum, and arrow-function spans.
- Added `pack-diff` and `review` commands for changed-symbol context, dependency
  impact, public-signature changes, removed symbols, and missing-test signals.
- Added a persistent MCP index service with `index_status`, `refresh_index`,
  `build_diff_context`, and `review_diff` alongside the v0.9 tools.
- Added paired agent-outcome evaluation. Savings claims are suppressed when the
  enabled condition does not preserve baseline task success.
- Added Codex, Claude Code, Cursor, and GitHub Actions integration artifacts.
- Added lexical normalization for common code-task inflections and structural
  terminology while retaining deterministic, inspectable scoring.
- Included benchmark: 96% file recall, 100% symbol recall, 92.94% estimated
  context reduction across 25 repository tasks at a 6,000-token cap.

# 0.9.1

- Fixed symbol selection when task vocabulary appears in a definition body but
  not its name or signature, including ambiguous CLI `main` functions.
- Hardened corrupted-cache handling, atomic index durability, and private cache
  permissions without changing the v0.9 on-disk schema.
- Made selector evaluation reproducible by excluding dirty-worktree and learned
  feedback boosts. On the expanded v0.9.1 corpus the included benchmark reports
  92% relevant-file recall and 88% relevant-symbol recall; no 100% claim is made.

# 0.9.0

- Upgraded the content-addressed index to store symbol ranges, signatures,
  parent classes, and per-symbol calls with automatic v1 cache invalidation.
- Added exact symbol-body context packing through `--target-symbol`, structured
  JSON output, selected-symbol metadata, and high-confidence secret redaction.
- Added `token-saver impact` for explainable file/symbol blast-radius analysis
  across imports, callers, and related tests.
- Added bounded local relevance feedback and a ground-truth context evaluator
  measuring file recall, symbol recall, and token reduction.
- Added a 25-task repository benchmark manifest and a dependency-free stdio MCP
  server exposing context, symbol lookup, impact, and feedback tools.
- Hardened repository scanning against sensitive paths, generated/vendor trees,
  escaping symlinks, and oversized context exposure.
- Full suite: 259 tests pass in the release environment.

# 0.8.0

- Added an incremental, content-addressed repository index. It extracts symbols,
  imports, calls, and normalized identifiers and reuses unchanged records.
- Added dependency and symbol-call graph expansion with configurable hop depth
  and distance-decayed ranking boosts.
- Added identifier-based near-duplicate suppression before context allocation.
- Added opt-in session working-set memory. Previous files are boosted only for
  follow-up queries sharing task terms, reducing stale-context carryover.
- Added optional local sentence-transformer reranking through the `embeddings`
  extra. Default behavior remains deterministic and dependency-free.
- Added atomic persistence for indexes and working sets, CLI controls, ranking
  explanations, and regression tests for every new subsystem.
- Full suite: 250 tests pass on Python 3.12 in the release environment.

# 0.7.0

- Added task-aware context packing with `token-saver pack` and the standalone
  `token-saver-pack` entry point.
- Added dependency-free BM25-style source ranking with stronger path and symbol
  weights, Git working-tree/staged-file boosts, and structural-priority fallback.
- Context packs combine compact outlines with exact line-numbered source windows
  around high-signal task matches instead of summarizing editable code.
- Added hard estimated-token caps, file-count/window controls, Git-ignore support,
  ranking explanations, and output-to-file support.
- Added conservative compression of consecutive duplicate lines in successful
  command output while keeping failures and diagnostics untouched.
- Added CI on Python 3.10 and 3.12 and regression coverage for relevance ranking,
  budget enforcement, exact source windows, dispatcher compatibility, JSON
  compaction, and failure preservation.
- Kept all 0.6 lifecycle, audit, recovery, source-read, and benchmark behavior;
  the new top-level dispatcher isolates `pack` from the mature legacy CLI.

Token Saver still does not claim a universal end-to-end savings percentage.
Task success and paired-run measurements remain the standard for savings claims.

# 0.6.0

- Corrected Bash replacement to the documented structured `updatedToolOutput`
  contract. Unsupported/image/interrupted outputs pass through.
- Preserved stderr and failure diagnostics. Shortened outputs are saved privately
  and recoverable by ID/range, without re-executing commands. Saving failures
  leave original output visible. Added `output` and `outputs-prune` commands.
- Scoped read state by project and session, with locked read-modify-write
  transactions, unique temporary files and atomic replacement. Compaction resets
  are installed. Only verified full-read contents are recorded.
- Removed the Stop hook's reliance on undocumented usage fields. Lifecycle advice
  remains based on explicit transcript analysis, not invented live usage.
- Tightened Read ranges: offsets alone and oversized/invalid limits no longer
  bypass the context budget. Relative paths resolve against the hook project.
- Replaced JS/TS snippet boundaries with Tree-sitter, added qualified names and
  ambiguity errors, removed silent 120-line truncation, and improved outlines.
- Excluded first cache observations and compaction epochs from suspected
  recreation. Reported only suspected overlapping prefixes, not all new tokens.
- Scoped repeated-read analysis by session and compaction epoch; stopped
  describing every repeat as waste. Preserved final streaming usage totals.
- Added explicit model/TTL pricing, with incomplete-cost results for unknown
  prices or TTLs. Unknown image sizes no longer use base64 length as token cost.
- Added paired-run benchmark evaluation including failed-attempt costs and
  quality outcomes. Removed historical savings percentages and absolute-ceiling
  claims without reproducible supporting data.
- Made settings updates atomic and refused malformed settings; preserved
  unrelated hooks sharing a matcher. Updated templates and upgrade guidance.

Validation: regression tests cover these fixes and subprocess hook transport.
See VALIDATION.md for executed results. A live Claude Code integration run and
real-task savings benchmark remain unexecuted; BENCHMARKING.md supplies the
protocol. The Windows locking branch is implemented but was not run on Windows.
