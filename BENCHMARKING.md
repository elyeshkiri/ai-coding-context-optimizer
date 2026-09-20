# Verify integration, then benchmark successful work

## Deterministic context-quality benchmark

Before paid paired-agent trials, run the included 25-task ground-truth selector
benchmark. It measures relevant-file recall, relevant-symbol recall, and context
reduction; selection metrics alone do not prove agent success.

```bash
token-saver evaluate benchmarks/context-quality.json --path . --max-tokens 6000
```

Each item also reports `symbol_recall_in_expected_files`, which counts a
symbol only when it was selected from one of the task's expected files. Bare
`symbol_recall` can be satisfied by a same-named symbol in an unrelated file;
prefer the scoped figure (or `qualified_symbols` / `symbol_identities`) when
names are common.

Add project-specific tasks using `query`, `files`, and `symbols`. Keep the
manifest under version control so ranking changes can be compared reproducibly.

## Multi-repository holdout benchmark

### Query-construction protocol

A frozen hash prevents post-hoc edits to the **query text**, expected files, and
expected symbols. It does not make an easy query difficult. New holdouts must
therefore declare which retrieval behavior they are measuring before the first
Token Saver run.

For a **semantic natural-language holdout**, construct each query from the
upstream issue, bug report, user request, or behavior description **before
looking up the answer identity**. The query must not contain:

- the target symbol/member name;
- the target's containing class/type/module name when that name directly
  identifies the answer;
- the target file basename/path;
- the exact qualified symbol identity used as ground truth;
- a distinctive implementation literal copied from the answer solely to make
  retrieval easier.

Example:

```text
acceptable:   "reject malformed email addresses before schema validation"
not semantic: "where is emailRegex in regexes.ts"
```

If the real user task already contains an identifier (for example, a compiler
error names `refreshSession`), keep it: removing genuine task evidence would
make the benchmark artificial. Classify that task/suite as **identifier-bearing**
rather than semantic-natural-language and report it separately.

Do not present identifier-bearing recall as a continuation of a
natural-language difficulty trend. The two answer different questions:

- semantic suites test whether Token Saver can discover the identity from a
  behavior/problem description;
- identifier-bearing suites test exact navigation, overload resolution,
  scoping, and identity recovery once some answer vocabulary is already known.

For future headline semantic holdouts:

1. pre-register the query source/rule and freeze the exact query text;
2. keep target symbol, containing type, file path, and qualified identity out of
   the query unless they genuinely appeared in the upstream task;
3. record any unavoidable identifier-bearing tasks explicitly;
4. run a trivial lexical baseline (for example grep/ctags/exact identifier
   lookup where applicable) on the same frozen tasks;
5. report Token Saver recall alongside that baseline rather than quoting only an
   absolute recall percentage;
6. never rewrite queries after seeing retrieval misses.

The query source/rule belongs in the same committed evidence package as the
manifest. The manifest's query strings themselves are part of the ground-truth
freeze hash, so changing the wording after freeze changes benchmark identity.

The repository-local selector benchmark is useful for regressions, but because
Token Saver is developed against this codebase it is not independent evidence of
generalization. For unseen evaluation, define ground truth before running the
tool and point one manifest at repositories that were excluded from ranking
work/tuning. `benchmarks/holdout.example.json` contains the full schema.

Repository paths are resolved relative to the manifest. Pin exact Git commits so
the corpus cannot move between runs. A publishable holdout also records a freeze
timestamp and a SHA-256 of the task/repository ground-truth definition:

```json
{
  "suite_version": 1,
  "protocol": {
    "ground_truth_frozen": true,
    "development_excluded": true,
    "frozen_at": "2026-09-17T12:00:00Z",
    "ground_truth_sha256": "HASH_FROM_COMMAND_BELOW"
  },
  "repositories": {
    "app-a": {"path": "../app-a", "revision": "ACTUAL_COMMIT_SHA"},
    "app-b": {"path": "../app-b", "revision": "ACTUAL_COMMIT_SHA"}
  },
  "tasks": [
    {
      "id": "auth-refresh",
      "repository": "app-a",
      "query": "session refresh after logout",
      "files": ["src/auth/session.ts"],
      "symbols": ["refreshSession"]
    }
  ]
}
```

After the tasks, expected evidence, and revision pins are final, calculate the
freeze hash without running retrieval:

```bash
token-saver evaluate benchmarks/holdout.json --print-ground-truth-hash
```

