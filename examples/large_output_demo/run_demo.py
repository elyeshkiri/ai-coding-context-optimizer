#!/usr/bin/env python3
"""Paired Claude Code run on the large-output demo: baseline vs Token Saver.

Generates the demo project in a throwaway Git repo, then uses the experiment
harness to run the same task in both arms (hooks only in the enabled arm),
verify each result with hidden tests, and price the recorded transcripts.

    python3 examples/large_output_demo/run_demo.py --trials 3

Needs the ``claude`` CLI logged in (or ANTHROPIC_API_KEY set) and real spend:
about $0.05-0.10 per run at API rates, so the default 3 trials is well under $1.
This is a demonstration on one task, not a benchmark.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from make_project import HIDDEN_TEST, PROMPT, make_project  # noqa: E402

from token_saver.benchmark import evaluate  # noqa: E402
from token_saver.experiment import prompt_sha256, run_experiment  # noqa: E402

DEFAULT_RATES = Path(__file__).parent / "rates.json"
TOOLS = (
    "Read,Edit,Write,Glob,Grep,Bash(python3:*),Bash(python:*),Bash(pytest:*),Bash(make:*),"
    "Bash(git:*),Bash(ls:*),Bash(cat:*),Bash(grep:*),Bash(sed:*),Bash(head:*),Bash(tail:*)"
)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], text=True, capture_output=True, check=True,
    )
    return proc.stdout.strip()


def _new_file_patch(path: str, text: str) -> str:
    lines = text.splitlines()
    body = "".join(f"+{line}\n" for line in lines)
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n"
        f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n{body}"
    )


def build_suite(work: Path, *, model: str, trials: int) -> Path:
    repo = make_project(work / "project")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "demo@example.test")
    _git(repo, "config", "user.name", "Demo")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "large-output demo project")
    revision = _git(repo, "rev-parse", "HEAD")
    suite = {
        "suite_version": 1,
        "protocol": {"task_definitions_frozen": False},
        "design": {"trials_per_task": trials, "condition_order_seed": 1729},
        "repositories": {"demo": {"path": str(repo), "revision": revision}},
        "runner": {
            "command": [
                "claude", "-p", "{prompt}", "--model", "{model}",
                "--permission-mode", "acceptEdits", "--allowedTools", TOOLS,
                "--max-budget-usd", "3", "--output-format", "json",
            ],
            "model": model,
            "transcript_mode": "claude-project",
            "timeout_seconds": 900,
        },
        "tasks": [{
            "id": "bulk-discount-boundary",
            "repository": "demo",
            "revision": revision,
            "prompt": PROMPT,
            "prompt_sha256": prompt_sha256(PROMPT),
            "test_patch": _new_file_patch("tests/test_bulk_hidden.py", HIDDEN_TEST),
            "verifier": [[sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"]],
        }],
    }
    path = work / "suite.json"
    path.write_text(json.dumps(suite, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--model", default="claude-haiku-4-5-20251001",
                        help="exact model id; must have an entry in --rates")
    parser.add_argument("--rates", type=Path, default=DEFAULT_RATES,
                        help="USD per million tokens, keyed by exact model id")
    parser.add_argument("--out", type=Path, default=None,
                        help="directory for suite, transcripts and results (default: temp dir)")
    args = parser.parse_args()

    # Let this run from inside a Claude Code session: children must start clean.
    for name in [k for k in os.environ if k.startswith("CLAUDE") or k == "AI_AGENT"]:
        os.environ.pop(name)

    work = args.out or Path(tempfile.mkdtemp(prefix="token-saver-demo-"))
    work.mkdir(parents=True, exist_ok=True)
    suite = build_suite(work, model=args.model, trials=args.trials)
    runs = work / "runs.json"
    print(f"running {args.trials * 2} Claude Code sessions ({args.model}); output in {work}")
    run_experiment(suite, runs, allow_development=True)

    report = evaluate(runs, args.rates)
    print(f"\n{'':10}{'runs':>5}{'solved':>8}{'cost USD':>11}{'output tok':>12}{'model calls':>13}")
    for arm, label in (("baseline", "baseline"), ("enabled", "token-saver")):
        r = report["results"][arm]
        print(f"{label:10}{r['runs']:>5}{r['successes']:>8}{r['usd']:>11.4f}"
              f"{r['output_tokens']:>12}{r['model_calls']:>13}")
    print(f"\ncost-per-success reduction: {report['cost_per_success_reduction_percent']:+.1f}%"
          "  (positive = Token Saver cheaper)")
    print(f"full report: {runs} (priced with {args.rates.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
