"""Generate the `ledgerkit` stress repository for ACCO cost benchmarks.

The repository is built to stress what ACCO optimizes:
  * ./ci.sh prints ~1 MB (build noise + verbose unittest shards + logging),
    with failures buried mid-log rather than at the tail;
  * ledgerkit/engine.py is ~2,500 lines with a bug past line 2,000;
  * three independent root causes in different files force repeated runs.

Usage: python3 benchmarks/stress/generate_ledgerkit.py <out-dir>

Outputs (all deterministic):
  <out>/repo           git repository with one commit (the task revision)
  <out>/hidden.patch   hidden regression tests applied only for grading
  <out>/reference.patch a reference fix used only to prove solvability
"""

from __future__ import annotations

import random
import subprocess
import sys
import textwrap
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

RNG = random.Random(20260925)
CLOSE_DAY = 25
RULES = 400
SHARDS = 6
TESTS_PER_SHARD = 250


# --- reference behaviour (the spec the tests encode) ------------------------

def ref_parse(text: str) -> Decimal:
    raw = text.strip().replace("$", "").replace(",", "").replace(" ", "")
    negative = raw.startswith("(") and raw.endswith(")")
    value = Decimal(raw.strip("()"))
    return -value if negative else value


def ref_period(day: date) -> tuple[int, int]:
    if day.day > CLOSE_DAY:
        month = day.month + 1
        return (day.year + (month > 12), (month - 1) % 12 + 1)
    return (day.year, day.month)