Put that value in `protocol.ground_truth_sha256`, commit the manifest, then run:

```bash
token-saver evaluate benchmarks/holdout.json --require-holdout --max-tokens 6000
```

`--require-holdout` rejects a manifest unless both protocol flags are true,
`frozen_at` is present, the SHA-256 still matches the frozen task definition,
and every pinned repository `HEAD` matches its declared revision. Filesystem
paths are excluded from the freeze hash so the same manifest can be replicated
on another machine without changing the benchmark identity. The output includes
aggregate metrics, per-repository summaries, and the verified hash.

A valid hash proves the evaluated definition did not change after it was frozen;
it does not by itself prove the labels were independently authored before tuning.
Preserve manifest history and the task-definition process as audit evidence.

## Automated end-to-end cost-per-success experiment

For evidence that supports a public cost claim, use the executable experiment
harness rather than hand-assembling a few runs. It exports history-isolated snapshots at pinned revisions, randomizes
baseline/enabled order deterministically, runs multiple trials, applies Token
Saver only in the enabled arm, executes the task's verifier outside the agent,
captures the real Claude Code transcript, and checkpoints after every run so an
interrupted paid experiment can resume safely. The exported snapshot is
re-initialized as a one-commit Git repository, so an agent cannot recover the
historical gold fix from later commits or remote branches.

The publication gate deliberately requires **at least 20 distinct tasks and at
least 3 paired trials per task**. A 20-task suite therefore means 120 agent runs
(20 tasks × 3 trials × 2 conditions). Prefer 20–50 historical real-world bug
fixes/refactors across several repositories and task types rather than many near-
duplicates from one project.

Start from `benchmarks/e2e-suite.example.json`. Each task must pin a repository
revision, preserve the exact prompt (plus its SHA-256), and specify one or more
independent verifier commands. Do not use the agent's own "done" statement as
the success label.

A production-ready frozen suite is checked in as
`benchmarks/e2e-swebench-24.frozen.json`. It contains 24 historical SWE-bench
Verified issues across scikit-learn, pytest, Astropy, Pylint, Requests, Xarray,
and Seaborn, with three paired trials per task (**144 agent runs**). The public
repository URL, task revision, prompt, hidden regression patch, official
SWE-bench evaluation image, and canonical test command are frozen into the suite
hash; only the machine-local clone path is excluded.

Prepare its external repositories without checking them into this repository:

```bash
python scripts/prepare_e2e_repos.py benchmarks/e2e-swebench-24.frozen.json
```

For these tasks, the hidden regression patch is not present while the coding
agent runs. After the agent exits, its diff is captured, then a fresh official
SWE-bench Docker image applies the agent patch and hidden test patch and executes
the canonical test command inside the benchmark's prepared environment.

A run is graded per test, not by the exit code of the whole command, because
official images can carry pre-existing errors (for example broken fixtures)
that make it nonzero even for a correct fix. A run is **resolved** when every
`source.fail_to_pass` test passes and no test that passed on the unpatched
reference regressed. The reference is the same image with the hidden tests
applied and no agent patch; it is computed once per task and cached under
`<out>.artifacts/_reference/`. Agent edits to files the hidden test patch
modifies are removed before verification (the full patch stays recorded as
`agent.patch`; the verified one is `agent.graded.patch`), so an agent that also
edits a test file cannot make the hidden tests fail to apply.

Before any paid run, finalize the task definitions and experimental design, then
freeze them:

```bash
token-saver experiment benchmarks/e2e-suite.json \
  --print-task-definition-hash
```

Copy that SHA-256 into `protocol.task_definition_sha256`, set `frozen_at`,
commit the suite, and inspect the randomized schedule without calling a model:

```bash
token-saver experiment benchmarks/e2e-suite.json \
  --out benchmark-runs.json \
  --dry-run
```

Run the experiment:

```bash
token-saver experiment benchmarks/e2e-suite.json \
  --out benchmark-runs.json
```

The baseline arm exports `TOKEN_SAVER_DISABLED=1`, which makes any inherited
Token Saver hook a true no-op. The enabled arm installs project-local hooks.
Both arms receive the same history-isolated source snapshot, exact prompt, model,
turn limit, and verifier. Hidden SWE-bench regression tests are applied only
after the agent process has ended.
To avoid double instrumentation, the runner refuses to start when it detects a
user-level `token-saver hook`; use a clean host configuration for publishable
runs rather than bypassing that guard.

