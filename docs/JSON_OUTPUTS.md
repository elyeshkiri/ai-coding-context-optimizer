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
  "version": "1.13.0",
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
  "cache_hit": false,
  "cache_key": "sha256-or-null",
  "semantic_index": null,
  "typescript_semantic_edges": 0
}
```

## `ingress-show --json`

```json
{
  "id": "stage-id",
  "created_at": 0,
  "original_sha256": "...",
  "original_tokens": 15000,
  "packet_tokens": 1500,
  "original_lines": 400,
  "packet": "# TOKEN-SAVER STAGED PROMPT...",
  "omitted_start_line": 50,
  "omitted_end_line": 350
}
```

The exact original prompt is intentionally not embedded as a second JSON field.
Use `ingress-read` for explicit bounded recovery.

## `fastpath-status --json`

```json
{
  "available": true,
  "backend": "rust",
  "capabilities": [
    "estimate_tokens",
    "identifier_tokens",
    "bm25_score",
    "jaccard_similarity",
    "char_ngrams"
  ],
  "env_override": null
}
```

`backend: "python"` with an empty capability list is a supported fallback
state, not a degraded/error JSON contract.

## `claude-plugin-path --json`

```json
{
  "schema": 1,
  "version": "1.13.0",
  "path": "/absolute/private/token-saver/claude-plugin/token-saver-1.13.0",
  "rendered": true
}
```

Text mode intentionally prints only the absolute path so Claude Code's
command-source marketplace contract can consume it.

When `--semantic` / `--embeddings` is active, `semantic_index` contains
the same status shape documented below; otherwise it is `null`.

## `semantic-index --json` / `semantic-status --json`

```json
{
  "schema": 2,
  "files": 240,
  "chunks": 918,
  "dimensions": 384,
  "model": "all-MiniLM-L6-v2",
  "model_revision": null,
  "backend": "hnsw",
  "path": "/private/token-saver/semantic-index/.../....sqlite3"
}
```

`model_revision` is `null` for the ordinary floating local-model configuration
and contains the pinned revision when `TOKEN_SAVER_SEMANTIC_MODEL_REVISION` is
set. The revision participates in the vector-store and query-cache identity.

`semantic-index` synchronizes changed repository evidence before returning the
document. `semantic-status` returns the same shape without loading the
embedding model. `backend` is `hnsw` when a synchronized optional sidecar is
active and `sqlite-cosine` for the exact vector-scan fallback.

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

## `session-holdout` (always JSON)

Dry-run output validates the frozen design without paid agent calls:

```json
{
  "schema": 1,
  "stage": "dry-run",
  "comparison": {
    "baseline": "v1.6-session-baseline",
    "treatment": "v1.7-session-efficiency"
  },
  "experiment": {
    "task_count": 24,
    "trials_per_task": 3,
    "paired_trials": 72,
    "run_count": 144,
    "condition_profiles": {
      "baseline": {
        "label": "v1.6-session-baseline",
        "install_token_saver": true,
        "env": {
          "TOKEN_SAVER_EFFICIENCY": "0"
        }
      },
      "enabled": {
        "label": "v1.7-session-efficiency",
        "install_token_saver": true,
        "env": {
          "TOKEN_SAVER_EFFICIENCY": "1"
        }
      }
    }
  }
}
```

A completed run prints a compact summary pointing to the durable run and
`*.session-effectiveness.json` report. The report contains:

```json
{
  "schema": 1,
  "comparison": {
    "baseline": "v1.6-session-baseline",
    "treatment": "v1.7-session-efficiency",
    "causal_scope": "combined_bundle_only"
  },
  "tasks": 24,
  "paired_trials": 72,
  "conditions": {
    "baseline": {
      "tool_calls": 0,
      "input_tokens": 0,
      "retry_attempts": 0,
      "cost_per_success_usd": null
    },
    "session-efficiency": {
      "tool_calls": 0,
      "input_tokens": 0,
      "retry_attempts": 0,
      "cost_per_success_usd": null
    }
  },
  "reductions": {
    "tool_calls": null,
    "input_tokens": null,
    "retry_attempts": null,
    "repeat_command_calls": null,
    "duplicate_read_calls": null,
    "cost_per_success": null
  },
  "bootstrap": {
    "samples": 2000,
    "seed": 271828,
    "task_clusters": 24,
    "intervals": {
      "tool_calls": null,
      "input_tokens": null,
      "retry_attempts": null,
      "cost_per_success_usd": null
    }
  },
  "feature_activation": {
    "treatment": {
      "active_runs": {
        "dedup": 0,
        "continuity": 0,
        "waste": 0
      }
    },
    "control": {
      "totals": {
        "events": 0
      }
    }
  },
  "publication_gate": {
    "passed": false,
    "blockers": []
  },
  "claim_allowed": false
}
```

The control/treatment labels describe session behavior profiles of the same
current binary; they are not package-version provenance.

## `session-holdout-evaluate --json`

Returns the full `session-effectiveness` object above. With
`--require-publishable`, a blocked publication gate exits `1`.




## `model-route --json`

```json
{
  "task": "debugging",
  "complexity_tier": "standard",
  "complexity_score": 1,
  "risk_level": "normal",
  "risk_signals": [],
  "minimum_capability": "balanced",
  "selected_model": "claude-sonnet-5",
  "current_model": null,
  "action": "recommend",
  "allowed_models": [
    "claude-haiku-4-5",
    "claude-sonnet-5",
    "claude-opus-5"
  ],
  "eligible_models": [
    "claude-sonnet-5",
    "claude-opus-5"
  ],
  "calibrated_models": [],
  "calibration_applied": false,
  "calibration_source": null,
  "estimated_input_tokens": 1200,
  "input_token_basis": "caller_supplied_complete_input",
  "estimated_output_tokens": 900,
  "projected_cost_usd": {},
  "projected_current_cost_usd": null,
  "projected_savings_fraction": null,
  "pricing_basis": "fresh_input_plus_output_one_turn",
  "reasons": []
}
```

`action` is `recommend` when no current model is known, `keep` when the
current model should remain, `route` when a switch satisfies policy/economic
rules, or `manual` when the allowed model set cannot satisfy the capability
gate. Projected economics are counterfactual one-turn estimates, not realized
task-success-adjusted savings.

## Model-route-calibrate artifact

```json
{
  "schema": 1,
  "source": "routing-runs.json",
  "source_sha256": "...",
  "quality_gate": {
    "minimum_pairs": 10,
    "minimum_tasks": 5,
    "minimum_baseline_success_rate": 0.8,
    "maximum_quality_drop": 0.1,
    "success_regressions_allowed": 0,
    "requires_blinded_quality": true,
    "requires_independent_verification": true,
    "requires_transcript_model_confirmation": true,
    "bucket_scope": "exact task + complexity + risk + baseline/candidate model"
  },
  "recommendations": [],
  "groups": []
}
```

`recommendations` contains only buckets that pass every hard gate. `groups`
also retains rejected comparisons with explicit `rejection_reasons`. Runtime
loading rechecks sample/task floors, success parity, zero regressions, blind
quality deltas, model ordering, and evidence booleans before any recommendation
can relax the static router.

## `pricing --json`

```json
{
  "status": {
    "schema": 1,
    "provider": "anthropic",
    "currency": "USD",
    "unit": "per_million_tokens",
    "verified_at": "2026-09-21",
    "age_days": 0,
    "max_age_days": 30,
    "fresh": true,
    "model_count": 5,
    "alias_count": 1,
    "source_url": "https://platform.claude.com/docs/en/about-claude/pricing",
    "source_markdown_url": "https://platform.claude.com/docs/en/about-claude/pricing.md",
    "scope": "..."
  },
  "models": {
    "claude-sonnet-5": {
      "display_name": "Claude Sonnet 5",
      "aliases": [],
      "rates": {
        "input": 2.0,
        "cache_write_5m": 2.5,
        "cache_write_1h": 4.0,
        "cache_read": 0.2,
        "output": 10.0
      }
    }
  }
}
```

Rates are USD per million tokens. The built-in registry is limited to the scope
reported in `status.scope`; it does not silently apply batch, fast-mode,
data-residency, or partner-cloud modifiers. With `--model`, `models` contains
only the resolved canonical registry entry.

## `cost-advisor --json`

```json
{
  "schema": 1,
  "root": "/project",
  "window_days": 7,
  "score": {
    "points": 72,
    "available_max_points": 80,
    "percent": 90.0,
    "coverage": 0.8,
    "grade": "A",
    "categories": []
  },
  "context": {
    "always_on_tokens": 1800,
    "on_demand_tokens": 900,
    "counter": "≈est",
    "mcp_servers_configured": [],
    "largest_always_on": []
  },
  "usage": {
    "summary": {},
    "models": {},
    "measured_turns": 12,
    "mixed_model_turns": 0
  },
  "cost": {
    "available": true,
    "complete": true,
    "usd": 0.1234,
    "priced_usd": 0.1234,
    "priced_turns": 12,
    "measured_turns": 12,
    "coverage": 1.0,
    "incomplete_reasons": []
  },
  "savings": {
    "estimated_tool_context_tokens": 4200,
    "by_feature": {},
    "events": 4,
    "trust": "...",
    "fresh_input_once_projection": {
      "available": true,
      "by_observed_model_usd": {},
      "assumption": "..."
    }
  },
  "behavior": {},
  "continuity": {},
  "recommendations": [],
  "evidence": {}
}
```

`score.coverage` is separate from the normalized score so missing telemetry
cannot silently become a zero or a perfect score. `cost.usd` is non-null only
for complete exact-model pricing coverage; `priced_usd` may contain a clearly
labeled partial subtotal. Estimated transformation savings remain token
estimates. The fresh-input-once projection is a counterfactual scenario, not an
API invoice or an end-to-end cost-per-success claim.

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
  "protocol": {
    "frozen": true,
    "frozen_at": "2026-09-20T13:00:00Z",
    "declared_definition_sha256": "...",
    "computed_definition_sha256": "...",
    "valid": true
  },
  "cases": [
    {
      "id": "lint-ruff-diagnostics",
      "processor": "lint",
      "missing_required": [],
      "introduced_forbidden": [],
      "preservation_ok": true,
      "no_hallucination": true,
      "passed": true
    }
  ],
  "summary": {
    "failed": 0,
    "preservation_rate": 1.0,
    "no_hallucination_rate": 1.0
  }
}
```

