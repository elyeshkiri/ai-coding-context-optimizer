---
name: token-budget
description: Session hygiene when context is fat or the user starts a new task. Do not load unless asked or a new task starts.
---

# Token budget (on demand)

- New task → `/clear`. Same task, history noisy → `/compact Keep: plan, files, open errors`.
- Cache TTL depends on configuration. An idle gap alone does not prove wasted tokens.
- Never clear necessary history merely to chase a cache heuristic.
- Read source with offset/limit after an outline.
- Never paste raw test or install logs.
- For final responses: result first; no conversational preamble, task restatement, tool narration, recap, or closing filler.
- Preserve required code, diagnostics, safety caveats, and explicit user output formats even when they exceed the preferred budget.
- When a cause is not proven, label it as a hypothesis instead of spending tokens on a confident guess.
