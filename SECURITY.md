# Security and privacy

Token Saver is designed as a local context-optimization layer. This document
describes what it reads, writes, and deliberately refuses to overwrite.

## Local processing

Core repository indexing, ranking, context packing, hook filtering, output
recovery, and transcript analysis run locally.

Optional external/model integrations can have their own network behavior; use
their documentation and credentials deliberately.

## Repository contents

Token Saver may read source files to build structural/retrieval indexes and
bounded context.

Context rendering applies the project's existing secret-redaction path where
documented, but users should still avoid committing credentials or treating an
AI-agent context layer as a secret-management system.

## Claude transcripts

`token-saver sessions` reads Claude Code transcript files under the local
Claude projects directory.

It does not need to upload those transcripts to Token Saver infrastructure.
The analysis is local.

## Saved command output

When the Claude hook safely replaces a large command result, the original can be
stored locally so it remains recoverable.

Retrieve it with:

```bash
token-saver output <id>
```

Prune old outputs with:

```bash
token-saver outputs-prune --days 7
```

Treat the state/output directory as potentially sensitive because command output
can contain project paths, diagnostics, or application data.

## Session state

Token Saver keeps bounded local state for features such as remembered reads and
diagnostic Delta. The default state area is under the user's Claude directory;
`TOKEN_SAVER_STATE_DIR` can relocate it.

Do not point the state directory at a shared/public location.

## Managed configuration safety

`token-saver setup` preflights selected host files before mutation.

Ownership boundaries:

- Claude: only Token Saver hook commands and `mcpServers.token-saver`;
- Cursor: only `mcpServers.token-saver`;
- Codex: only the marked Token Saver managed block;
- generated Claude skill: removed only if it still matches the generated
  template exactly.

Invalid JSON and unmanaged conflicting Codex sections are refused rather than
overwritten.

## Credentials

Token Saver should not require storing provider API keys in repository config.

Optional exact token counters, embeddings, model runners, or CI publication can
use provider-specific credentials. Keep those in normal secret stores or CI
secrets rather than `.token-saver.toml`.

## Benchmark privacy

Do not use proprietary repositories, private transcripts, or production secrets
in published benchmark artifacts unless you have explicit permission.

The repository's frozen public holdouts use pinned external repositories and
predeclared task definitions so evaluation evidence can be reproduced without
private source.

## Reporting a security issue

Do not publish an exploit or sensitive reproduction data in a public issue.

Use GitHub's private security-reporting mechanism for the repository when
available. If that mechanism is unavailable, contact the repository owner
privately and disclose only the minimum information needed to reproduce the
issue.

Include:

- affected Token Saver version/commit;
- affected command/integration;
- impact;
- reproduction steps using non-sensitive fixtures where possible;
- proposed mitigation if known.
