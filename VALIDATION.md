# Validation for 0.6.0

Executed in the Linux repair workspace with Python 3.12:

- Full test suite: **231 passed in 2.87s**.
- Original suite: 194 cases; regression additions: 37 cases.
- Regression coverage includes documented structured Bash output, subprocess hook
  transport, saved-output recovery and permissions, fail-open disk errors,
  diagnostic preservation, first-write/growth accounting, compaction boundaries,
  streamed usage deduplication, session isolation, concurrent process writes,
  range bypasses, settings preservation, JS/TS syntax and ambiguity, model/TTL
  pricing, and paired benchmark quality/cost evaluation.
- Built `token_saver-0.6.0-py3-none-any.whl` successfully.
- Installed that wheel into a separate directory; verified version import,
  TypeScript arrow-function extraction, and benchmark CLI error handling.

Test dependency versions:

- pytest 9.1.1
- tree-sitter 0.25.2
- tree-sitter-javascript 0.25.0
- tree-sitter-typescript 0.23.2

Not executed:

- A live Claude Code session accepting the replacement on its model input path.
- Real paired coding tasks with paid API usage and independent outcomes.
- Windows execution of the locking branch or other Python versions.

No real-world token savings percentage is claimed. Synthetic benchmark tests
exercise arithmetic and validation, not product efficacy. See BENCHMARKING.md
for the remaining live integration and measurement procedures.
