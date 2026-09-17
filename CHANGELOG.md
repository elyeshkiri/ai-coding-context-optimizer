# 0.9.0

- Upgraded the content-addressed index to store symbol ranges, signatures,
  parent classes, and per-symbol calls with automatic v1 cache invalidation.
- Added exact symbol-body context packing through `--target-symbol`, structured
  JSON output, selected-symbol metadata, and high-confidence secret redaction.
- Added `token-saver impact` for explainable file/symbol blast-radius analysis
  across imports, callers, and related tests.
- Added bounded local relevance feedback and a ground-truth context evaluator
  measuring file recall, symbol recall, and token reduction.
- Added a 25-task repository benchmark manifest and a dependency-free stdio MCP
  server exposing context, symbol lookup, impact, and feedback tools.
- Hardened repository scanning against sensitive paths, generated/vendor trees,
  escaping symlinks, and oversized context exposure.
- Full suite: 259 tests pass in the release environment.

# 0.8.0

- Added an incremental, content-addressed repository index. It extracts symbols,
  imports, calls, and normalized identifiers and reuses unchanged records.
- Added dependency and symbol-call graph expansion with configurable hop depth
  and distance-decayed ranking boosts.
- Added identifier-based near-duplicate suppression before context allocation.
- Added opt-in session working-set memory. Previous files are boosted only for
  follow-up queries sharing task terms, reducing stale-context carryover.
- Added optional local sentence-transformer reranking through the `embeddings`
  extra. Default behavior remains deterministic and dependency-free.
- Added atomic persistence for indexes and working sets, CLI controls, ranking
  explanations, and regression tests for every new subsystem.
- Full suite: 250 tests pass on Python 3.12 in the release environment.

# 0.7.0

- Added task-aware context packing with `token-saver pack` and the standalone
  `token-saver-pack` entry point.
- Added dependency-free BM25-style source ranking with stronger path and symbol
  weights, Git working-tree/staged-file boosts, and structural-priority fallback.
- Context packs combine compact outlines with exact line-numbered source windows
  around high-signal task matches instead of summarizing editable code.
- Added hard estimated-token caps, file-count/window controls, Git-ignore support,
  ranking explanations, and output-to-file support.
- Added conservative compression of consecutive duplicate lines in successful
  command output while keeping failures and diagnostics untouched.
- Added CI on Python 3.10 and 3.12 and regression coverage for relevance ranking,
  budget enforcement, exact source windows, dispatcher compatibility, JSON
  compaction, and failure preservation.
- Kept all 0.6 lifecycle, audit, recovery, source-read, and benchmark behavior;
  the new top-level dispatcher isolates `pack` from the mature legacy CLI.

Token Saver still does not claim a universal end-to-end savings percentage.
Task success and paired-run measurements remain the standard for savings claims.

# 0.6.0

- Corrected Bash replacement to the documented structured `updatedToolOutput`
  contract. Unsupported/image/interrupted outputs pass through.
- Preserved stderr and failure diagnostics. Shortened outputs are saved privately
  and recoverable by ID/range, without re-executing commands. Saving failures
  leave original output visible. Added `output` and `outputs-prune` commands.
- Scoped read state by project and session, with locked read-modify-write
  transactions, unique temporary files and atomic replacement. Compaction resets
  are installed. Only verified full-read contents are recorded.
- Removed the Stop hook's reliance on undocumented usage fields. Lifecycle advice
  remains based on explicit transcript analysis, not invented live usage.
- Tightened Read ranges: offsets alone and oversized/invalid limits no longer
  bypass the context budget. Relative paths resolve against the hook project.
- Replaced JS/TS snippet boundaries with Tree-sitter, added qualified names and
  ambiguity errors, removed silent 120-line truncation, and improved outlines.
- Excluded first cache observations and compaction epochs from suspected
  recreation. Reported only suspected overlapping prefixes, not all new tokens.
- Scoped repeated-read analysis by session and compaction epoch; stopped
  describing every repeat as waste. Preserved final streaming usage totals.
- Added explicit model/TTL pricing, with incomplete-cost results for unknown
  prices or TTLs. Unknown image sizes no longer use base64 length as token cost.
- Added paired-run benchmark evaluation including failed-attempt costs and
  quality outcomes. Removed historical savings percentages and absolute-ceiling
  claims without reproducible supporting data.
- Made settings updates atomic and refused malformed settings; preserved
  unrelated hooks sharing a matcher. Updated templates and upgrade guidance.

Validation: regression tests cover these fixes and subprocess hook transport.
See VALIDATION.md for executed results. A live Claude Code integration run and
real-task savings benchmark remain unexecuted; BENCHMARKING.md supplies the
protocol. The Windows locking branch is implemented but was not run on Windows.