Exit `1` means one or more replay quality contracts failed. With
`--require-frozen`, malformed/mutated freeze metadata exits `2`.

## `recover --json`

```json
{
  "handle": "tsr_0123456789abcdef0123456789abcdef",
  "content_type": "text/plain",
  "encoding": "utf-8",
  "payload": "exact recovered content",
  "output": null,
  "size_bytes": 1280,
  "metadata": {
    "transform": "provider-tool-result"
  },
  "access_count": 2
}
```

When `--output FILE` is used, `payload` is `null` and `output` contains
the resolved destination path. Binary payloads use `encoding: "base64"`.
Integrity is checked before bytes are returned.

## `recovery-status --json`

```json
{
  "path": "/private/token-saver/recovery/project.sqlite3",
  "records": 14,
  "used_bytes": 1048576,
  "capacity_bytes": 536870912,
  "remaining_bytes": 535822336
}
```

The command reports capacity only; it never returns stored source content.

## `prefix-status --json`

```json
{
  "providers": {
    "anthropic": {
      "hits": 8,
      "misses": 2,
      "reuse_rate": 0.8,
      "stable_tokens": 4200,
      "stable_bytes": 16800,
      "components": ["system", "tools", "messages[:-latest-user]"],
      "fingerprint": "sha256-hex"
    }
  }
}
```

