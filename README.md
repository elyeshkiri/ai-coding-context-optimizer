# Token Saver 0.6.0

Tools for reducing unnecessary context in Claude Code: source outlines, bounded
reads, recoverable command-output filtering, context audits, and transcript analysis.

**This release does not claim a measured percentage reduction in task cost.**
Smaller tool results are not proof of cheaper successful tasks. The previous
release's historical percentages and “absolute savings ceiling” were not supported
by reproducible evidence in this package and have been removed.

## Install or upgrade

Requires Python 3.10+. JS/TS parsing uses Tree-sitter and the JavaScript/TypeScript
grammar packages, installed automatically by pip.

```bash
python -m pip install .
token-saver install /path/to/project --templates
```

Run `install` again when upgrading: it refreshes this package's hooks, includes
compaction resets, and removes the obsolete Stop usage hook. Unrelated settings
and hooks are preserved, including hooks sharing a matcher with Token Saver.
Invalid JSON settings are rejected instead of overwritten. Do not install the
same hooks at both project and user scope; that runs each hook twice.

For user-wide installation:

```bash
token-saver install . --user
```

The `token-saver` executable must be on the PATH visible to Claude Code.

## Hook compatibility and validation

The Bash filter emits `hookSpecificOutput.updatedToolOutput` with a structured
Bash result, preserving `stderr`, `interrupted`, `isImage`, and additional fields.
It never uses the unsupported `updatedOutput` field from 0.5.4.

This requires a Claude Code release supporting `updatedToolOutput` for built-in
tools. Older hosts may ignore the field. Use the live validation procedure in
[BENCHMARKING.md](BENCHMARKING.md) before assuming automatic filtering works on
your installed host. No precise minimum version is asserted without verification.

The bundled contract tests use documented payload shapes and real subprocess
invocations of the hook; **they do not constitute a live Claude Code test**.
A live Claude Code session and paid model calls were not available in the repair
environment. No real-task savings benchmark has been run for this release.