def ref_total(amounts: list[Decimal]) -> Decimal:
    return sum(amounts, Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ref_rule(i: int, x: int) -> int:
    return (x * (i % 7 + 2) + i) % 1009


# --- source files -----------------------------------------------------------

PARSE_PY = '''\
"""Amount parsing for ledger import files."""

import logging
from decimal import Decimal, InvalidOperation

log = logging.getLogger("ledgerkit.parse")


def parse_amount(text):
    """Parse a ledger amount such as "$1,234.50" or "(12.00)".

    Accounting exports write negative amounts in parentheses.
    """
    raw = text.strip().replace("$", "").replace(",", "").replace(" ", "")
    log.info("parse_amount raw=%r", raw)
    raw = raw.strip("()")
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: {text!r}") from exc
    log.debug("parse_amount value=%s", value)
    return value
'''

PERIODS_PY = f'''\
"""Billing period assignment."""

import logging

log = logging.getLogger("ledgerkit.periods")

CLOSE_DAY = {CLOSE_DAY}


def period_of(day):
    """Return the (year, month) billing period for an invoice date.

    Books close at the end of CLOSE_DAY: invoices dated on the close day
    still belong to the current month; later dates roll to the next month.
    """
    log.info("period_of day=%s close_day=%s", day.isoformat(), CLOSE_DAY)
    if day.day >= CLOSE_DAY:
        month = day.month + 1
        year = day.year + (1 if month > 12 else 0)
        return (year, (month - 1) % 12 + 1)
    return (day.year, day.month)
'''


def engine_py() -> str:
    parts = [
        '"""Rule engine and invoice summarization."""\n',
        "import logging",
        "from decimal import Decimal\n",
        'log = logging.getLogger("ledgerkit.engine")\n\n',
    ]
    for i in range(1, RULES + 1):
        parts.append(textwrap.dedent(f'''\
            def rule_{i:04d}(x):
                """Scoring rule {i}: weight {i % 7 + 2}, offset {i}."""
                log.debug("rule_{i:04d} x=%s", x)
                return (x * {i % 7 + 2} + {i}) % 1009

            '''))
    parts.append(textwrap.dedent('''\
        RULES = {name: fn for name, fn in globals().items() if name.startswith("rule_")}


        def apply_rule(name, x):
            """Apply one named scoring rule."""
            log.info("apply_rule name=%s x=%s", name, x)
            return RULES[name](x)


        def summarize(amounts):
            """Return the invoice total rounded to cents, half-up.

            Totals must be exact: amounts are Decimals and ties round away
            from zero (0.005 -> 0.01), as required by the invoicing spec.
            """
            log.info("summarize n=%d", len(amounts))
            total = sum(float(a) for a in amounts)
            return Decimal(str(round(total, 2)))
        '''))
    return "\n".join(parts)


BUILD_PY = f'''\
"""Pretend native build: compiles rule tables and prints a verbose log."""

import random

rng = random.Random(7)
WARNINGS = [
    "warning: implicit conversion loses precision [-Wshorten-64-to-32]",
    "warning: unused variable 'tmp' [-Wunused-variable]",
    "note: in expansion of macro 'LEDGER_ASSERT'",
    "warning: 'amt' is deprecated; use 'amount' [-Wdeprecated-declarations]",
]
for i in range(1, {RULES} * 25 + 1):
    rule = (i - 1) % {RULES} + 1
    print(f"[build] cc -O2 -fPIC -Iinclude -c rules/r{{rule:04d}}.c -o build/r{{rule:04d}}_{{i:05d}}.o")
    if rng.random() < 0.12:
        print(f"rules/r{{rule:04d}}.c:{{rng.randint(10, 400)}}:{{rng.randint(1, 60)}}: {{rng.choice(WARNINGS)}}")
print("[build] linking build/libledger_rules.so ({RULES} rule objects)")
print("[build] OK")
'''

CI_SH = '''\
#!/bin/sh
# Full CI: native build, then every unittest shard in verbose mode.
set -u
python3 build.py || exit 1
status=0
for shard in tests/test_shard_*.py; do
    name=$(basename "$shard" .py)
    echo "=== running $name"
    python3 -m unittest -v "tests.$name" || status=1
done
exit $status
'''

TEST_BASE = '''\
import logging
import sys

logging.basicConfig(
    level=logging.INFO, stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
'''


def random_day() -> date:
    return date(2025, 1, 1) + timedelta(days=RNG.randint(0, 729))


def parse_case(negative: bool) -> str:
    cents = RNG.randint(100, 9_999_999)
    text = f"{cents // 100:,}.{cents % 100:02d}"
    if RNG.random() < 0.5:
        text = "$" + text
    return f"({text})" if negative else text


def total_case(tie: bool) -> list[str]:
    amounts = [f"{RNG.randint(1, 5000)}.{RNG.randint(0, 99):02d}" for _ in range(RNG.randint(2, 6))]
    if tie:
        amounts.append(f"0.{RNG.choice([5, 15, 25, 35, 45, 65, 85])}5")
    return amounts


def gen_test(kind: str, index: int, failing: bool) -> str:
    """Return one unittest method; `failing` cases hit a seeded bug."""
    name = f"test_{kind}_{index:04d}"
    if kind == "parse":
        text = parse_case(negative=failing)
        want = ref_parse(text)
        body = f"self.assertEqual(parse_amount({text!r}), Decimal({str(want)!r}))"
    elif kind == "period":
        day = random_day()
        if failing:
            day = day.replace(day=CLOSE_DAY)
        elif day.day == CLOSE_DAY:
            day = day.replace(day=CLOSE_DAY - 1)
        want = ref_period(day)
        body = f"self.assertEqual(period_of(date({day.year}, {day.month}, {day.day})), {want!r})"
    elif kind == "total":
        def buggy(values):
            return Decimal(str(round(sum(float(a) for a in values), 2)))

        while True:
            amounts = total_case(tie=failing)
            want = ref_total([Decimal(a) for a in amounts])
            # Failing cases must expose the float bug; passing ones must not.
            if (buggy(amounts) != want) == failing:
                break
        items = ", ".join(f"Decimal({a!r})" for a in amounts)
        body = f"self.assertEqual(summarize([{items}]), Decimal({str(want)!r}))"
    else:
        rule = RNG.randint(1, RULES)
        x = RNG.randint(0, 10_000)
        body = f"self.assertEqual(apply_rule('rule_{rule:04d}', {x}), {ref_rule(rule, x)})"
    return f"    def {name}(self):\n        {body}\n"


def gen_shards() -> dict[str, str]:
    # 45 failing cases, 15 per bug, spread so every shard fails somewhere.
    failing = {
        "parse": {1: 5, 3: 5, 5: 5},
        "period": {2: 8, 4: 7},
        "total": {3: 5, 6: 10},
    }
    shards = {}
    counter = 0
    for shard in range(1, SHARDS + 1):
        methods = []
        plan = []
        for kind, per_shard in failing.items():
            plan += [(kind, True)] * per_shard.get(shard, 0)
        plan += [(RNG.choice(["parse", "period", "total", "rule", "rule"]), False)
                 for _ in range(TESTS_PER_SHARD - len(plan))]
        RNG.shuffle(plan)
        for kind, fail in plan:
            counter += 1
            methods.append(gen_test(kind, counter, fail))
        shards[f"tests/test_shard_{shard:02d}.py"] = (
            TEST_BASE
            + "import unittest\nfrom datetime import date\nfrom decimal import Decimal\n\n"
            + "from ledgerkit.engine import apply_rule, summarize\n"
            + "from ledgerkit.parse import parse_amount\n"
            + "from ledgerkit.periods import period_of\n\n\n"
            + f"class Shard{shard:02d}(unittest.TestCase):\n"
            + "\n".join(methods)
        )
    return shards


def gen_hidden() -> str:
    methods = []
    for i in range(12):
        methods.append(gen_test("parse", 9000 + i, failing=True))
        methods.append(gen_test("period", 9100 + i, failing=True))
        methods.append(gen_test("total", 9200 + i, failing=True))
    methods.append(
        "    def test_parse_rejects_garbage(self):\n"
        "        with self.assertRaises(ValueError):\n"
        "            parse_amount('12.3.4')\n"
    )
    methods.append(
        "    def test_period_rolls_year_after_close(self):\n"
        f"        self.assertEqual(period_of(date(2025, 12, {CLOSE_DAY + 1})), (2026, 1))\n"
    )
    return (
        "import unittest\nfrom datetime import date\nfrom decimal import Decimal\n\n"
        "from ledgerkit.engine import summarize\n"
        "from ledgerkit.parse import parse_amount\n"
        "from ledgerkit.periods import period_of\n\n\n"
        "class HiddenRegressions(unittest.TestCase):\n" + "\n".join(methods)
    )


def git(repo: Path, *args: str, capture: bool = False) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=capture, text=True)
    return proc.stdout if capture else ""


