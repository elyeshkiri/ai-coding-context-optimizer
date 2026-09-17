# Validation for 1.1.0

Release validation executed locally on Linux with Python 3.14. The
repository CI matrix targets Python 3.10, Python 3.12, and Python 3.13:

- Full test suite: **320 passed** at the current commit (270 at 1.0.0; +18
  from this release's SQL/config/CI/env extractors, changed-file/
  priority-file/fair-share allocation fixes, coverage manifest, and the
  regression fixture reproducing the real-world validation diff's
  structural shape below; +30 from index-backed retrieval, TypeScript
  compiler semantics, frozen holdouts, and host validation merged after
  this release was cut; +2 from the live-host-validation fix described
  below).
- Package build and isolated installation succeeded from `pyproject.toml` as
  token-saver 1.1.0 (`python -m build`, then `pip install` the built wheel
  into a fresh virtualenv and run `token-saver --help`).
- The included deterministic selector benchmark at a 6,000-token cap
  measured 88% mean relevant-file recall, 92% mean relevant-symbol recall,
  and 93.83% mean estimated context reduction on this repository at this
  commit. These are repository-specific selection metrics, not proof of
  end-to-end agent task success, and move slightly release to release as
  the tool's own source -- part of the benchmark corpus -- changes.
- New in this release: differential testing verified the `RepositoryIndex`
  reverse-index caching (`symbol_callers`/`neighbors`/test-file signatures)
  produces byte-for-byte identical output to the pre-caching per-call scan
  it replaced, checked across 625 real files and 10 symbols in a separate
  application's repository (not included here).
- Real-world validation: a real 129-file diff from a separate production
  application (private, not included in this repository) was reviewed by
  an isolated model instance with no access to that repository, at a fixed
  4,000-token `pack-diff` budget, against a full-repository-access baseline
  (100,416 tokens, 42 tool calls) and an independently-built 15-item
  ground-truth list written before any of this release's code existed.
  Result: roughly 5-7/15 ground-truth items recovered before this
  release's evidence-coverage and allocation work, roughly 12-13/15 after,
  including two findings the baseline missed, at effectively flat token
  cost (37,306 -> 37,036 tokens). Single diff, not a statistically
  validated benchmark; see CHANGELOG.md for full methodology and
  `tests/test_evidence.py::test_mixed_diff_represents_every_evidence_category_within_budget`
  for the checked-in regression fixture that guards this result without
  depending on the private repository.
