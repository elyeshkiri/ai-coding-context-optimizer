# `acco output-telemetry`

Report locally captured generation-budget telemetry for the current project.

## Synopsis

```bash
acco output-telemetry [path] [--json] [--records] [--limit N]
```

## Arguments and options

- `path` — project root; default current directory.
- `--json` — emit the complete report as JSON.
- `--records` — include recent raw telemetry metadata records in the report.
- `--limit N` — maximum raw records included with `--records`; default `20`.

Claude Code telemetry is captured automatically when `output.telemetry = true`.
The prompt hook stores a transcript byte checkpoint and active policy metadata;
`Stop` or `StopFailure` reads only the transcript bytes appended during that
turn and records usage counters.

Telemetry never copies prompt text, assistant text, tool payloads, or transcript
content. A `Stop` is only evidence that a model turn completed. It is **not**
treated as proof that the coding task succeeded or that response quality was
preserved.

## Exit codes

`0` success; argparse usage errors exit `2`.

## Output contract

The aggregate report contains total/measured/completed/API-failed turns, input
and cache usage, output tokens, model calls, selected-budget statistics,
task/mode groups, and observational underuse/overrun signals. See
[Machine-readable contracts](../JSON_OUTPUTS.md#output-telemetry-json).

## Authoritative runtime help

Run `acco output-telemetry --help` for argparse's exact usage text for
the installed version.