def main(out: Path) -> None:
    repo = out / "repo"
    if repo.exists():
        raise SystemExit(f"{repo} exists; remove it first")
    files = {
        "README.md": "# ledgerkit\n\nInvoice import, billing periods and totals.\n\n"
                     "Run `./ci.sh` for the full build and test suite.\n",
        "build.py": BUILD_PY,
        "ci.sh": CI_SH,
        "ledgerkit/__init__.py": '"""ledgerkit."""\n',
        "ledgerkit/parse.py": PARSE_PY,
        "ledgerkit/periods.py": PERIODS_PY,
        "ledgerkit/engine.py": engine_py(),
        "tests/__init__.py": "",
        **gen_shards(),
    }
    for rel, body in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    (repo / "ci.sh").chmod(0o755)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "stress@example.invalid")
    git(repo, "config", "user.name", "ACCO Stress")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "ledgerkit stress fixture")

    # Hidden tests and the reference fix are produced as patches against HEAD.
    hidden = repo / "tests" / "test_hidden_regressions.py"
    hidden.write_text(gen_hidden(), encoding="utf-8")
    git(repo, "add", "-N", str(hidden.relative_to(repo)))
    (out / "hidden.patch").write_text(git(repo, "diff", capture=True), encoding="utf-8")
    git(repo, "reset", "-q")
    hidden.unlink()

    fixes = {
        "ledgerkit/parse.py": ('    raw = raw.strip("()")\n',
                               '    negative = raw.startswith("(") and raw.endswith(")")\n'
                               '    raw = raw.strip("()")\n'),
        "ledgerkit/periods.py": ("    if day.day >= CLOSE_DAY:", "    if day.day > CLOSE_DAY:"),
        "ledgerkit/engine.py": (
            "    total = sum(float(a) for a in amounts)\n"
            "    return Decimal(str(round(total, 2)))\n",
            "    total = sum(amounts, Decimal(\"0\"))\n"
            "    return total.quantize(Decimal(\"0.01\"), rounding=ROUND_HALF_UP)\n"),
    }
    for rel, (old, new) in fixes.items():
        path = repo / rel
        text = path.read_text(encoding="utf-8")
        assert old in text, rel
        path.write_text(text.replace(old, new), encoding="utf-8")
    parse = repo / "ledgerkit/parse.py"
    parse.write_text(parse.read_text(encoding="utf-8").replace(
        "    return value\n", "    return -value if negative else value\n"), encoding="utf-8")
    engine = repo / "ledgerkit/engine.py"
    engine.write_text(engine.read_text(encoding="utf-8").replace(
        "from decimal import Decimal\n", "from decimal import ROUND_HALF_UP, Decimal\n", 1),
        encoding="utf-8")
    (out / "reference.patch").write_text(git(repo, "diff", capture=True), encoding="utf-8")
    git(repo, "checkout", "-q", "--", ".")
    print(git(repo, "rev-parse", "HEAD", capture=True).strip())


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
