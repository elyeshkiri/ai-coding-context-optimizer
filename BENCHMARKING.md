# Verify integration, then benchmark successful work

## Live host validation (not yet executed for this release)

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

No confidence interval or statistical significance is claimed. Before publishing
savings, retain task definitions, repeated trials, model versions, host versions,
prices, independent checks, and raw results needed to reproduce the claim.
