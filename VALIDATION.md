# Validation for 1.0.0

Release validation executed locally on Ubuntu 24.04 with Python 3.12. The
repository CI matrix targets Python 3.10, Python 3.12, and Python 3.13:

- Full test suite: **270 passed** on Python 3.12 in the release environment.
- Package build and isolated installation succeeded from `pyproject.toml` as token-saver 1.0.0.
- v0.9 coverage includes symbol locations/signatures/calls, targeted symbol
  windows, impact traversal, feedback bounds, selector evaluation, sensitive
  paths, secret redaction, symlink containment, and MCP tool dispatch.
- The expanded 25-task deterministic selector benchmark at a 6,000-token cap
  measured 96% mean relevant-file recall, 100% mean relevant-symbol recall, and
  92.94% mean estimated context reduction. These are repository-specific
  selection metrics, not proof of end-to-end agent task success.
- Regression coverage includes incremental index reuse, dependency/symbol graph
  expansion, near-duplicate suppression, task-session continuity, optional
  embedding failure behavior, task-aware relevance ranking, hard context-pack
  token caps, exact line-numbered source windows, changed-file boosts, top-level
  command dispatch, repetitive successful-log compression, JSON compaction, and
  failure preservation.
- Existing coverage still exercises documented structured Bash output, subprocess
  hook transport, saved-output recovery and permissions, fail-open disk errors,
  diagnostic preservation, cache/compaction accounting, session isolation,
  concurrent state writes, bounded-read bypasses, settings preservation, JS/TS
  syntax and ambiguity, model/TTL pricing, and paired benchmark quality/cost
  evaluation.

The local Python 3.12 release run completed **270 passed**. GitHub CI
continues to run the suite on Python 3.10, 3.12, and 3.13 for the pushed commit.

Observed dependency versions in that run:

- pytest 9.1.1
- tree-sitter 0.25.2
- tree-sitter-javascript 0.25.0
- tree-sitter-typescript 0.23.2

Not executed:

- A live Claude Code session accepting the replacement on its model input path.
- Real paired coding tasks with paid API usage and independently checked outcomes.
- Windows execution of the locking branch.
- A production benchmark proving that task-aware packs reduce total task cost for
  a representative workload; the pack tests prove ranking/budget invariants, not
  end-to-end model quality.

No real-world token savings percentage is claimed. Synthetic and unit tests
exercise mechanics and validation, not product efficacy. See BENCHMARKING.md for
live integration and paired-task measurement procedures.
