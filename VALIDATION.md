# Validation for 1.3.1

Release validation is anchored to GitHub CI on Linux across Python 3.10,
3.12, and 3.13. Version 1.3.1 is a packaging/release-integrity patch over
1.3.0 plus the behavior-preserving ranking refactor and CI quality gates
merged after that tag; the frozen retrieval evidence below is unchanged.

Observed CI dependency versions include:

- pytest 9.1.1
- tree-sitter 0.25.2
- tree-sitter-javascript 0.25.0
- tree-sitter-typescript 0.23.2
- tree-sitter-c-sharp 0.23.5

## Test suite and self-benchmark

- Full test suite: **474 passed** on the Python 3.10/3.12/3.13 PR CI matrix after adding quality-gate coverage.
- The included deterministic 25-task selector benchmark at a 6,000-token cap
  currently measures **100% mean relevant-file recall, 100% mean
  relevant-symbol recall, 100% symbol recall in expected files, and 97.90%
  mean estimated context reduction**.
- The self-benchmark is now saturated and should be treated as a regression
  floor, not as the main evidence of generalization. The frozen external
  holdouts below are deliberately stronger evidence.
- Package metadata for this release is **claude-token-saver 1.3.1**; the import remains `token_saver` and the CLI remains `token-saver`.

## Frozen external holdout program

Token Saver now maintains eleven frozen external holdout suites. Ground truth is
written before evaluation, normalized into a path-independent payload, sealed
with SHA-256, and enforced with `--require-holdout`. Once a suite is evaluated,
it is considered burned for tuning.

### Holdout #11 — latest fresh external evidence

Holdout #11 contains **60 source-grounded tasks across 10 repositories never
used in holdouts #1-#10**, spanning C#, Java, TypeScript, Rust, Go, and Python.

Frozen ground-truth SHA-256:

`011dffedad4fe5ea99400cc58655850dcf43f38b3664b9219b4f5cf92a7f94ec`

First and only fresh evaluation: GitHub Actions run **35395304893**.

| Metric | Fresh first run |
| --- | ---: |
| File recall | **96.67%** |
| Bare symbol recall | **96.67%** |
| Symbol recall in expected files | **93.33%** |
| Qualified-symbol recall | **91.67%** |
| Exact symbol-identity recall | **88.33%** |
| Mean estimated context reduction | **99.71%** |

Six repositories were perfect through exact identity: .NET Runtime, EF Core,
Spring Framework, tracing, gRPC-Go, and SQLAlchemy. The fresh C# results are
especially important because .NET Runtime and EF Core independently validate
the C# 14 extension-block recovery introduced after holdout #10.

The seven non-perfect tasks were concentrated in four general classes: dense
Java overload identity, TypeScript interface/generic-member identity, a
same-name TypeScript function in the wrong file, and a Go receiver/member query
overwhelmed by common call-site noise.

After those classes were fixed generically, frozen #11 was rerun **once** as a
burned development diagnostic (run **35399929752**). That diagnostic reached
**100% file, bare, scoped, qualified, and exact identity recall across all
60 tasks**, with **99.71% mean context reduction** and zero misses. This is
regression confirmation only; it does **not** replace the fresh 88.33% exact
first-run result above.

The exact untouched first-run artifact is checked in as
`benchmarks/holdout-external-11.result.json`.

## Historical first external holdout (1.2-era)

