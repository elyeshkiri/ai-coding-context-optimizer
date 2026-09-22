# Large-output demo: where ACCO can help

A small `shop` project built to trigger ACCO's two savings paths, plus a
runnable paired Claude Code comparison.

| What the agent does | Without ACCO | With ACCO |
|---|---|---|
| Runs `make check` (pytest with `-v`, 631 lines, 1 failure) | 14,214 tokens enter the context | 264 tokens: the failing test, its assertion and the summary are kept |
| Reads the whole 739-line `shop/catalog.py` with the Read tool | 6,240 tokens | 856-token outline plus line ranges (the Read is redirected) |

Those figures are deterministic and checked by `tests/test_large_output_example.py`
(no model involved). The one real bug: ordering exactly 10 units gets no bulk
discount (`>` should be `>=`).

## Run it

```bash
python3 examples/large_output_demo/run_demo.py --trials 3
```

`run_demo.py` creates the project in a throwaway Git repo, runs the same task in a
baseline arm and a ACCO arm through the experiment harness, verifies each
result with hidden tests, and prices the recorded transcripts. It needs the
`claude` CLI logged in and spends real money (about $0.05-0.10 per run at API
rates). Use `--model` / `--rates` for another model.

## What we measured (3 trials per arm, API-equivalent cost, all runs solved)

| Model | Prompt | Baseline (3 runs) | ACCO (3 runs) | ACCO vs baseline |
|---|---|---|---|---|
| Sonnet 5 | "fix the bulk-discount bug, run the tests" | $0.1718 | $0.1652 | +3.9% |
| Sonnet 5 | "`make check` is red, fix it, re-run `make check`" (before the `cat` guard) | $0.1667 | $0.2427 | -45.6% |
| Sonnet 5 | same, after the `cat` guard | $0.2008 | $0.1841 | +8.4% |
| Haiku 4.5 | same `make check` prompt (the shipped demo) | $0.2298 | $0.1653 | +28.1% |

Positive means ACCO was cheaper (cost per solved task; every run solved). Three trials is a demonstration, not a
benchmark, and the spread between runs is as large as some of these gaps.

## How to read it

ACCO only saves what the agent would otherwise have put in the context.

* **A `cat` of the whole file used to slip past the guard.** In the -45.6% row, 2 of
  3 enabled runs read `shop/catalog.py` with `cat` through Bash, which the Read
  guard did not cover, and each paid about $0.04 more. The guard now also denies a
  lone `cat <large source file>` with the same outline. Rerunning the test, the
  agent again tried `cat` in 2 of 3 enabled runs (and in 1 of 3 baseline runs);
  the guard redirected it to a ranged `Read`, and those enabled runs cost $0.066
  against $0.093 for the baseline run that read the file whole. The aggregate
  moved from -45.6% to +8.4% mostly because of which runs chose to `cat`, so read
  the like-for-like cost of one such run, not the total, as the effect.
* **Sonnet 5 mostly avoids the noise on its own.** It found the bug with `Grep`,
  read 20 lines, and piped every test run through `| tail`, so there was nothing
  for the output filter to trim.
* **Haiku 4.5 ran plain `make check`**, so every baseline run took all 631 lines
  into context. The hook trimmed the output in 2 of 3 enabled runs, and all three
  enabled runs were cheaper than every baseline run ($0.045-0.063 vs
  $0.070-0.083).

So expect a real saving when the agent runs a verbose command as-is, and little
when it already truncates output or reads by range.
