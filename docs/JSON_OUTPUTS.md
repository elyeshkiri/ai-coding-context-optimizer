# Machine-readable CLI contracts

This reference documents the stable **top-level** JSON shape emitted by Token
Saver commands. It is intentionally narrower than a formal JSON Schema: nested
records may gain additive fields in compatible releases, while the documented
top-level keys and meanings are treated as public CLI contracts.

Commands that support both human and JSON output require `--json` unless noted
otherwise.

## Exit behavior shared by JSON commands

- exit `0`: the JSON document was produced successfully;
- exit `1`: a requested quality/readiness condition failed for commands that
  define such a gate;
- exit `2`: invalid input/configuration, malformed manifests, unsafe
  mutations, or other refused operations.

Argparse usage errors also exit `2`.

## `setup --json`

```json
{
  "root": "absolute project path",
  "config": "path to .token-saver.toml",
  "requested_hosts": ["claude", "cursor"],
  "configured_hosts": ["claude", "cursor"],
  "detected": [
    {
      "name": "claude",
      "detected": true,
      "configured": true,
      "executable": "/path/to/claude",
      "config_paths": ["..."],
      "details": ["hooks", "mcp"]
    }
  ]
}
```

## `doctor --json`

```json
{
  "ready": true,
  "version": "1.5.0",
  "token_saver_executable": "/path/to/token-saver",
  "root": "absolute project path",
  "config_path": "/project/.token-saver.toml",
  "config_error": null,
  "runtime": {},
  "detected_hosts": ["claude"],
  "configured_hosts": ["claude"],
  "hosts": [],
  "index": {},
  "index_error": null,
  "claude_transcripts": 3
}
```

With `--require-ready`, a document is still printed but exit `1` indicates
`ready == false`.

## `uninstall --json`

```json
{
  "root": "absolute project path",
  "removed_hosts": ["claude", "cursor", "codex"],
  "config_removed": false
}
```

## `host-check` (always JSON)

```json
{
  "host": {},
  "project_settings": {},
  "user_settings": {},
  "configured": true,
  "hook_transport": {},
  "live_host_evidence": {},
  "ready": true,
  "live_verified": false
}
```

`--require-ready` and `--require-live` turn false readiness/evidence into
exit `1`.

## `pack --json`

```json
{
  "text": "bounded context pack",
  "estimated_tokens": 1234,
  "scanned_files": 200,
  "selected_files": ["src/a.py"],
  "selected_symbols": ["..."],
  "redactions": [],
  "closure_files": [],
  "retrieval_plan": {},
  "typescript_semantic_edges": 0
}
```

## `browse --json`

```json
{
  "query": "task text",
  "files": [
    {
      "rank": 1,
      "path": "src/a.py",
      "score": 42.0,
      "reasons": ["..."],
      "symbols": ["..."],
      "qualified_symbols": ["..."],
      "fuzzy_corrections": {},
      "preview": "...",
      "detail": "...",
      "preview_tokens": 120,
      "redactions": []
    }
  ],
  "candidate_count": 1
}
```

## `impact --json`

```json
{
  "target": "refreshSession",
  "matched": [
    {
      "path": "src/auth.ts",
      "symbol": "refreshSession",
      "start_line": 10,
      "end_line": 20
    }
  ],
  "affected": [
    {
      "path": "tests/auth.test.ts",
      "reason": "related-test",
      "confidence": 0.85,
      "symbol": null,
      "start_line": null
    }
  ]
}
```

## `feedback` (always JSON)

```json
{"file": "src/auth.ts", "score": 1}
```

## `ranking-explain --json`

```json
{
  "query": "task text",
  "candidate_count": 20,
  "returned": 8,
  "top_limit": 8,
  "results": [
    {
      "rank": 1,
      "path": "src/auth.ts",
      "final_score": 81.2,
      "term_hits": 3,
      "changed": false,
      "reasons": ["..."],
      "stage_deltas": {"bm25": 12.3},
      "trace": [],
      "trace_complete": true
    }
  ]
}
```

## `evaluate` (always JSON)

```json
{
  "tasks": [],
  "repositories": {},
  "summary": {},
  "holdout_protocol_enforced": true,
  "ground_truth_sha256": "..."
}
```

Each task carries its expected/selected file and symbol evidence plus token
measurements. Repository and summary objects aggregate the same recall/reduction
metrics.

## `agent-evaluate` (always JSON)

```json
{
  "tasks": 10,
  "paired_trials": 30,
  "conditions": {
    "baseline": {
      "runs": 30,
      "successes": 28,
      "output_tokens_per_success": 910.0,
      "tokens_per_success": 12400.0
    },
    "token-saver": {
      "runs": 30,
      "successes": 28,
      "output_tokens_per_success": 590.0,
      "tokens_per_success": 8800.0
    }
  },
  "task_success_parity": true,
  "quality_parity": true,
  "quality_evidence": {
    "blinded": true,
    "judge": "independent-response-grader",
    "rubric": {},
    "baseline": {},
    "token-saver": {}
  },
  "blind_quality_verified": true,
  "raw_output_token_reduction": 0.35,
  "output_tokens_per_success_reduction": 0.35,
  "tokens_per_success_reduction": 0.29,
  "paired": {
    "paired_trial_count": 30,
    "unique_task_count": 10,
    "trials_per_task": {"min": 3, "max": 3},
    "output_token_reduction": {
      "count": 30,
      "mean": 0.34,
      "median": 0.35,
      "p10": 0.18,
      "p90": 0.48,
      "stdev": 0.12,
      "mean_ci95": [0.30, 0.38]
    },
    "total_token_reduction": {},
    "successful_pair_output_token_reduction": {},
    "bootstrap": {"samples": 2000, "seed": 1729}
  },
  "claim_allowed": true,
  "claim_blockers": []
}
```

