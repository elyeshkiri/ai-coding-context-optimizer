# Worked end-to-end example: fix a real bug with measured context

This walkthrough connects installation, host verification, one concrete coding
bug, Token Saver's hook behavior, independent verification, transcript
measurement, and the limits of the resulting evidence. It uses the checked-in
`examples/large_output_demo` so every source file and deterministic token
figure is reproducible from this repository.

## The bug

The demo contains a small `shop` application. Its bulk-discount rule is wrong
at the exact threshold: an order of **10 units** receives no discount because
the implementation uses `>` where the intended rule is `>=`.

The agent task is intentionally ordinary:

```text
make check is red, fix it, re-run make check
```

The independent verifier is the demo's hidden regression test. The agent's own
"done" message is never used as the success label.

## 1. Install and configure the project

From a clean environment:

```bash
python -m pip install --upgrade claude-token-saver
cd /path/to/token-saver
token-saver setup . --host claude
token-saver doctor . --require-ready
```

For a deeper Claude transport check:

```bash
token-saver host-check . --require-ready
```

`doctor` proves local CLI/config/index readiness. `host-check` additionally
probes the hook transport. Neither command by itself proves a coding task will
be cheaper or successful.

## 2. Reproduce the two context-pressure points

The demo intentionally exposes two common sources of unnecessary context.

### Verbose failing command

Running the demo's `make check` produces 631 lines with one failure.

The checked-in deterministic fixture measures:

| Path | Without Token Saver | With Token Saver |
|---|---:|---:|
| `make check` output | 14,214 estimated tokens | 264 estimated tokens |
| whole `shop/catalog.py` read | 6,240 estimated tokens | 856-token outline + line ranges |

These are deterministic context-size measurements guarded by
`tests/test_large_output_example.py`; no model is involved.

The output filter preserves the failing test, assertion, and summary rather than
keeping all 631 lines.

### Whole-file source read

`shop/catalog.py` is 739 lines. An unbounded Read (and a lone
`cat shop/catalog.py`) is redirected to a structural outline with line ranges,
so the agent can request the relevant body instead of paying for the full file.

That distinction matters: Token Saver is not "summarize everything." It tries to
preserve exact evidence and make follow-up retrieval explicit.

## 3. Run the paired agent demo

The repository ships a paid paired-run driver:

```bash
python examples/large_output_demo/run_demo.py --trials 3
```

It creates a throwaway Git repository, runs the same frozen task in baseline and
Token Saver arms, independently verifies each result with hidden tests, and
prices the recorded Claude transcripts.

The checked-in measurements are:

| Model / prompt | Baseline (3 runs) | Token Saver (3 runs) | Relative cost |
|---|---:|---:|---:|
| Sonnet 5 — "fix the bulk-discount bug, run the tests" | $0.1718 | $0.1652 | +3.9% cheaper |
| Sonnet 5 — `make check` prompt, before Bash `cat` guard | $0.1667 | $0.2427 | **45.6% more expensive** |
| Sonnet 5 — same prompt, after Bash `cat` guard | $0.2008 | $0.1841 | +8.4% cheaper |
| Haiku 4.5 — shipped `make check` prompt | $0.2298 | $0.1653 | +28.1% cheaper |

All recorded runs solved the task.

The negative pre-guard row is deliberately retained. In two of three enabled
runs the agent bypassed the Read guard with `cat`, paid for the whole source
file, and made Token Saver more expensive. That failure led to the current Bash
`cat` guard.

Three trials per arm are a demonstration, **not** a statistically publishable
benchmark. The between-run spread is large enough that none of these percentages
should be presented as a universal savings rate.

## 4. Inspect what happened in a real Claude session

After using Claude Code in the project:

```bash
token-saver sessions .
```

The report separates recorded API token fields from estimated tool-result size
and shows:

- uncached input and cache reads recorded by Claude;
- estimated tool-result volume by tool;
- largest individual results;
- repeated reads;
- hypothetical outline reduction;
- lifecycle advice derived from the transcript.

For machine-readable health/configuration evidence:

```bash
token-saver doctor . --json
token-saver host-check . --live-evidence /path/to/claude-debug.log --require-live
```

A live-host proof is stronger than a synthetic hook round trip because it shows
the external host accepted `updatedToolOutput`. See
[Benchmarking](../BENCHMARKING.md) for the live-host evidence protocol.

## 5. Verify the coding result independently

A successful agent run is not accepted because the model says the task is done.
The demo runner executes hidden tests after the agent exits.

For broader publishable experiments, the same principle is enforced by
`token-saver experiment`: success comes from independent verifier commands,
and frozen SWE-bench tasks apply hidden regression tests only after the agent
process ends.

## 6. Interpret the result correctly

This walkthrough demonstrates three different claims at three different
strengths:

1. **Deterministic mechanism:** the checked-in verbose output and whole-file read
   are much smaller after Token Saver's transformations.
2. **Task success in this demo:** every recorded paired run solved this specific
   bug under independent verification.
3. **End-to-end cost effect:** the measured direction varies by model and agent
   behavior, from worse before the `cat` guard to cheaper afterward.

Only the first two are strongly established by this example. The third remains
small-sample evidence. Token Saver therefore does **not** turn this walkthrough
into a universal cost-saving claim.

For the current evidence boundary, read [Validation](../VALIDATION.md). For the
publication protocol and frozen broad experiment, read
[Benchmarking](../BENCHMARKING.md).
