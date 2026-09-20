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
  "version": "1.7.0",
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

## `blind-grade` (always JSON)

A completed grading run returns the full paired manifest with run-level
`quality` and `blocker` fields plus:

```json
{
  "quality_evaluation": {
    "blinded": true,
    "judge": "claude-sonnet-5",
    "rubric_version": 1,
    "weights": {
      "correctness": 0.4,
      "completeness": 0.2,
      "actionability": 0.15,
      "safety": 0.15,
      "concision": 0.1
    },
    "assignment_seed": 20260920,
    "grader_command_sha256": "...",
    "pair_count": 72,
    "completed_pairs": 72,
    "position_balance": {
      "baseline_as_a": 36,
      "baseline_as_b": 36
    }
  },
  "blind_grading": {
    "schema": 1,
    "records": [
      {
        "task": "task-id",
        "trial": 1,
        "blind_pair_id": "...",
        "grader_request_sha256": "...",
        "grader_output_sha256": "...",
        "seconds": 4.2
      }
    ]
  }
}
```

`--dry-run` returns the deterministic A/B assignment plan without judge calls.
The audit hashes do not store grader prompts or response text.

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

## `evidence-run` (always JSON)

```json
{
  "schema": 1,
  "stage": "complete",
  "suite": "/path/to/frozen-suite.json",
  "runs": "/path/to/benchmark-runs.json",
  "effectiveness": "/path/to/benchmark-runs.effectiveness.json",
  "calibration": "/path/to/benchmark-runs.output-calibration.json",
  "graded_pairs": 72,
  "publication_gate": {
    "passed": true,
    "blockers": []
  },
  "claim_allowed": true
}
```

The durable run/effectiveness/calibration files contain the detailed evidence.
With `--dry-run`, `stage` is `"dry-run"` and the result contains the
experiment schedule plus grader/pricing readiness.

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

## `output-effectiveness --json`

```json
{
  "schema": 1,
  "source": "benchmark-runs.json",
  "tasks": 20,
  "paired_trials": 60,
  "trials_per_task": {"min": 3, "max": 3},
  "pricing": {
    "fresh_input_per_million": 3.0,
    "cache_creation_5m_per_million": 3.75,
    "cache_creation_1h_per_million": 6.0,
    "cache_creation_unknown_per_million": null,
    "cache_read_per_million": 0.3,
    "output_per_million": 15.0,
    "supplied": true
  },
  "conditions": {
    "baseline": {"runs": 60, "success_rate": 0.95},
    "token-saver": {"runs": 60, "success_rate": 0.95}
  },
  "delta": {
    "success_rate_change": 0.0,
    "cost_per_success_reduction": 0.22,
    "output_token_reduction": 0.31
  },
  "protocol": {
    "valid": true,
    "declared_task_definition_sha256": "...",
    "computed_task_definition_sha256": "...",
    "pair_identity_missing": [],
    "pair_identity_mismatches": [],
    "frozen_run_mismatches": [],
    "exact_usage_missing": []
  },
  "quality": {
    "blinded": true,
    "judge": "independent-response-grader",
    "parity": true,
    "tolerance": 0.1
  },
  "telemetry": {
    "optimized_runs": 60,
    "runs_with_policy_telemetry": 60,
    "incomplete_runs": [],
    "usage_mismatches": [],
    "ungrouped_runs": 0
  },
  "budget_groups": {
    "coding:normal:600": {
      "runs": 12,
      "tasks": 4,
      "success_rate": 1.0,
      "quality_safe_rate": 1.0,
      "p90_output_tokens": 420.0,
      "mean_budget_utilization": 0.61,
      "eligible_for_calibration": true
    }
  },
  "bootstrap": {
    "samples": 2000,
    "seed": 20260920,
    "task_clusters": 20,
    "cost_per_success_reduction_ci95": [0.12, 0.30]
  },
  "publication_gate": {
    "required_tasks": 20,
    "required_trials_per_task": 3,
    "passed": true,
    "blockers": []
  },
  "claim_allowed": true
}
```

The publication gate fails closed when the frozen suite hash or run identity
does not match, exact transcript usage is incomplete, blind quality is
missing/regressed, task success regresses, optimized policy telemetry lacks a
measured task/mode/budget, telemetry usage disagrees with the copied transcript,
cost evidence is incomplete, or the cost-per-success point estimate / 95% task-
cluster confidence interval does not show a strictly positive reduction. Budget-group
`eligible_for_calibration` is only a candidate signal; `output-calibrate`
still applies its own cross-task quality gate before changing learned bases.

## `output-calibrate` (always JSON or `--out`)

```json
{
  "schema": 1,
  "source": "benchmarks/agent-runs.json",
  "quality_gate": "blind paired success + correctness/safety/weighted parity",
  "recommendations": {
    "coding": {
      "normal": {
        "recommended_tokens": 667,
        "samples": 6,
        "tasks": 4,
        "p90_output_tokens": 580.0,
        "margin": 1.15
      }
    }
  }
}
```

Recommendations are omitted for task/mode groups with fewer than three valid
quality-preserving paired samples or fewer than three distinct task IDs. The runtime treats missing/invalid calibration
as no learned override and falls back to built-in bases.

## `output-telemetry --json`

```json
{
  "schema": 1,
  "path": "~/.claude/token-saver/telemetry/<project>.jsonl",
  "summary": {
    "turns": 12,
    "measured_turns": 12,
    "completed_turns": 11,
    "api_failures": 1,
    "input_tokens": 2200,
    "cache_creation_input_tokens": 18000,
    "cache_creation_5m_input_tokens": 12000,
    "cache_creation_1h_input_tokens": 6000,
    "cache_read_input_tokens": 92000,
    "output_tokens": 6400,
    "model_calls": 28,
    "mean_output_tokens": 533.3,
    "p90_output_tokens": 810.0,
    "mean_selected_budget": 700.0,
    "mean_budget_utilization": 0.76,
    "p50_budget_utilization": 0.70,
    "p90_budget_utilization": 1.10,
    "target_met_rate": 0.83
  },
  "by_task_mode": {},
  "signals": {
    "underused_budget_groups": [],
    "frequent_target_overrun_groups": [],
    "minimum_turns": 5,
    "observational_only": true
  },
  "evidence_limits": {
    "task_success_evidence": false,
    "quality_evidence": false,
    "note": "..."
  }
}
```

With `--records`, a bounded `records` array is added. Those records contain
policy metadata, opaque session fingerprints, model identifiers, and usage
counters only. They do not contain prompt, response, or tool-result content.
Budget signals are observational; they do not authorize a smaller calibrated
budget without separate success/quality evidence.

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
