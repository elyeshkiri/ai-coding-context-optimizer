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
