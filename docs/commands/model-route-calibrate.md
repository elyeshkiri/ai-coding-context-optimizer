# `token-saver model-route-calibrate`

Build a fail-closed model-routing calibration artifact from a frozen paired
experiment that compares a stronger static-policy baseline model with a cheaper
candidate model.

## Synopsis

```bash
token-saver model-route-calibrate MANIFEST
  [--out .token-saver.routing-calibration.json]
  [--stdout]
```

## Arguments and options

- `MANIFEST` — completed paired experiment JSON after `blind-grade`.
- `--out FILE` — calibration artifact path; defaults to
  `.token-saver.routing-calibration.json`.
- `--stdout` — emit the artifact to stdout instead of writing `--out`.

The experiment must isolate model choice as the treatment. Its explicit
`runner.condition_profiles.baseline` and `enabled` entries must use the same
Token Saver installation setting and environment; only `model` and an optional
human label may differ.

An exact routing bucket is promoted only when all of these gates pass:

- at least 10 paired runs across at least 5 distinct frozen tasks;
- frozen/randomized/history-isolated experiment protocol with independent
  hidden/post-agent verification;
- complete blinded A/B response grading;
- baseline success rate at least 80%;
- zero baseline-success to candidate-failure regressions;
- candidate success rate at least the baseline rate;
- no candidate quality blocker;
- correctness, safety, and weighted blind quality each within 0.10 points of
  the baseline on every pair;
- declared models exactly match the single actual model observed in each
  transcript;
- the baseline model is the current static routing choice for that bucket;
- the candidate is lower-capability and strictly cheaper across the verified
  pricing-registry token-rate fields.

Recommendations are scoped to the exact
`task + complexity_tier + risk_level + baseline_model + candidate_model`
bucket. Evidence for normal-risk standard debugging cannot relax high-risk,
complex, review, coding, or other buckets.

## Exit codes

- `0` — evidence evaluated and artifact emitted/written, even if zero buckets
  qualify;
- `2` — malformed, incomplete, confounded, unblinded, non-independent, or
  model-identity-invalid evidence.

## Output contract

The JSON artifact contains `schema`, source hash, immutable gate metadata,
accepted `recommendations`, and all evaluated `groups` with explicit
rejection reasons. See
[Machine-readable contracts](../JSON_OUTPUTS.md#model-route-calibrate-artifact).

## Authoritative runtime help

Run `token-saver model-route-calibrate --help`.