For development/smoke experiments with fewer tasks or an unfrozen suite, pass
`--allow-development`. Those runs are intentionally rejected by the publication
gate.

After the runs finish, price the exact recorded model usage and require the broad
protocol:

```bash
token-saver benchmark benchmark-runs.json \
  --rates rates.json \
  --require-publishable
```

The result includes success rates, failed-run cost, cost per success, per-task
improvements/regressions, and deterministic **95% task-cluster bootstrap
intervals**. Repeated trials are resampled as one task cluster; three trials of
one task are not treated as three independent tasks. The report separately marks
whether the frozen protocol is valid, whether a quality-parity cost claim is
allowed, and whether the 95% interval for cost-per-success reduction is entirely
above zero.

Raw transcripts and verifier outputs can contain source code or secrets. Keep
them private when needed; the checked-in suite definition, revision pins, prompt
hashes, verifier definitions, rates, and aggregate result are sufficient to make
the experimental design auditable.

## Paired agent outcomes

Record independently validated baseline and Token Saver runs using the schema in
`benchmarks/agent-runs.example.json`, then run:

```bash
token-saver agent-evaluate benchmarks/agent-runs.json
```

The evaluator requires exactly one run per condition and task. It reports input
and output tokens, retries, elapsed time, context failures, success rate, and
tokens per success. It suppresses the reduction headline whenever Token Saver's
success rate is below baseline.

For generation-time output-policy experiments, the same manifest can carry
optional **blind response-quality evidence**. Score both conditions on identical
tasks/trials after relabelling them so the grader cannot see which response came
from Token Saver. The built-in rubric weights correctness 40%, completeness
20%, actionability 15%, safety 15%, and concision 10%.

```json
{
  "quality_evaluation": {
    "blinded": true,
    "judge": "independent-response-grader"
  },
  "runs": [
    {
      "task": "fix-session-refresh",
      "condition": "baseline",
      "success": true,
      "input_tokens": 18000,
      "output_tokens": 1200,
      "quality": {
        "correctness": 5,
        "completeness": 5,
        "actionability": 4,
        "safety": 5,
        "concision": 3
      },
      "blocker": false
    }
  ]
}
```

When quality scores are supplied, every paired run must be scored. Token Saver
then requires task-success parity, no material correctness/safety regression,
no increase in blockers, and weighted-quality parity before reporting token
reductions. `output_token_reduction` isolates generated completion-token
savings; `tokens_per_success_reduction` still measures total input + output
efficiency per successful task. Unblinded quality evidence is reported but
cannot authorize a savings claim.

For a publishable output-cost claim, use at least 20 distinct frozen tasks and
three randomized paired trials per task, keep the model/prompt/tool settings
identical, independently verify task success, and report output-token reduction
next to cost per success rather than treating response length alone as quality.

## Live host validation is a separate manual gate

Start with the consolidated configuration/index check, then run the deeper host
transport check before a live host trial:

```bash
token-saver doctor . --require-ready
token-saver host-check . --require-ready
```

This checks project/user hook configuration, probes the host executable version,
runs a synthetic 500-line Bash response through the real PostToolUse hook, and
retrieves an omitted middle line from Token Saver's saved original output. That
is a local transport test; it does **not** prove the host actually feeds
`hookSpecificOutput.updatedToolOutput` back to the model.

For that final gate, capture a real host debug transcript and supply it explicitly:

```bash
token-saver host-check . \
  --live-evidence /path/to/claude-debug.log \
  --require-live
```

`live_verified=true` is reported only when the supplied evidence contains both
the host replacement field and Token Saver's filtered-output recovery marker.
The manual validation protocol remains:

1. Record `claude --version`, model ID, configuration, and Token Saver version.
2. Use a disposable project. Install the package and its project hooks. Check
   that inherited user hooks do not run Token Saver a second time.
3. Start Claude Code with debugging enabled. Ask it to run a harmless command
   that prints 500 distinct progress lines. Do not use a command with side effects.
4. Verify the host accepts `hookSpecificOutput.updatedToolOutput` without a
   validation error. The model-visible result should include the recovery note,
   show the shortened head/tail, and preserve the structured Bash fields.
   Hook stdout alone is not sufficient evidence of host acceptance.
5. Ask it to retrieve a known omitted middle line using the supplied
   `token-saver output` command. Verify the exact line without rerunning the
   original command. Test stderr independently and test a failing Jest-style
   output containing a test name, stack location and multiline assertion diff.