Reference: [Claude Code hooks](https://code.claude.com/docs/en/hooks#posttooluse-decision-control).

## What happens automatically

- **PreToolUse / Read:** source files over 220 lines require a bounded window.
  `offset: 1` alone, negative limits, and oversized limits no longer bypass the
  guard. The denial includes a capped outline; an explicit permitted range
  returns the original source bytes needed for editing.
- **PostToolUse / Bash:** sufficiently large successful text output is shortened
  only if the replacement, including its recovery note, saves an estimated 50+
  tokens and is smaller in bytes. Stderr is preserved. Interrupted, image, or
  unsupported structured responses pass through unchanged.
- **Diagnostics:** outputs containing failure indicators pass through intact.
  Pytest's complete failure block and summary can be retained while collection
  chatter is removed. This conservative choice can reduce compression but avoids
  losing test names, stack frames, diffs, and source excerpts.
- **Recovery:** before replacing output, the original structured result is saved
  locally. A retrieval command is included. If saving fails, the hook leaves the
  original output in place. It never asks the model to rerun the command.
- **Read state:** only verified full-file results are recorded. State is isolated
  by project and session ID, cleared after compaction, and updated under a lock
  with unique temporary files and atomic replacement.
- **UserPromptSubmit:** after a manual `sessions` or `policy` analysis identifies
  candidate prefix recreation, an explicit new-task phrase can trigger a
  user-visible suggestion. It does not clear history or control cache lifetime.

Duplicate-read blocking is off by default. The guard is a context-budget aid,
not a security boundary: it does not intercept source access through Bash.

## Recover omitted output

The note on a filtered result includes its unique ID:

```bash
token-saver output OUTPUT_ID --stream stdout --offset 1 --limit 80
token-saver output OUTPUT_ID --stream stderr --offset 1 --limit 80
```

Offsets are one-based; limits are 1–2000 lines. Results are stored under
`~/.claude/token-saver/outputs` (or `TOKEN_SAVER_STATE_DIR/outputs`). Files use
owner-only permissions on POSIX. Originals may contain sensitive command output;
keep them local. They are retained until explicitly pruned:

```bash
token-saver outputs-prune --days 7
```

Standalone `filter` also preserves shortened originals and emits a recovery note.
Pipelines should use their shell's `pipefail` if the original command's exit
status must propagate.

## Source navigation

```bash
token-saver outline src/service.ts
token-saver snippet src/service.ts Service.fetchUser
token-saver map src --max-tokens 4000 -o CODEMAP.md
token-saver map src --check-stale
```

Python uses `ast`. JavaScript, JSX, TypeScript and TSX use Tree-sitter for symbol
boundaries and outlines. Arrow functions, class methods, nested symbols and
qualified names are supported. Ambiguous names require qualification. Symbols
are not silently cut at 120 lines; snippets preserve exact source bytes within
the symbol span. Syntax errors in JS/TS cause snippet extraction to fail with an
explicit message; outlines preserve source rather than guessing structure.

Other languages retain approximate pattern-based extraction, explicitly labeled
in snippet output. Vue single-file components are not parsed as JS/TS files.

Maps compete with targeted search: generate a scoped, capped map only when it
helps navigation. The existing freshness check uses modification times; it is a
convenience check, not a content-addressed guarantee. A regenerated map should be
used after renames/deletions or timestamp-preserving source changes.

## Measurement, not invented savings

```bash
token-saver sessions /path/to/project
token-saver sessions --all-projects
token-saver policy /path/to/project
token-saver audit /path/to/project
token-saver check /path/to/project
```

The reports distinguish:

| Output | Meaning |
|---|---|
| Recorded API usage | Token counters from transcript usage records, deduplicated per response; later streaming totals are retained |
| Estimated tool-result size | One-copy offline estimate, not a billing allocation |
| Initial cache observation | First observed prefix in a session/context epoch; never labeled churn |
| Prefix growth | Cache reads cover the previous observed prefix and new tokens are appended |
| Suspected recreation | Heuristic overlap with a prior observed prefix; not proof of expiry or avoidable waste |
| Repeated reads | Same path/content within one session and compaction epoch; may still be necessary |
| Outline reduction | Hypothetical one-shot size change, excluding follow-up reads, retries and quality effects |

A smaller result can reduce later cache reads and writes as well as its initial
insertion. Conversely, extra reads or failed work can erase savings. Consequently
no tool-output ratio is an absolute savings ceiling. Idle gaps use a configurable
assumed TTL; they do not establish actual cache expiry. `/clear` is suggested only
for unrelated tasks, not as a universal cost optimization.

Images are dimension-based estimates. Unknown/corrupt images are reported as
unknown and excluded from token estimates, never charged as base64 text size.
These estimates are not model-specific image billing.

## Model-specific cost

```bash
token-saver sessions /path/to/project --rates rates.json
token-saver benchmark runs.json --rates rates.json
```

Supply USD-per-million rates keyed by exact transcript model ID. All five fields
are required: `input`, `cache_write_5m`, `cache_write_1h`, `cache_read`, `output`.
When a transcript omits the cache-write TTL breakdown, costs remain incomplete
unless you explicitly supply `cache_write_unknown`. Do not guess that rate: use
known run configuration or leave the result incomplete. Missing model prices
never silently use another model's prices. These calculations are at supplied
rates, not a provider invoice or subscription quota estimate.

See [BENCHMARKING.md](BENCHMARKING.md) for the paired-run format and protocol.
Current pricing must come from your provider configuration; no frozen price list
is presented as current. [Anthropic caching reference](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

## Other commands

```bash
token-saver estimate -f CLAUDE.md
token-saver estimate -f CLAUDE.md --exact --model YOUR_MODEL_ID
token-saver audit . --probe-mcp
token-saver budget .
token-saver status .
token-saver mcp-prune .              # inspect before applying
token-saver filter --command 'npm test' < test-output.txt
```

Offline counts are character-ratio heuristics, not a guaranteed error bound.
`--exact` requires `pip install '.[exact]'` plus Anthropic credentials; it counts
the supplied text as a standalone API message, not your entire live session.
Context audits estimate discovered instructions and schemas; they are not an
instrumentation trace of everything a particular Claude Code version loaded.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `TOKEN_SAVER_GUARD` | `1` | Set to `0` to disable the Read guard |
| `TOKEN_SAVER_READ_MAX_LINES` | `220` | Large-source threshold and maximum guarded range size |
| `TOKEN_SAVER_REREAD` | `0` | Optional duplicate full-read denial |
| `TOKEN_SAVER_ALLOW` | empty | Colon-separated source allowlist globs |
| `TOKEN_SAVER_MIN_LINES` | `40` | Minimum Bash stdout lines considered |
| `TOKEN_SAVER_MAX_LINES` | adaptive | Approximate filter line target; diagnostics can exceed it |
| `TOKEN_SAVER_KEEP_TAIL` | `15` | Bash filter tail target |
| `TOKEN_SAVER_CACHE_TTL_MIN` | `5` | Assumed TTL for advisory gap classification only |
| `TOKEN_SAVER_STATE_DIR` | `~/.claude/token-saver` | Local state and saved output directory |

## Development

```bash
python -m pip install '.[dev]'
python -m pytest -q
```

See [CHANGELOG.md](CHANGELOG.md) for the repair list and validation limits.
