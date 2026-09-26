# `acco guardian`

Inspect the most recent structured pre-compaction checkpoint.

```bash
acco guardian .
acco guardian . --json
```

Claude Code's ACCO integration registers a `PreCompact` hook. The checkpoint
contains bounded task class, working-file, recent-command, failure, and
validation metadata. It intentionally does **not** persist raw prompts,
assistant prose, or raw tool output.

On a later `resume` or `compact` session start, ACCO can restore this
checkpoint as orientation. Repository state remains authoritative and should be
re-verified before stale command results are trusted.
