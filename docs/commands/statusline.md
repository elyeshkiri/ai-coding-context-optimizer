# `acco statusline`

Render a compact one-line operational efficiency status.

```bash
acco statusline .
acco statusline . --days 7
acco statusline . --json
```

Example:

```text
ACCO | saved~4.2Kt | waste 1 | prefix 86% | files 3 | HEALTHY
```

The status is built from local ACCO telemetry: estimated before/after
tool-context reductions, waste signals, stable-prefix observations, and the
current structured working set. It is intentionally fast and content-free.

The displayed saved-token value is an operational estimate, not an API invoice
or end-to-end cost-per-success claim.