`trial` defaults to `1` for legacy manifests; repeated runs should provide it
explicitly. Raw reductions are descriptive and can be reported without a quality
grader. `claim_allowed` requires blind quality evidence, task-success parity,
quality parity, and an available tokens-per-success comparison.
`claim_blockers` identifies missing or failed evidence gates.

## `ranking-snapshot` (always JSON or `--out`)

```json
{
  "schema_version": 1,
  "ground_truth_sha256": "...",
  "manifest": "holdout.json",
  "config": {},
  "repositories": {},
  "tasks": []
}
```

## `ranking-diff --json`

```json
{
  "schema_version": 1,
  "ground_truth_sha256": "...",
  "baseline_repositories": {},
  "candidate_repositories": {},
  "baseline_config": {},
  "candidate_config": {},
  "summary": {},
  "tasks": [],
  "violations": []
}
```

`violations` is added by the CLI to the comparison payload. With
`--fail-on-regression`, any violation makes the command exit `1`.

## `ranking-calibrate` (JSON by default)

When `--markdown` is not selected:

```json
{
  "selected_ground_truth_sha256": "...",
  "available_cohorts": {},
  "calibration": {}
}
```

Without `--ground-truth-sha`, the report uses a `cohorts` array instead of a
single `calibration` object.

## `experiment` (always JSON)

The experiment command writes/checkpoints the run artifact at `--out` and also
prints the experiment result as JSON. The result contains the frozen suite
identity, randomized schedule/run records, artifact references, and completion
state. Treat the file named by `--out` as the durable experiment artifact.

`--dry-run` validates and materializes the schedule without calling an agent.

## `cost-report --json`

```json
{
  "paired_task_count": 10,
  "unique_task_count": 10,
  "baseline": {},
  "optimized": {},
  "delta": {
    "input_token_reduction": 0.3,
    "output_token_reduction": 0.2,
    "total_token_reduction": 0.28,
    "cost_reduction": 0.25,
    "cost_per_success_reduction": 0.2,
    "latency_reduction": 0.1,
    "success_rate_change": 0.0,
    "tool_call_change": -3,
    "model_call_change": 0
  },
  "confidence": {},
  "outcomes": {},
  "task_alignment": {}
}
```

## `output-policy --json`

```json
{
  "mode": "normal",
  "max_tokens": 600,
  "task": "coding",
  "instructions": "..."
}
```

## `output-save --json`

```json
{
  "text": "...",
  "mode": "terse",
  "budget_tokens": 300,
  "original_tokens": 500,
  "output_tokens": 200,
  "token_reduction": 0.6,
  "removed_units": 4,
  "budget_exceeded": false,
  "code_preserved": true
}
```

## `output-benchmark` (always JSON)

```json
{
  "cases": [],
  "summary": {
    "case_count": 3,
    "original_tokens": 1000,
    "output_tokens": 300,
    "weighted_token_reduction": 0.7,
    "mean_token_reduction": 0.65,
    "code_preservation_rate": 1.0,
    "required_content_preservation_rate": 1.0,
    "budget_exceeded_rate": 0.0
  }
}
```

## `output-explain` (always JSON)

The object describes the selected processor and failure-routing evidence. Stable
consumer-facing keys include `processor`, routing/failure information, and the
command being explained. Consumers should tolerate additive diagnostic keys.

## `output-replay` (always JSON)

```json
{
  "cases": [],
  "summary": {
    "failed": 0
  }
}
```

Exit `1` means one or more replay quality contracts failed.

## `pack-diff --json`

```json
{
  "context": "...",
  "coverage": {
    "selected": [],
    "changed_files": 0,
    "not_represented": [],
    "excluded_by_policy": []
  }
}
```

Additional patch-evidence fields may be present.

## `review --json`

```json
{
  "files": [],
  "warnings": []
}
```

Each file entry contains status/path/symbol evidence. Warning entries contain a
stable warning `code` plus path/detail evidence.

## Legacy `benchmark` (always JSON)

The legacy benchmark prints the paired benchmark report returned by
`token_saver.benchmark.evaluate`. The report contains protocol validity,
quality/cost results, task-level comparisons, and confidence intervals. Use
`--require-publishable` when consuming it as evidence for a public claim.

## Compatibility rule

Scripts should:

1. depend on documented top-level keys rather than exact object equality;
2. tolerate additive nested fields;
3. treat nullability described above as meaningful evidence state, not as zero;
4. check the process exit code before trusting the JSON as a passing gate.