The fingerprint is content-derived evidence, not request text. `reuse_rate`
is `null` until at least one comparable prior prefix observation exists.

## `browser-context --json`

```json
{
  "text": "focused browser context\n[token-saver recovery: tsr_...]",
  "changed": true,
  "original_tokens": 12000,
  "output_tokens": 430,
  "recovery_handle": "tsr_0123456789abcdef0123456789abcdef",
  "matched_terms": ["checkout", "total"]
}
```

When focusing is not smaller or exact recovery cannot be guaranteed,
`changed` is false, `recovery_handle` is null, and `text` is the original
caller-supplied payload.

## `optimize --json`

Planning mode returns currently applicable Token Saver-owned configuration
hypotheses:

```json
{
  "schema": 1,
  "root": "/project",
  "window_days": 7,
  "proposals": [
    {
      "id": "adaptive-mcp",
      "title": "Use adaptive MCP tool disclosure",
      "rationale": "...",
      "section": "mcp",
      "key": "profile",
      "value": "adaptive",
      "risk": "low"
    }
  ],
  "advisor_recommendations": [],
  "evidence": {
    "measured": "provider-reported usage is used when available",
    "not_claimed": "a proposal is not a savings claim until a post-change evaluation"
  }
}
```

`--apply PROPOSAL_ID --json` returns the journal record, including
`id`, `proposal`, `config_path`, exact-config `recovery_handle`,
`baseline_mean_tokens_per_turn`, `baseline_turns`, `applied_at`, and
`status`.