A 6-task suite against independently-authored public repositories at
pinned revisions -- [encode/httpx](https://github.com/encode/httpx)
`b5addb6` and [colinhacks/zod](https://github.com/colinhacks/zod)
`59bbc03` -- with ground truth (target files/symbols for a
natural-language query) written from reading the actual source before
ever running the tool, frozen via `--print-ground-truth-hash`, and
evaluated with `--require-holdout` (`benchmarks/holdout-external.json` /
`.result.json`).

- **First run (1.1.0 validation cycle): 83.3% mean file recall, 16.7%
  mean symbol recall**, ~98.5% mean estimated token reduction -- the
  honest, frozen number, not a cherry-picked one, and materially worse on
  symbol recall than this repository's own self-benchmark, exactly the
  generalization gap freezing ground truth in advance exists to catch.
  Two disclosed root causes: per-file symbol sub-ranking could prefer a
  densely-worded helper method over the semantically-correct class/
  function the query was about, and file-level BM25 ranking could prefer
  a prose-rich file discussing a topic over a terser file that is
  actually the correct answer.
- **Current result: 83.3% mean file recall, 83.3% mean symbol
  recall**, ~98.5% mean token reduction unchanged. `httpx-digest-auth`,
  `httpx-redirects`, `httpx-multipart`, `zod-error-tree`, and
  `zod-flatten-error` are all now at 1.0/1.0 symbol recall. Each fix
  along the way was designed and validated against this repository's own
  25-task self-benchmark first (never iterated against this frozen
  suite), then measured against it once, after the fact, purely as an
  observation of generalization -- consistent with this project's
  standing rule against tuning against the same suite that found a gap.
  That process surfaced two of its own regressions along the way (a
  parent-credit symbol-window fix that briefly broke `httpx-redirects`,
  and a file-ranking dampening attempt that broke it again while fixing
  `zod-email-regex`); both are disclosed in full, with root cause and
  resolution, in CHANGELOG.md.
- **Correction (bisected after 1.3.0):** the per-task attribution above is
  stale, and `benchmarks/holdout-external.result.json` (6/6 at 1.0/1.0) no
  longer reproduces. That artifact was accurate when written -- the suite
  scored 6/6 at `3462828` -- but regressed twice afterwards, undetected,
  because this suite ran in no CI job:
  - `6f47fd2` "stop containers from double-counting descendant relevance"
    broke `zod-error-tree` symbol recall (1.000 -> 0.667; partially
    recovered to 0.833 at `3361bdb`, and `zod-error-tree` has failed ever
    since);
  - `7acb0d8` "align structural leaf gates with query tokenization" broke
    `zod-email-regex` file recall (1.000 -> 0.833).

  Current main therefore measures 83.3% file recall, 83.3% bare-symbol
  recall, and 66.7% symbol recall in expected files. The scoped metric is
  lower because `zod-email-regex` can still find a same-named symbol outside
  `regexes.ts`, while `zod-error-tree` misses its expected symbol. The
  aggregate 83.3% bare figures matching the 1.2.0 result are therefore a
  coincidence of offsetting changes.

  `.github/workflows/ci.yml` now runs this suite on every pull request and
  again on every push to `main` via `scripts/check_holdout.py`, enforcing
  file, bare-symbol, and expected-file-scoped symbol floors recorded in
  `benchmarks/holdout-external.floor.json`. The floor update command is
  monotonic and refuses to lower any existing threshold. Neither regression has been
  "fixed" by adjusting ranking: this is a burned holdout, and tuning
  against it to move the number is exactly what the protocol forbids. The
  floor is set at the current value and should be ratcheted upward only
  when a root-cause fix, validated on the self-benchmark first, raises it.
- **Remaining known gap: `zod-email-regex` (0.0 file recall).** Root
  cause identified precisely: `rank_files()`'s outline-term bonus is
  presence-only, not normalized by outline size, so a large file with a
  sprawling outline (`schemas.ts`) picks up more distinct query-term hits
  than a small, precisely on-topic file (`regexes.ts`) purely from having
  more surface area -- even though raw BM25 alone already correctly
  favors the smaller file. A fix (dampening the bonus by outline size)
  was tried and reverted after it broke a different, previously-fixed
  task (`httpx-redirects`, itself a large file that is genuinely the
  correct answer) -- a flat per-file size penalty can't distinguish
  "large and diffusely matching" from "large and genuinely on-topic."
  PR #4 (`fix/authoritative-file-ranking`, see below) targeted this same
  gap via a different mechanism and does not resolve it either:
  `regexes.ts` has no direct incoming `semantic-ref` edge from a file
  that independently outranks `schemas.ts`. Deliberately left unfixed
  pending a *new*, separately-frozen holdout suite to validate a future
  fix against -- re-running a change against the same frozen tasks that
  found the weakness would not demonstrate generalization.

## Merged without their own release (PR #1-#4)

PR #1 (`feat/index-backed-retrieval`), PR #2 (`feat/semantic-retrieval-v2`),
PR #3 (`fix/graph-aware-symbol-ranking`), and PR #4
(`fix/authoritative-file-ranking`) all merged directly to `main` between
1.1.0 and this release, without their own version bump or CHANGELOG entry;
summarized here rather than individually re-documented (see each PR's
description and CHANGELOG.md's entries for full detail):

- PR #1/#2: index-backed retrieval performance, stronger JS/TS module
  semantics, adaptive retrieval budgeting, provider-aware exact token
  counting, multi-repository/frozen-holdout evaluation infrastructure, a
  TypeScript-compiler semantic overlay, and `token-saver host-check`.
- PR #3: caller-graph-aware symbol ranking and exact incoming
  semantic-reference evidence in `_symbol_windows()`.
- PR #4: a strong, deliberately non-transitive one-hop ranking weight for
  exact `semantic-ref` edges. Merged with its own CI check failing on
  every push (only a separate, narrower frozen-holdout workflow was
  green); the underlying gap (`dependency_closure`'s seed set is too
  small to discover a relevant-but-low-raw-score provider) was diagnosed
  and fixed as part of this release -- see CHANGELOG.md.

## Other validation carried over from 1.1.0

- Differential testing verified the `RepositoryIndex` reverse-index
  caching (`symbol_callers`/`neighbors`/test-file signatures) produces
  byte-for-byte identical output to the pre-caching per-call scan it
  replaced, checked across 625 real files and 10 symbols in a separate
  application's repository (not included here).
- Real-world validation: a real 129-file diff from a separate production
  application (private, not included in this repository) was reviewed by
  an isolated model instance with no access to that repository, at a fixed
  4,000-token `pack-diff` budget, against a full-repository-access baseline
  (100,416 tokens, 42 tool calls) and an independently-built 15-item
  ground-truth list. Result: roughly 12-13/15 ground-truth items
  recovered, including two findings the baseline missed, at effectively
  flat token cost (37,306 -> 37,036 tokens). Single diff, not a
  statistically validated benchmark; see
  `tests/test_evidence.py::test_mixed_diff_represents_every_evidence_category_within_budget`
  for the checked-in regression fixture that guards this result without
  depending on the private repository.
- Live host validation executed against a real, separate Claude Code host
  process (version 2.1.274), not a simulated payload: a headless
  `claude -p` session with Token Saver's hooks installed produced a
  captured debug log showing the host receiving
  `hookSpecificOutput.updatedToolOutput` and logging `Hook PostToolUse
  (token-saver hook) replaced tool output`. `token-saver host-check
  --live-evidence <captured-log> --require-live` exits 0 with
  `live_verified: true`.
- Paired coding-agent trials against real bug-fix tasks in
  [encode/httpx](https://github.com/encode/httpx), full-context baseline
  vs. Token Saver's hooks, outcomes independently verified by running the
  target tests directly. Both conditions produced the byte-for-byte
  identical correct fix in both trials. No reliable cost effect was
  demonstrated either way: Token Saver's filtering/guard mechanism never
  actually activated in either trial (both file reads and command output
  stayed under its size thresholds). See CHANGELOG.md.
- Regression coverage exercises bounded dependency closure,
  Tree-sitter-backed JS/TS/JSX/TSX symbol ranges, patch-aware context
  generation, public-signature/removed-symbol/missing-test detection, the
  persistent MCP index service, paired agent-outcome evaluation,
  incremental index reuse, near-duplicate suppression, task-session
  continuity, hard context-pack token caps, exact line-numbered source
  windows, sensitive-path rejection, symlink containment, secret
  redaction, structured Bash output, subprocess hook transport, and
  model/TTL pricing.

## Not executed

- Windows execution of the locking branch.
- A production benchmark proving that task-aware packs reduce total task
  cost for a representative workload; the pack tests prove ranking/budget
  invariants, not end-to-end model quality.
- A fresh, never-seen frozen holdout suite to validate a `zod-email-regex`
  fix against (the original suite is now burned for that specific gap,
  having been used to diagnose and disprove two fix attempts).

No real-world token savings percentage is claimed beyond the private-diff
review and the external holdout benchmark described above, both explicitly
hedged (single diff; six tasks across two repositories), and the paired
coding-agent trials explicitly demonstrated no reliable cost effect either
way rather than a savings claim. Synthetic and unit tests exercise
mechanics and validation, not general product efficacy. See BENCHMARKING.md
for live integration and paired-task measurement procedures.
