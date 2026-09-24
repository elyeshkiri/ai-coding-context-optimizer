# `acco trial`

Run a simple local baseline-versus-ACCO A/B trial on one real coding task.

## Synopsis

```bash
acco trial [path] --prompt TEXT --verify COMMAND [options]
acco trial [path] --prompt-file FILE --verify COMMAND [--verify COMMAND ...] [options]
```

Examples:

```bash
acco trial . \
  --prompt "Fix the refresh-session regression." \
  --verify "pytest -q tests/test_auth.py"

acco trial . \
  --prompt-file task.md \
  --verify "pytest -q" \
  --trials 3 \
  --require-both-success
```

## Arguments and options

- `path` — Git repository to test; default current directory.
- `--prompt TEXT` / `--prompt-file FILE` — exactly one is required.
- `--verify COMMAND` — independent post-agent verifier; required and repeatable.
  Commands are parsed to argv without a shell.
- `--setup COMMAND` — optional repeatable setup command executed inside each
  isolated repository snapshot before the agent.
- `--model MODEL` — exact model id supplied to the runner; default
  `claude-sonnet-5`.
- `--trials N` — paired trials for the same task; default 1.
- `--timeout SECONDS` — per-agent-run timeout; default 1800.
- `--out FILE` — durable result manifest. Without it, ACCO writes under its
  private state directory.
- `--runner COMMAND` — custom runner. Supported placeholders are
  `{prompt}`, `{prompt_file}`, `{worktree}`, `{transcript}`,
  `{model}`, and `{condition}`.
- `--transcript-mode claude-project|path` — whether usage evidence is
  discovered from Claude Code's project transcript or written by the custom
  runner to `{transcript}`.
- `--allow-dirty` — explicitly benchmark committed `HEAD` while ignoring
  uncommitted working-tree changes. Without this flag a dirty tree is refused.
- `--allow-user-hook` — permit a pre-existing user-level ACCO hook. This can
  contaminate the baseline and is therefore refused by default.
- `--dry-run` — validate the suite and randomized paired schedule without
  executing the agent.
- `--json` — emit the machine-readable result.
- `--require-both-success` — after a real run, exit 1 unless every baseline
  and enabled run passes the independent verifier.

The trial reuses ACCO's experiment engine. Each arm receives a history-isolated
snapshot of the same committed revision. The baseline has ACCO disabled; the
enabled arm installs ACCO only inside its isolated snapshot. Verification runs
after agent execution.

A local trial is deliberately **not** a publishable general savings benchmark.
It lacks the broad frozen task set and blind response-quality gate required by
ACCO's publication protocol. Token deltas are workload evidence and are shown
per independently verified success where possible.

## Exit codes

- `0` — trial/dry-run completed; or all requested success gates passed.
- `1` — `--require-both-success` was requested and at least one arm failed
  its independent verifier.
- `2` — invalid repository/prompt/verifier/runner configuration, unsafe dirty
  state, missing transcript evidence, or agent/runtime failure.

## Output contract

With `--json`, the top-level object contains `schema`, `root`,
`revision`, `suite`, `manifest`, `dirty_worktree_ignored`, and
`trial`. Completed runs also include `summary` with baseline/enabled
success, token, tool-call, and per-success measurements plus explicit evidence
limits.

See [Machine-readable contracts](../JSON_OUTPUTS.md#trial---json).

The generated `*.suite.json` and result manifest are retained so the exact
local comparison can be inspected. They are not promoted to frozen benchmark
evidence.

## Authoritative runtime help

Run `acco trial --help` for argparse's exact usage text for the installed version.
