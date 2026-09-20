# Validation for 1.6.0

Token Saver separates **mechanical correctness**, **retrieval generalization**,
and **end-to-end agent economics**. Passing one layer is not presented as proof
of another.

Release CI is anchored to Linux across Python 3.10, 3.12, and 3.13 and requires:

- the complete pytest suite on every supported Python version;
- the deterministic context-quality evaluation;
- the frozen external holdout regression floor;
- PR base-vs-candidate ranking snapshots/diffs;
- Ruff correctness checks;
- 100% docstring coverage via interrogate;
- GitHub Actions workflow linting.

Version 1.5.0 adds the pluggable ranking-stage boundary, opt-in ranking
observability, immutable ranking snapshots/diffs, PR regression evidence,
historical gate calibration, unified host setup/doctor/uninstall, project TOML
configuration, and documentation correctness gates. It does **not** retune the
frozen retrieval baseline merely to improve release metrics.

## Test suite and self-benchmark

- The release gate runs the full suite on Python **3.10, 3.12, and 3.13** rather
  than relying on a single interpreter.
- The included deterministic 25-task selector benchmark at a 6,000-token cap
  currently measures **92% mean relevant-file recall, 92% mean
  relevant-symbol recall, 88% symbol recall in expected files, and 98.71% mean
  estimated context reduction** on the 1.5 release candidate.
- This repository-local benchmark is a diagnostic signal, not the main
  generalization claim and not the frozen release floor. The external holdout
  program below is the stronger retrieval-regression evidence.
- Package metadata for this release is **claude-token-saver 1.5.0**; the import
  remains `token_saver` and the CLI remains `token-saver`.

## Ranking observability and regression validation

Version 1.5.0 adds evidence around *why* ranking changes:

- normal ranking keeps score tracing disabled, preserving the default execution
  path;
- `ranking-explain` verifies trace endpoints against final scores;
- registered post-score stages are traced automatically;
- snapshots retain expected files even when they fall below the ordinary
  display top-N;
- `ranking-diff` refuses incompatible frozen ground truth;
- PR CI captures the baseline with base-commit code against the immutable base
  checkout and the candidate with candidate code;
- both PR snapshots use the base manifest so a PR cannot redefine its own
  comparison ground truth;
- ranking history de-duplicates workflow reruns and selects the newest artifact
  per PR by explicit `(created_at, artifact_id)` comparison;
- historical gate calibration separates frozen ground-truth cohorts and remains
  descriptive until the configured independent-PR evidence floor is reached.

These checks make ranking regressions explainable and reproducible. They do not
turn the current historical sample into a hard merge threshold prematurely.

## Integration lifecycle validation

The 1.5.0 setup lifecycle is tested for:

- auto-detection and explicit Claude Code / Cursor / Codex selection;
- idempotent repeated setup;
- preservation of unrelated MCP servers, hooks, and TOML;
- refusal to overwrite malformed JSON or unmanaged conflicting Codex sections;
- preflight of all selected hosts before the first multi-host mutation;
- safe uninstall of only Token Saver-owned entries;
- preservation of a user-modified generated Claude skill;
- project `.token-saver.toml` discovery and environment-variable precedence;
- repository-relative guard allowlist globs;
- Python 3.10 TOML support through the conditional `tomli` dependency;
- top-level dispatcher, doctor, command-discovery, and shell-completion
  behavior.

`doctor` validates configuration/index health; `host-check` remains the
stronger transport/live-host diagnostic. Configuration health alone is not
claimed as proof that an external host accepted model-visible replacement
output.

## Output optimization validation

The failure-aware output subsystem introduced in 1.4 remains a separate
validation surface alongside source retrieval:

- failure-aware routing is tested so success-oriented processors do not
  automatically compress failed commands;
- complex JavaScript test failures with stack frames and multiline diffs are
  preserved verbatim when the processor cannot safely reduce them;
- the shared critical-line recovery path is exercised independently of any
  one processor;
- output replay contracts test exact diagnostic preservation, token budgets,
  minimum reductions, and nonzero exit status on contract failure;
- graph-aware Delta tests diagnostic identity, unchanged compression,
  changed-diagnostic source/symbol mapping, related repository edges, and
  RESOLVED diagnostics after a clean rerun;
- the historical large-Read and Bash `cat` guard regressions remain in the
  suite.

These tests establish mechanics and preservation behavior for covered fixtures.
They are not a universal lossless guarantee for arbitrary command output.