6. Test a >220-line source read. A bounded Read must return actual bytes, and a
   subsequent Edit must succeed. Repeat after `/compact`; prior full-read state
   must not block access to needed source. Test two independent sessions.
7. Save the version, debug evidence and outcomes. If the installed host does not
   support structured replacement, use manual `filter` until upgraded. Do not
   claim automatic savings based on an ignored hook field.

No paid model call or live Claude Code session was executed in the repair
workspace. Automated tests cover the documented contract, subprocess transport,
state isolation, retrieval, and accounting. Live behavior remains a separate gate.

## Paired task protocol

- Choose representative tasks before measuring: bug fixes, refactors, unfamiliar
  repo navigation, noisy passing tests, and failures requiring deep diagnostics.
- Use independent fresh worktrees at the same commit and the same exact prompt,
  model, effort, tools, system instructions, and approval configuration.
- In baseline, disable all Token Saver hooks (including user-scope hooks). In
  enabled runs, use the release's hooks. Do not add orientation maps to only one
  arm unless that is the specific intervention being tested.
- Randomize condition order and run multiple trials per task. Record cache
  policy and cold/warm conditions rather than assuming a five-minute TTL.
- Keep tests/evaluation independent of the agent. Record success, regression
  checks, elapsed time, retries and any manual intervention. A smaller context
  that fails the task is not a win.
- Preserve each run's complete transcripts, including nested subagent
  transcripts where applicable. Do not reuse a transcript across runs.
- Keep raw transcripts local; they may contain code or secrets.

`token-saver benchmark` analyzes recorded runs; it does not execute coding agents
or certify evaluator outcomes. It verifies paired task/trial identity, revision,
model and prompt metadata, requires measured usage and explicit prices, and
rejects incomplete or duplicate runs. Metadata must be recorded honestly by the
runner; the evaluator does not independently attest your checkout or prompt.

## Run manifest

Paths are relative to the manifest file. `success` is determined by independent
validation, not by the agent's own assertion. Use the actual SHA-256 of the prompt.

```json
{
  "runs": [
    {
      "task": "fix-user-lookup",
      "trial": 1,
      "condition": "baseline",
      "revision": "ACTUAL_COMMIT",
      "model": "EXACT_MODEL_ID",
      "prompt_sha256": "ACTUAL_PROMPT_SHA256",
      "success": true,
      "validation": "Independent tests passed; no regressions in required suite",
      "seconds": 120.5,
      "transcripts": ["runs/baseline.jsonl"]
    },
    {
      "task": "fix-user-lookup",
      "trial": 1,
      "condition": "enabled",
      "revision": "ACTUAL_COMMIT",
      "model": "EXACT_MODEL_ID",
      "prompt_sha256": "ACTUAL_PROMPT_SHA256",
      "success": true,
      "validation": "Same independent checks passed",
      "seconds": 118.2,
      "transcripts": ["runs/enabled.jsonl"]
    }
  ]
}
```

The times above demonstrate the schema; they are not measured results.

## Rate file

Create a JSON object mapping each exact model ID to numeric USD-per-million
rates: `input`, `cache_write_5m`, `cache_write_1h`, `cache_read`, `output`.
For example, this object is syntactically valid but deliberately uses a fictitious
model and synthetic prices. **It must not be used to price actual models.**

```json
{
  "synthetic-test-model": {
    "input": 1,
    "cache_write_5m": 1.25,
    "cache_write_1h": 2,
    "cache_read": 0.1,
    "output": 5
  }
}
```

Only add `cache_write_unknown` when the run's actual cache configuration permits
an explicit rate for missing TTL details. Missing prices or unexplained cache
creation prevent a complete cost result.

```bash
token-saver benchmark runs.json --rates rates.json
```

The output includes per-condition success rates, total tokens by usage type,
tool-result counts, repeated reads, elapsed time, total cost, and cost per success.
Costs from failed attempts are included. A reduced success rate suppresses the
headline cost-per-success reduction. Inspect per-task outcomes too: aggregate
success parity does not prove each task retained the same quality.

For the automated experiment path above, `token-saver benchmark` reports a
deterministic task-cluster bootstrap 95% interval. This is still an empirical
benchmark, not a proof that savings generalize to every repository or model.
Before publishing savings, retain the frozen task definitions, repeated trials,
model and host versions, prices, independent checks, and raw results needed to
reproduce the claim.
