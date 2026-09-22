# Output optimization, quality contracts, and diagnostic Delta

Token Saver's output layer reduces command noise without treating all terminal
text as disposable. Version 1.5.0 introduces three related capabilities:

1. a pluggable, failure-aware output processor registry;
2. registry-wide critical-diagnostic recovery plus replayable quality contracts;
3. an opt-in graph-aware Delta for repeated pytest and Ruff diagnostics.

The design goal is simple: **remove repeated or low-value output only when the
information needed to solve the task remains available**.

Generation-time response control is a separate path from terminal-output
compression. With Claude Code setup, `UserPromptSubmit` classifies the task and
injects the task-aware `output-policy` contract before completion generation.
The policy is remembered per host session and re-injected only when task/mode
changes or context is reset. This is the path that can reduce billable model
output; post-generation compaction cannot refund tokens already emitted.

### Turn-level budget telemetry

The same prompt hook checkpoints the current Claude transcript byte offset after
the policy is resolved. Claude's per-turn `Stop`/`StopFailure` hook supplies
the transcript path after generation. Token Saver then parses only newly
appended assistant usage records, deduplicating repeated content-block rows by
message id, and stores the real usage counters alongside the selected policy.

This telemetry answers questions such as "which task/mode budgets are routinely
far above observed output?" and "which groups exceed the soft target often?"
It does **not** answer "did the task succeed?" or "was the shorter answer good?"
Those claims still require independent verification/blind quality evidence.

## 1. Failure-aware output processor registry

Bash stdout is routed through a priority-ordered processor registry. The first
matching processor handles the output; a conservative generic processor is the
fallback.

Specialized processors now cover:

- pytest;
- Jest/Vitest and common JavaScript test commands;
- `git log` and `git status`;
- grep/ripgrep/find result sets;
- Ruff/ESLint/Pylint/Clippy diagnostics;
- tsc/mypy/pyright diagnostics;
- Go/Cargo tests;
- Cargo/Go/Gradle/Maven/npm/pnpm/yarn builds;
- npm/pnpm/yarn/bun/pip/uv installs;
- successful Docker/Kubernetes log dumps.

Unknown failed commands still fall back to the conservative generic path.

The public compatibility API remains:

```python
from token_saver.filter_output import filter_command_output

compressed = filter_command_output(
    output,
    command="pytest -q",
    exit_code=1,
)
```

### Failure-aware routing

Processors declare whether they are safe to use on failed commands. A
success-oriented processor is skipped when the command failed unless it
explicitly opts into failure handling.

This matters for commands such as package installation: a successful run can
contain hundreds of repetitive progress lines, while a failed run may contain
the only actionable dependency-resolution message.

Unknown failures therefore fall back conservatively instead of being forced
through an optimistic success compressor.

Inspect the routing decision without running the command:

```bash
token-saver output-explain "pytest -q"
token-saver output-explain "npm install" --exit-code 1
```

The second command reports that the package-install processor was skipped for
the failed command and that the generic conservative fallback was selected.

### Compression ratio gate

Every processor is subject to a final size gate. If the transformed output is
not materially smaller, Token Saver keeps the original output instead.

This avoids spending context on explanatory wrappers that save little or
nothing.

## 2. Critical-line recovery

Format-specific processors are not the final authority on diagnostic safety.
After a processor returns, Token Saver scans the original output for
high-signal lines such as:

- `ERROR`, `FAILED`, `FATAL`, and `PANIC`;
- traceback and assertion markers;
- `Caused by:`;
- source locations such as `src/auth.py:42`.

If one of those lines disappeared from the candidate output, the shared recovery
pass can append it under:

```text
[token-saver: recovered critical diagnostics]
```

This is defense in depth. A bug in a single processor should not automatically
become a silent loss of the most obvious failure evidence.

Recovery is still bounded, and the resulting output must remain smaller than the
original.

## 3. Replayable output quality contracts

Compression ratios alone are not a correctness guarantee. Version 1.5.0 adds
`output-replay`, which evaluates captured command output against explicit
preservation and savings requirements.

Example:

```json
{
  "cases": [
    {
      "id": "pytest-auth-failure",
      "command": "pytest -q",
      "exit_code": 1,
      "path": "fixtures/pytest-auth-failure.txt",
      "must_preserve": [
        "tests/test_auth.py::test_refresh",
        "AssertionError: expected 200, got 401"
      ],
      "max_tokens": 300,
      "min_reduction": 0.50
    }
  ]
}
```

Run it with:

```bash
token-saver output-replay quality.json
```

Each case can define:

- `command`: the command whose output shape is being evaluated;
- `exit_code`: optional original command status;
- exactly one of `text` or `path`;
- `must_preserve`: exact strings that must survive;
- `must_not_contain`: strings that must not be introduced by compression;
- `max_tokens`: optional maximum estimated output budget;
- `min_reduction`: optional minimum token reduction from 0 to 1.

Version 1.7 also supports a hash-frozen replay protocol. CI runs
`benchmarks/output-quality-session-v17.frozen.json` with
`--require-frozen`, so changing a fixture, preservation rule, no-hallucination
rule, or reduction floor changes benchmark identity and cannot silently weaken
the release gate.

The command exits non-zero when any contract fails, making it suitable for CI.

A small checked-in example is available at
`benchmarks/output-quality.example.json`.

These contracts complement Token Saver's other validation layers:

```text
retrieval holdouts
    -> did we select the right source?

output quality contracts
    -> did we preserve the required diagnostics?

paired agent / SWE-bench experiments
    -> did the agent still solve the task at lower cost?
```

## 4. Graph-aware diagnostic Delta

Repeated edit/test loops often spend context on failures the model has already
seen. Delta compares the current structured diagnostic inventory with the
previous run of the same supported command in the same session.

Enable it explicitly:

```bash
export TOKEN_SAVER_DELTA=1
```

Delta currently recognizes eligible pytest and Ruff output.

Diagnostics are classified as:

- `NEW`: not present in the previous run;
- `CHANGED`: same identity, different summary/detail;
- `UNCHANGED`: same diagnostic and detail;
- `RESOLVED`: previously present and absent from the current run.

Example:

```text
[token-saver delta: pytest]
CHANGED tests/test_auth.py::test_refresh — AssertionError: expected 200, got 401
source tests/test_auth.py:37::test_refresh
related src/auth/session.py [imports], src/auth/token.py [calls]

UNCHANGED tests/test_cookie.py::test_invalid_cookie — AssertionError

RESOLVED tests/test_login.py::test_expired_session — AssertionError
```

### Repository-graph enrichment

For new or changed diagnostics, Token Saver uses its existing repository index
to map a diagnostic back to the containing source symbol when possible. It can
then attach nearby import/call/dependency relationships.

This is the main difference between Delta and simple repeated-log deduplication:
the compact diagnostic can point the agent toward the source that is most likely
to matter next.

The graph hint is best-effort. If indexing or mapping fails, Delta keeps the
diagnostic classification without inventing a source relationship.

### Session state and privacy

Delta stores only a bounded structured diagnostic inventory in Token Saver's
existing local session state. It does not persist raw command output as part of
the Delta feature.

When Token Saver replaces a large Bash result, it preserves two compatible
recovery paths. The legacy paged-output store remains available for explicit
range retrieval, and v1.13 also stores the exact stdout in the universal
content-addressed recovery store when capacity permits, emitting a `tsr_...`
handle recoverable through CLI `recover` or MCP `recover_context`. If the
universal recovery store cannot accept the original, that additional lossy
replacement path fails closed rather than creating a dangling handle.

### When Delta replaces output

Delta is deliberately conservative:

- it is disabled by default;
- it requires a session identifier;
- it only handles supported diagnostic families;
- first observations establish a baseline rather than claiming a delta;
- a rendered delta replaces the normal compressed fallback only when it is
  smaller.

Short clean reruns still advance Delta state so previously failing diagnostics
can become `RESOLVED`.

## 5. Claude Code hook behavior

With Token Saver installed, the relevant flow is:

```text
Bash command
    ↓
PostToolUse
    ↓
failure-aware processor registry
    ↓
critical-line recovery
    ↓
ratio gate
    ↓
optional Delta comparison
    ↓
recoverable compressed result
```

Source reads use a separate pre-execution guard:

```text
large Read / lone cat of large source
    ↓
PreToolUse guard
    ↓
deny full dump
    ↓
structural outline + exact line ranges
    ↓
bounded follow-up Read
```

The source guard and output processors are intentionally separate: editing tools
need exact source bytes, while terminal output can often be reduced safely.

## 6. Configuration

Project defaults now live in the nearest `.token-saver.toml`; environment
variables remain higher-priority overrides. See the canonical
[configuration reference](docs/CONFIGURATION.md) for discovery, precedence,
host-managed files, and all hook settings.

| Variable | Default | Purpose |
|---|---:|---|
| `TOKEN_SAVER_DELTA` | `0` | Enable graph-aware repeated-diagnostic Delta |
| `TOKEN_SAVER_MIN_LINES` | `40` | Minimum Bash stdout lines considered for filtering |
| `TOKEN_SAVER_MAX_LINES` | adaptive | Target size for generic output filtering |
| `TOKEN_SAVER_KEEP_TAIL` | `15` | Tail lines preserved by generic filtering |
| `TOKEN_SAVER_STATE_DIR` | `~/.claude/token-saver` | Local state, indexes, legacy paged output, and universal recovery storage |
| `TOKEN_SAVER_DISABLED` | unset | Set to a truthy value to disable hook behavior |

## 7. Extension boundary

The registry remains intentionally conservative in 1.5.0. The goal is not to duplicate every
possible CLI parser immediately.

A processor supplies:

```python
name: str
priority: int
handles_failure: bool

def matches(command: str) -> bool: ...

def compress(
    command: str,
    text: str,
    *,
    failed: bool,
    max_lines: int,
    keep_tail: int,
) -> str: ...
```

The shared registry then applies failure routing, critical-line recovery, and the
final ratio gate.

Future processors should be added based on observed high-volume agent commands
and accompanied by output-quality fixtures, especially failure fixtures.

## 8. Validation boundaries

The output subsystem has unit and integration coverage across the supported
routing, failure, recovery, replay, and Delta paths. The frozen external
retrieval holdouts validate a different property: source selection and exact
symbol identity.

Neither a high compression percentage nor a passing output contract by itself
proves lower end-to-end agent cost. Token Saver's broader benchmark policy
continues to treat cost per successful independently-verified task as the
stronger product metric.

See also:

- [README.md](README.md) for installation and overall architecture;
- [VALIDATION.md](VALIDATION.md) for frozen holdout evidence and limitations;
- [BENCHMARKING.md](BENCHMARKING.md) for paired agent-cost methodology;
- [CHANGELOG.md](CHANGELOG.md) for release history.
