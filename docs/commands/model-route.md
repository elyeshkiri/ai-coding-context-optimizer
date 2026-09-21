# `token-saver model-route`

Choose the cheapest explicitly profiled model that first satisfies Token Saver's
deterministic task, complexity, and risk policy.

## Synopsis

```bash
token-saver model-route PROMPT [--input-tokens N] [--output-tokens N]
  [--current-model MODEL] [--allowed-model MODEL ...]
  [--min-savings FRACTION] [--non-conservative] [--json]
```

## Decision order

1. classify the task with the same deterministic task classifier used by output
   budgeting;
2. derive the bounded complexity tier;
3. escalate the minimum capability for debugging/review, broad complex changes,
   and explicit high-risk domains such as production, security, migrations,
   concurrency, or destructive data operations;
4. discard models that do not satisfy that capability profile;
5. only then choose the lowest projected one-turn cost from the fresh built-in
   pricing registry.

Price therefore never overrides the capability gate.

The default routing set is:

- `claude-haiku-4-5` — economy profile for simple/standard low-risk work;
- `claude-sonnet-5` — balanced profile for coding/debugging/review and complex
  work;
- `claude-opus-5` — deep profile for extended or high-risk complex work.

These are conservative Token Saver routing profiles, not benchmark rankings of
model intelligence.

## Cost projection

If `--input-tokens` is supplied, it should be the complete request input size.
Otherwise Token Saver estimates only the prompt text and labels the basis as
`local_prompt_text_estimate_only`.

The projection includes fresh input plus the selected output-budget target for
one turn. It does not claim cache behavior, history propagation, task success,
or realized API savings.

## Automatic integration

The same decision engine is exposed as the MCP `route_task` tool. An
orchestrator that can select models can consume its `selected_model` and
`action` directly.

Claude Code's current Token Saver `UserPromptSubmit` hook can automatically
compute and record the route, but it cannot itself replace the active top-level
Claude model. With `[model_routing] mode = "advisory"`, it injects a concise
host-neutral recommendation for model-selectable subagents/orchestrators.
`mode = "observe"` records decisions without injecting advice.

## Exit codes

- `0` — routing decision produced;
- `2` — invalid token/savings bounds, unknown routing model profile, or stale
  built-in pricing.

## Output contract

See [Machine-readable contracts](../JSON_OUTPUTS.md#model-route---json).

## Authoritative runtime help

Run `token-saver model-route --help`.
