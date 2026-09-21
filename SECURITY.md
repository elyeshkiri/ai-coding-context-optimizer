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

## Oversized-prompt ingress state

Prompt ingress optimization is **disabled by default** because its safety model
requires storing the exact blocked prompt locally so omitted ranges remain
recoverable. When enabled and the threshold fires, Token Saver writes:

- the exact original prompt;
- a SHA-256 integrity digest;
- a bounded exact-excerpt packet and line-range metadata.

State is project-scoped under the private Token Saver state directory, written
with private permissions, and bounded to the newest 40 staged prompts. It is not
uploaded to Token Saver infrastructure. Unlike output-policy telemetry and
session continuity, this store intentionally contains user prompt content.
Treat it as sensitive, relocate `TOKEN_SAVER_STATE_DIR` when appropriate, and
do not enable ingress staging for material that must not be persisted locally.

The hook blocks the oversized prompt before Claude processes it. Token Saver
does not send a lossy substitute automatically and never silently truncates a
failed compression attempt.

## Smart Tool Proxy model boundary

Smart Tool Proxy is disabled by default. When enabled with the default
`provider = "ollama"`, Token Saver sends a bounded task hint, structural
outline, and bounded exact candidate source windows to the configured Ollama
HTTP endpoint. The default endpoint is loopback
`http://127.0.0.1:11434`.

Changing that endpoint to a remote host changes the privacy boundary: the
bounded task/source evidence is then sent to that host. Configure remote
endpoints only when that provider is approved to receive the repository
material.

The selector is not trusted as source truth. Returned JSON can only nominate
line ranges; Token Saver validates/clamps those ranges and re-reads the delivered
code from the original file. Model-generated orientation is labeled
non-authoritative. If the selector fails, deterministic local range selection is
used. Bounded Reads are never proxied.

The latest user task may be read transiently from the local Claude transcript
tail to orient selection. Token Saver does not persist that prompt text in Smart
Tool Proxy state. Operational savings telemetry stores only token counts and the
selector label, not the source excerpts or task text.

## Smart Tool Proxy model boundary

Smart Tool Proxy is disabled by default. When enabled with the default `provider = "ollama"`, Token Saver sends a bounded task hint, structural outline, and bounded exact candidate source windows to the configured Ollama HTTP endpoint. The default endpoint is loopback `http://127.0.0.1:11434`.

Changing that endpoint to a remote host changes the privacy boundary: the bounded task/source evidence is then sent to that host. Configure remote endpoints only when that provider is approved to receive the repository material.

The selector is not trusted as source truth. Returned JSON can only nominate line ranges; Token Saver validates/clamps those ranges and re-reads the delivered code from the original file. No model-generated selector prose is forwarded to Claude. If the selector fails, deterministic local range selection is used. Bounded Reads are never proxied.

The latest user task may be read transiently from the local Claude transcript tail to orient selection. Token Saver does not persist that prompt text in Smart Tool Proxy state. Operational savings telemetry stores only token counts and the selector label, not the source excerpts or task text.
## Semantic vector state

Opt-in semantic retrieval reads the same repository files already admitted by
the structural index's path-safety policy. Its private project-scoped SQLite
database stores:

- repository-relative file paths and indexed content digests;
- chunk start/end lines and optional symbol labels;
- normalized embedding vectors;
- hashes and vectors for exact repeated queries;
- optional HNSW label mappings.

It deliberately does **not** persist source text inside the vector database.
The optional HNSW sidecar contains derived vector-index data only. Both live
under `TOKEN_SAVER_STATE_DIR`; treat that directory as private because vectors
and filenames are still derived from project contents.

Token Saver loads the configured SentenceTransformer with
`local_files_only=True`. Model downloading is an explicit user action outside
normal retrieval. The current feature does not send source chunks or query text
to Token Saver infrastructure.

A changed file is re-hashed before embedding and must still match the structural
repository-index digest. A mismatch fails the semantic refresh rather than
storing vectors under stale evidence identity.

When `TOKEN_SAVER_SEMANTIC_MODEL_REVISION` is set, that immutable revision is
part of the local vector-store and query-vector cache identity. This prevents a
pinned evaluation or deployment from silently reusing embeddings produced by
different weights under the same model name.

## Retrieval cache state