The checked-in `benchmarks/output-quality.example.json` demonstrates the
portable quality-contract format. See `OUTPUT_OPTIMIZATION.md` for the
processor and Delta contracts.

The broad 24-task SWE-bench cost experiment remains **non-publishable evidence**
for 1.5.0: its latest broad run exposed harness/grader issues, including
budget-limited agent runs being misclassified as infrastructure failures and a
reference grader that produced no parseable test result for one task. Those
failures are benchmark-infrastructure findings, not evidence for or against
Token Saver's real-task cost effect. No 144-run aggregate savings claim is made
for 1.5.0.

## Frozen external holdout program

Token Saver now maintains twelve frozen external holdout suites. Ground truth is
written before evaluation, normalized into a path-independent payload, sealed
with SHA-256, and enforced with `--require-holdout`. Once a suite is evaluated,
it is considered burned for tuning.

### Query difficulty and comparability

The frozen suites do **not** all measure the same query difficulty.

The original 6-task external holdout uses natural-language behavior descriptions
without embedding the target symbol/type identity. By contrast, later suites
including #11 and #12 contain many **identifier-bearing queries** whose wording
names the target class/type and member (for example, asking for a named method
on a named type). Their strong exact-identity numbers therefore validate
navigation, scoping, overload resolution, and identity recovery under
identifier-bearing tasks; they must not be read as evidence that semantic
natural-language retrieval improved monotonically from the early suites to
100%.

This distinction is now part of the benchmark protocol. Future headline
semantic holdouts must follow the no-identifier-leakage query-construction rule
in [BENCHMARKING.md](BENCHMARKING.md#query-construction-protocol), and should
publish a trivial lexical baseline on the same frozen tasks. Identifier-bearing
tasks remain valid when that vocabulary genuinely appears in the upstream user
task, but are reported as a separate query class.

### Holdout #12 — latest fresh external evidence

Holdout #12 follows the pre-declared design from the #11 review: **72
source-grounded tasks across 12 repositories never used in holdouts #1-#11**,
with **6 tasks per repository across 6 languages** (Python, Go, Rust, Java,
TypeScript, and C#).

Repositories: itsdangerous, encode/httpcore, gorilla/websocket, zerolog, uuid,
crossbeam, Apache Commons Text, Apache Commons Codec, Zustand, React Hook Form,
Humanizer, and Newtonsoft.Json.

Frozen ground-truth SHA-256:

`625de623c409f6e77ac695612533f722330db3fd329dfc4b0eb82a0bb6994f54`

Ground truth freeze commit: `6cd5fc8bb5efe16e43e2e5e9625cc12420165135`.
First and only canonical fresh evaluation: GitHub Actions run **35442135225**
from launch commit `20d109d37ea467fe03767cb491b1fe892371d74d`.

| Metric | Fresh first run |
| --- | ---: |
| File recall | **100.00% (72/72)** |
| Bare symbol recall | **100.00% (72/72)** |
| Symbol recall in expected files | **100.00% (72/72)** |
| Qualified-symbol recall | **100.00% (72/72)** |
| Exact symbol-identity recall | **100.00% (72/72)** |
| Mean estimated context reduction | **94.30%** |

All 12 repositories are perfect through exact identity. This is the first fresh
suite in the program to reach 100% at every retrieval/identity level while also
meeting the larger 72-task / 12-repository design.

The context-reduction result must be reported just as literally: **94.30%** is
below the `>=97%` efficiency target proposed after holdout #11. The main reason
is corpus size sensitivity under a fixed 6,000-token budget: the smallest
repository in this suite, itsdangerous, averages only **65.65%** reduction,
while several large repositories exceed 99%. No repository or task is excluded
or reweighted to improve the aggregate.

The exact untouched first-run artifact is checked in as
`benchmarks/holdout-external-12.result.json`. Holdout #12 is now burned for
tuning; later reruns can be regression evidence only.

Two earlier attempts are retained explicitly as rejected audit evidence and are
not counted as canonical holdout #12:

- run **35441174123** reused repositories already present in holdouts #1-#11;
  its manifest/result remain under
  `benchmarks/holdout-external-12-candidate-rejected*.json`;
- run **35441476809** used genuinely unseen repositories but only **25 tasks
  across 5 repositories / 5 languages**, so it did not satisfy the already
  documented 72-task / 12-repository / 6-language design. Its manifest/result
  remain under `benchmarks/holdout-external-12-pilot-rejected*.json`.

Neither rejected attempt was used to tune ranking before the canonical #12
first run.

### Holdout #11 — previous fresh external evidence

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