`--evaluate RUN_ID --json` adds
`treatment_mean_tokens_per_turn`, `treatment_turns`, `min_improvement`,
`decision`, `reverted`, and the updated `status`. A decision may be
`keep`, `revert`, `insufficient-baseline`, or
`insufficient-treatment`; insufficient evidence is not converted to zero
savings.

`--status --json` returns:

```json
{"runs": []}
```

## Long-running service commands

`provider-proxy` is a long-running reverse-proxy process and deliberately has
no one-shot JSON report. Use `prefix-status --json`,
`recovery-status --json`, and the normal process exit/log stream for
operational evidence.

## `dashboard --json`

```json
{
  "schema": 1,
  "window_days": 7,
  "savings": {
    "estimated_tool_context_tokens": 4200,
    "by_feature": {
      "cross_turn_dedup": 1800,
      "output_compression": 1600,
      "unchanged_read_block": 800
    },
    "events": 8,
    "trust": "Estimated from observed before/after local tool text..."
  },
  "continuity": {
    "restores": 2,
    "tracked_sessions": 3
  },
  "behavior": {
    "signals": {
      "retry_loop": 1
    },
    "events": 1
  },
  "billed_usage": {
    "input_tokens": 12000,
    "cache_read_input_tokens": 44000,
    "output_tokens": 3200
  },
  "evidence": {
    "task_success": false,
    "quality_verified": false
  }
}
```

The savings bucket is operational before/after estimation, not billed-dollar or
cost-per-success evidence. `billed_usage` comes from exact available Claude
transcript counters for the same requested time window.

## `continuity --json`

```json
{
  "schema": 1,
  "available": true,
  "task": "debugging",
  "working_files": [
    {"path": "src/auth.py", "action": "edit", "at": 0}
  ],
  "commands": [],
  "failures": [],
  "validations": [],
  "last_activity": 0,
  "privacy": "No raw user prompt, assistant response, or tool output is stored..."
}
```

Command labels, when present, are bounded and credential-redacted before local
persistence.

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

## Durable project knowledge

### `remember --json`

Emits one finding object with:

- `id`, `claim`, `evidence`, `applicability`, `confidence`;
- `anchors[]` containing `path`, optional `symbol`, stored `digest`, and
  current `current_digest`;
- `invalidators[]`, `supersedes[]`, `source`;
- `created_at`, `updated_at`, `version`;
- current `state` and `stale_reasons[]`.

### `recall --json`

Emits an array of the same finding objects plus deterministic lexical `score`.
Without `--include-stale`, only `state == "active"` findings appear.

### `knowledge-status --json`

Emits `schema`, `total`, `active`, `stale`, `superseded`, and the private
local `path`. Finding contents are intentionally absent.

## `cache-economics --json`

```json
{
  "accepted": true,
  "original_cost": 6200.0,
  "replacement_cost": 1400.0,
  "relative_savings": 0.774,
  "cached_prefix_tokens": 12000,
  "original_frontier_tokens": 4000,
  "replacement_frontier_tokens": 800,
  "invalidates_cached_prefix": false,
  "expected_reuses": 2,
  "cache_write_factor": 1.25,
  "cache_read_factor": 0.1,
  "min_relative_savings": 0.05
}
```

Costs are relative input-cost units. The command does not imply universal
provider pricing.

## Knowledge-efficiency holdout reports

`knowledge-holdout` emits the same pipeline-summary class as
`session-holdout`: `schema`, `stage`, suite/run/report paths, task and
paired-trial counts, `reductions`, `feature_activation`,
`publication_gate`, and `claim_allowed`.

`knowledge-holdout-evaluate --json` emits the full paired report with:

- `comparison`, `tasks`, `paired_trials`, and `trials_per_task`;
- `conditions.baseline` and `conditions.knowledge-efficiency`;
- reductions for `tool_calls`, `input_tokens`, `duplicate_read_calls`, and
  `cost_per_success`;
- task-cluster `bootstrap` intervals;
- treatment/control `feature_activation`;
- independent `quality` evidence;
- frozen `protocol` identity;
- `publication_gate` and `claim_allowed`.

## Compatibility rule

Scripts should:

1. depend on documented top-level keys rather than exact object equality;
2. tolerate additive nested fields;
3. treat nullability described above as meaningful evidence state, not as zero;
4. check the process exit code before trusting the JSON as a passing gate.