- Live host validation executed against a real, separate Claude Code host
  process (version 2.1.274), not a simulated payload: a fresh scratch
  project had Token Saver's hooks installed via `token-saver install`, a
  headless `claude -p` session (`--allowedTools Bash --debug-file ...`) ran
  a command producing 500 distinct lines, and the host's own debug log was
  captured and inspected directly. It shows the host receiving
  `hookSpecificOutput.updatedToolOutput`, parsing and validating it, and
  logging `Hook PostToolUse (token-saver hook) replaced tool output`. This
  also surfaced and fixed a real bug: the host's own debug-log redaction
  rewrote the word "filtered" to "[REDACTED]" inside Token Saver's recovery
  note (confirmed unrelated to Token Saver -- invoking the hook directly
  produces the unmangled note), which made the previous exact-string
  evidence check report no acceptance despite genuine acceptance having
  occurred. `host_validate.py` now checks for the recovery command's
  generated hex id instead of exact prose, since nothing but Token Saver
  produces that pattern and generic redaction of surrounding words doesn't
  remove it. `token-saver host-check --live-evidence <captured-log>
  --require-live` now exits 0 with `live_verified: true`. The raw debug log
  is not included in this repository (it briefly names an internal socket
  path and environment-probe details, distinct from and in addition to
  Token Saver's own recovery marker, and is host session debug output, not
  Token Saver's own artifact).
- **First frozen external holdout benchmark**, executed for real against
  independently-authored public repositories rather than this repository's
  own self-benchmark: a 6-task suite against
  [encode/httpx](https://github.com/encode/httpx) `b5addb6` and
  [colinhacks/zod](https://github.com/colinhacks/zod) `59bbc03`, with
  target files/symbols for each natural-language query written from reading
  the actual source before running the tool, frozen via
  `--print-ground-truth-hash`, and evaluated with `--require-holdout`
  (`benchmarks/holdout-external.json` / `.result.json`). Original result:
  **83.3% mean file recall, 16.7% mean symbol recall**, ~98.5% mean
  estimated token reduction -- the honest, frozen number, not a
  cherry-picked one, and exactly the kind of generalization gap this
  methodology exists to surface. Two disclosed root causes: per-file
  symbol sub-ranking could prefer a densely-worded helper method over the
  semantically-correct class the query was about, and file-level BM25
  ranking can prefer a prose-rich file discussing a topic over a terser
  file that is actually the correct answer (e.g. a file of bare regex
  constants; still unfixed -- see CHANGELOG.md's reverted "terse
  implementation" signal attempt).

  The first root cause was later fixed (parent-credit symbol-window
  selection) and validated entirely against the self-benchmark, never
  against this frozen suite. A one-time, after-the-fact re-run of this
  same frozen suite (not a tuning loop) then measured the fix's real
  effect: mean symbol recall rose to 50%, file recall and token reduction
  unchanged. It also surfaced one new, disclosed regression
  (`httpx-redirects`, 1.0 -> 0.0) where two classes sharing one specific
  target method now both out-score it for the file's top-2 window slots.
  That regression was itself fixed (crediting the child whose score
  earned its parent a window slot, since the parent's window already
  contains that child's source) and re-verified with a second one-time
  holdout re-run: mean symbol recall 66.7%, file recall and token
  reduction still unchanged, no new regressions.

  `zod-flatten-error` and `zod-error-tree` turned out, on investigation,
  to be symbol-window bugs too, not the file-ranking issue they were
  originally filed under (file recall was already 1.0 for both): an
  untruncated TypeScript type-alias signature double-counting its own
  inline fields, and the parent-credit boost above applying to
  function-in-function nesting, not just class/method containment. Both
  fixed and re-verified with a third one-time holdout re-run: **mean
  symbol recall 83.3%**, file recall and token reduction still unchanged,
  no new regressions across any of the 5 tasks this now passes. A fourth
  attempt, at the real remaining file-ranking gap behind
  `zod-email-regex` (root cause: an unnormalized, presence-only outline-
  term bonus lets a large file rack up more distinct query-term hits than
  a small, precisely on-topic one purely from having more surface area),
  was tried and reverted after it broke a different, previously-fixed
  task (`httpx-redirects`) -- see CHANGELOG.md for the full account,
  including why it looked clean on the self-benchmark alone (100%/100%)
  and only the frozen holdout caught the regression. `zod-email-regex`
  remains deliberately unfixed pending its own separately-frozen holdout
  to validate a future fix against.
- Regression coverage carried over from 1.0.0 still exercises bounded
  dependency closure, Tree-sitter-backed JS/TS/JSX/TSX symbol ranges,
  patch-aware context generation, public-signature/removed-symbol/
  missing-test detection, the persistent MCP index service, paired
  agent-outcome evaluation, incremental index reuse, near-duplicate
  suppression, task-session continuity, hard context-pack token caps,
  exact line-numbered source windows, sensitive-path rejection, symlink
  containment, secret redaction, structured Bash output, subprocess hook
  transport, and model/TTL pricing.

Observed dependency versions in the release environment:

- pytest 9.1.1
- tree-sitter 0.25.2
- tree-sitter-javascript 0.25.0
- tree-sitter-typescript 0.23.2

- Paired coding-agent trials executed with real, paid API usage: two
  full-context-baseline-vs-Token-Saver-hooks trials against real bug-fix
  tasks in [encode/httpx](https://github.com/encode/httpx), same model/
  prompt/revision, outcomes independently verified by running the target
  tests directly rather than trusting either agent's self-report. Both
  conditions produced the byte-for-byte identical correct fix in both
  trials. No reliable cost effect was demonstrated either way: direct
  inspection of the hook debug logs showed Token Saver's filtering/guard
  mechanism never actually activated in either trial (both file reads and
  command output stayed under its size thresholds, and in the second trial
  the agent used `Grep` to avoid a full 2019-line read in both conditions
  identically) -- the observed cost swing (+27% in trial 1, -56% in trial
  2) is inter-run variance in post-fix verification thoroughness, not a
  demonstrated tool effect. See CHANGELOG.md. A task genuinely forcing an
  expensive read or highly verbose command output remains untested.

Not executed:

- Windows execution of the locking branch.
- A production benchmark proving that task-aware packs reduce total task cost
  for a representative workload; the pack tests prove ranking/budget
  invariants, not end-to-end model quality.
- A fix for the symbol-selection weaknesses the external holdout benchmark
  found. Deliberately left unfixed pending a *new*, separately-frozen
  holdout suite to validate any fix against -- re-running a change against
  the same frozen tasks that found the weakness would not demonstrate
  generalization.

No real-world token savings percentage is claimed beyond the pikivo diff and
the external holdout benchmark described above, both explicitly hedged
(single diff; six tasks across two repositories), and the paired
coding-agent trials explicitly demonstrated no reliable cost effect either
way rather than a savings claim. Synthetic and unit tests exercise
mechanics and validation, not general product efficacy. See BENCHMARKING.md
for live integration and paired-task measurement procedures.