Persistent retrieval cache entries contain completed bounded context packs and
ranking metadata, so they may include source excerpts that were selected for an
agent. Cache identity incorporates indexed source digests and index version;
changed repository evidence gets a new key rather than reusing stale context.
The cache is local/private and bounded by `retrieval.cache_max_entries`.
Disable it with `TOKEN_SAVER_RETRIEVAL_CACHE=0` when local persistence is not
appropriate.

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

## Blind grading data boundary

`blind-grade` is an explicit evaluation action, not background telemetry. It
sends the configured grader the frozen task prompt and the two agents' **final
response texts** under anonymized A/B labels. It does not send condition names,
repository patches, hidden verifier output, billing data, or full transcripts.
The bundled Claude grader runs in an empty pinned container with shell,
filesystem, and web tools denied.

For private/custom benchmark prompts, treat the configured grader as an external
processor of that prompt and final-response text. Do not enable a remote grader
for material you are not permitted to send to that provider.

## Frozen session-holdout evidence

The optional `session-holdout` workflow is an explicit paid evaluation action,
not normal runtime telemetry. It runs frozen public SWE-bench task prompts
through the configured Claude model and persists benchmark artifacts such as
transcripts, patches, verifier logs, blind-quality scores, usage counters, and
session-efficiency event counts.

The dedicated GitHub workflow uploads per-task evidence for 30 days and merged
aggregate evidence for 90 days. Repository/API credentials are supplied to
isolated runner containers through GitHub Actions secrets; they are not written
into the frozen suite.

The benchmark blind grader receives the frozen task prompt plus anonymized final
A/B response text under the existing blind-grading boundary. Session-efficiency
outcome metrics are derived from raw transcripts locally; Token Saver's event
ledger is used only as feature-activation evidence.

Do not reuse the public frozen workflow for private task prompts or repositories
unless the configured model/grader provider and artifact-retention policy are
acceptable for that material.

## Session-efficiency state

The 1.7 continuity layer uses a separate private project-scoped snapshot and
bounded event ledger under the Token Saver state directory.

The continuity snapshot may contain:

- an opaque session fingerprint;
- coarse task class;
- repository-relative/absolute working file paths;
- bounded command labels after best-effort credential redaction plus opaque
  command/output fingerprints;
- validation kind/status, failure fingerprints, and counters.

It deliberately does **not** persist raw user prompts, assistant responses, or
raw tool output. Exact output fingerprints are hashes, not copied output.
Compressed Bash originals remain in the existing saved-output store described
above because recoverability is a separate explicit feature.

The efficiency event ledger stores feature names, counts, opaque session
fingerprints, and estimated before/after token savings. It does not contain the
removed command output. Files are written with private permissions and bounded
retention.

Command-label redaction covers common `key=value`, `--token value`,
authorization-header, and URL-credential forms, but it is defense in depth
rather than a secret-management guarantee. Do not pass secrets on command lines
when avoidable, and treat the local state directory as potentially sensitive.

## Durable project-knowledge state

`remember` / `remember_finding` persist the exact claim, evidence,
applicability text, confidence label, file/symbol anchors, and source digests
that the caller explicitly submits. This state is local, project-scoped,
private-permission, and bounded, but unlike continuity state it **can contain
human/model-authored prose**. Do not place credentials, production secrets,
private customer data, or other material you would not store on the local
machine into a finding.

Automatic knowledge-assisted read avoidance never harvests conversation text.
It reads only explicit stored findings, requires current verified anchors, and
does not send knowledge to Token Saver infrastructure. The frozen paid
knowledge-efficiency workflow has the same external model/grader and artifact
retention considerations as the session holdout below; do not reuse the public
workflow for private prompts/repositories unless those boundaries are acceptable.

## Session state

Token Saver keeps bounded local state for features such as remembered reads,
diagnostic Delta, the active automatic output-policy signature, and bounded
output-budget telemetry. The output policy stores only resolved
task/mode/budget metadata; it does not persist user prompt text. Telemetry stores
policy metadata, opaque session fingerprints, model identifiers, and transcript
usage counters. It does **not** store prompt text, assistant text, tool payloads,
or copied transcript content. The telemetry JSONL file is project-scoped,
created with private permissions, and compacted after it grows beyond 4 MiB,
keeping the newest 2,000 records. The default state area is under the user's Claude directory;
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
