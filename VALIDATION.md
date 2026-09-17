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

Not executed:

- Real paired coding tasks with paid API usage and independently checked outcomes.
- Windows execution of the locking branch.
- A production benchmark proving that task-aware packs reduce total task cost
  for a representative workload; the pack tests prove ranking/budget
  invariants, not end-to-end model quality.
- Replication of the real-world validation result on tasks the tool's own
  development never saw (fresh diffs/repositories with ground truth written
  in advance). This is the explicitly planned next validation step, not
  something this release claims.

No real-world token savings percentage is claimed beyond the single, hedged
diff described above. Synthetic and unit tests exercise mechanics and
validation, not general product efficacy. See BENCHMARKING.md for live
integration and paired-task measurement procedures.
