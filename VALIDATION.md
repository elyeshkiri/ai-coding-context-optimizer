# Validation for 1.11.0

Token Saver separates **mechanical correctness**, **retrieval generalization**,
and **end-to-end agent economics**.

Version 1.11.0 adds the expanded CLI-output compression system, provenance-
backed real-output evidence, Smart Tool Proxy, and semantic-retrieval follow-up
while deliberately keeping each claim bounded to the evidence that supports it.
Semantic retrieval remains opt-in, so the existing deterministic/frozen default
retrieval gates continue to measure the validated structural/lexical baseline.

The 1.10 semantic mechanism is covered by deterministic tests that establish:

- chunk vectors and exact-query vectors persist across fresh service instances;
- a repeated unchanged repository/query can reuse semantic state without
  invoking the encoder again;
- changed repository digests re-embed only changed files;
- live source bytes must still match the structural RepositoryIndex digest
  before vectors can be persisted;
- semantic hits contribute explicit chunk coordinates and hybrid-RRF ranking
  evidence;
- final context still contains exact live source rather than a generated
  semantic summary;
- optional HNSW is an acceleration sidecar over authoritative SQLite vectors,
  with exact cosine scan as the semantic fallback.

Those tests establish implementation correctness and safety. They do **not**
establish a new external natural-language recall number.

Semantic holdout #13 has now been consumed exactly once as fresh evidence.
Its 24 query/revision definitions were committed before ground-truth lookup at
`f3247c1d4c8e388de653aea1a5de4fa4624f82ce`, with query-freeze SHA-256
`8cdf871ea2fcbe59161a332f1f0ce0f93b087a6c3560acebadb5ee338c4169bf`.
After answer lookup, two tasks were conservatively classified as
identifier-bearing and excluded without changing their query text, leaving
**22 eligible natural-language tasks** across six previously unused
repositories/language ecosystems.

The final definition is sealed as
`dc6ea6c3641db573b5b05473f2bc4ee13e0f05a4f093cb86f803e68c7b265d25`.
The first real run was GitHub Actions **35537362040**, using pinned
`all-MiniLM-L6-v2` revision
`bc57282bc374d33e0d6c4de27f12dc1c2a87f37a` with exact cosine:

| Arm | File recall |
| --- | ---: |
| Token Saver hybrid semantic | **50.00% (11/22)** |
| Token Saver lexical/structural | **45.45% (10/22)** |
| Trivial distinct-term lexical | **40.91% (9/22)** |

The semantic arm recovered one task missed by Token Saver lexical/structural
and introduced zero regressions. Mean estimated context reduction remained
essentially unchanged (97.8374% semantic vs 97.8373% lexical).

This is modest positive retrieval evidence, not proof of a strong semantic
generalization advantage and not an API-cost/task-success claim. Holdout #13 is
now **burned**. The semantic-retrieval-v3 changes (structure-aware chunks,
multi-hit file aggregation, lexical-independent semantic fusion, and bounded
semantic-witness graph expansion) are deliberately not tuned or scored against
#13. A fresh holdout #14 is required before those changes can support any new
external-generalization claim.

Release CI is anchored to Linux across Python 3.10, 3.12, and 3.13 and requires:

- the complete pytest suite on every supported Python version;
- the deterministic context-quality evaluation;
- the frozen external holdout regression floor;
- PR base-vs-candidate ranking snapshots/diffs;
- Ruff correctness checks;
- 100% docstring coverage via interrogate;
- GitHub Actions workflow linting;
- an optional-Rust job that builds the PyO3 wheel, requires the native backend,
  checks Python/Rust primitive parity, reruns pack/retrieval tests, and reruns
  the deterministic context-quality benchmark;
- the hash-frozen session/output quality replay suite with preservation,
  no-hallucination, and minimum-reduction contracts.

Version 1.9.0 also adds three runtime/product mechanisms whose evidence
boundaries are intentionally narrower than an agent-cost claim:

- **prompt ingress staging** is covered by exact-original SHA-256 verification,
  bounded packet tests, explicit omitted-range recovery, hook ordering tests, and
  default-off configuration. Claude's prompt hook is used only to block before
  model processing; Token Saver does not claim unsupported prompt replacement.
- **persistent retrieval caching** is tested across independent service
  instances. Identical content/config reuses a completed pack; a source mutation
  or retrieval-budget change produces a different cache key and a fresh pack.
  Cache-hit metadata is observable in CLI/MCP output.
- **Rust acceleration** is optional. Normal CI exercises the Python reference
  path; a separate native job builds the extension and requires the same
  primitive outputs plus the same pack/context-quality behavior. Failure to
  build/install Rust does not alter the supported Python runtime.
- **Claude marketplace packaging** is structurally tested for a complete
  generated plugin, stable hooks/MCP/skill content, and the command-source
  safety constraints (printable <=500-character command and <=600-second
  timeout). Actual Claude marketplace acceptance still depends on a supported
  Claude Code installation and is not inferred from JSON fixture tests alone.

These mechanisms may reduce repeated local work or prevent one oversized prompt
from reaching the model, but **1.9.0 makes no new end-to-end cost-savings
percentage claim from their existence alone**.

The 1.9 knowledge-efficiency layer has its own evidence boundary.
`knowledge_read_avoidance` and `cache_economics` are disabled by default.
The checked-in
`benchmarks/knowledge-efficiency-swebench-24.frozen.json` reuses the same 24
SWE-bench Verified tasks at three randomized paired trials per task. Both arms
run the same current Token Saver binary, explicitly persist verified findings
during an identical no-edit investigation phase, and then enter a fresh
implementation session. Continuity, exact cross-turn deduplication, repeated-read
deduplication, and behavioral waste signals are disabled in both arms; only
knowledge-assisted full-read avoidance and its cache-economics acceptance gate
differ.

The accompanying paid/manual workflow represents **144 arm-runs / 288 Claude
task phases**, plus independent hidden verification and blind response grading.
It has **not been executed**. The stored mechanism tests and frozen protocol
therefore establish correctness/isolation only; they do not establish a real
reduction in tool calls, input tokens, billed cost, or cost per successful task.
**No knowledge-efficiency savings percentage is claimed** until the paid paired
run passes success parity, blind-quality parity, treatment-exposure/control-
isolation checks, complete cache-TTL-aware pricing, and a task-cluster 95%
confidence interval whose cost-per-success reduction lower bound is above zero.

Version 1.8.0 adds a separate frozen session-efficiency
holdout rather than treating operational dashboard estimates as evidence. The
holdout reuses the existing 24 SWE-bench Verified task definitions, runs three
randomized paired trials per task, and compares the same current Token Saver
binary with only the four session-efficiency switches changed. Each arm uses a
forced two-session protocol and independent hidden verification; transcript
metrics, blind response grading, exact cache-TTL-aware pricing, and task-cluster
bootstrap intervals feed the publication gate.

The checked-in holdout definition is frozen and mechanically validated, but the
new paid **144 arm-run / 288 Claude-phase** workflow has not yet been executed
for this release candidate. Therefore **no session-efficiency savings
percentage is claimed for 1.8.0** merely from implementing the benchmark.

Version 1.7.0 adds a modular session-efficiency control plane: structured
continuity across resume/compaction, exact cross-turn command/read deduplication,
bounded retry/cascade waste signals, broader command-aware output processors,
and local operational savings dashboards. A new hash-frozen output-quality
fixture is enforced in CI alongside the existing external retrieval holdout and
ranking regression checks. It does **not** retune the frozen retrieval baseline
merely to improve release metrics.

Version 1.6.0 added the complete output-evidence control plane: automatic
task-aware budgets, runtime usage telemetry, cache-TTL-aware cost accounting,
deterministic blind A/B response grading, and the resumable experiment ->
verification -> grading -> cost-per-success -> calibration pipeline.

## Test suite and self-benchmark

- The release gate runs the full suite on Python **3.10, 3.12, and 3.13** rather
  than relying on a single interpreter.
- The included deterministic 25-task selector benchmark at a 6,000-token cap
  currently measures **92% mean relevant-file recall, 92% mean
  relevant-symbol recall, 88% symbol recall in expected files, and 98.71% mean
  estimated context reduction** on the 1.9 release candidate.
- This repository-local benchmark is a diagnostic signal, not the main
  generalization claim and not the frozen release floor. The external holdout
  program below is the stronger retrieval-regression evidence.
- Package metadata for this release is **claude-token-saver 1.10.0**; the import
  remains `token_saver` and the CLI remains `token-saver`.

## Ranking observability and regression validation

Version 1.5.0 adds evidence around *why* ranking changes:

- normal ranking keeps score tracing disabled, preserving the default execution
  path;
- `ranking-explain` verifies trace endpoints against final scores;
- registered post-score stages are traced automatically;
- snapshots retain expected files even when they fall below the ordinary
  display top-N;
- `ranking-diff` refuses incompatible frozen ground truth;
- PR CI captures the baseline with base-commit code against the immutable base
  checkout and the candidate with candidate code;
- both PR snapshots use the base manifest so a PR cannot redefine its own
  comparison ground truth;
- ranking history de-duplicates workflow reruns and selects the newest artifact
  per PR by explicit `(created_at, artifact_id)` comparison;
- historical gate calibration separates frozen ground-truth cohorts and remains
  descriptive until the configured independent-PR evidence floor is reached.

These checks make ranking regressions explainable and reproducible. They do not
turn the current historical sample into a hard merge threshold prematurely.

## Integration lifecycle validation

The setup lifecycle is tested for:

- auto-detection and explicit Claude Code / Cursor / Codex selection;
- idempotent repeated setup;
- preservation of unrelated MCP servers, hooks, and TOML;
- refusal to overwrite malformed JSON or unmanaged conflicting Codex sections;
- preflight of all selected hosts before the first multi-host mutation;
- safe uninstall of only Token Saver-owned entries;
- preservation of a user-modified generated Claude skill;
- project `.token-saver.toml` discovery and environment-variable precedence;
- repository-relative guard allowlist globs;
- Python 3.10 TOML support through the conditional `tomli` dependency;
- top-level dispatcher, doctor, command-discovery, and shell-completion
  behavior.

`doctor` validates configuration/index health; `host-check` remains the
stronger transport/live-host diagnostic. Configuration health alone is not
claimed as proof that an external host accepted model-visible replacement
output.

## Output optimization validation

The failure-aware output subsystem introduced in 1.4 remains a separate
validation surface alongside source retrieval:

- failure-aware routing is tested so success-oriented processors do not
  automatically compress failed commands;
- complex JavaScript test failures with stack frames and multiline diffs are
  preserved verbatim when the processor cannot safely reduce them;
- the shared critical-line recovery path is exercised independently of any
  one processor;
- output replay contracts test exact diagnostic preservation, token budgets,
  minimum reductions, and nonzero exit status on contract failure;
- graph-aware Delta tests diagnostic identity, unchanged compression,
  changed-diagnostic source/symbol mapping, related repository edges, and
  RESOLVED diagnostics after a clean rerun;
- the historical large-Read and Bash `cat` guard regressions remain in the
  suite.

These tests establish mechanics and preservation behavior for covered fixtures.
They are not a universal lossless guarantee for arbitrary command output.

The checked-in `benchmarks/output-quality.example.json` demonstrates the
portable quality-contract format. See `OUTPUT_OPTIMIZATION.md` for the
processor and Delta contracts.

The CLI-compression parity work adds a separate frozen ratchet at
`benchmarks/cli-output-compression-ratchet-v1.frozen.json`. It contains one
representative canonical case for each of the 40 built-in processors and seals
the case definitions with SHA-256. Each case can lock the expected processor,
required evidence, forbidden fabricated evidence, and a minimum token-reduction
floor. CI replays the suite with `--require-frozen`, and the shell uses
`pipefail` so a failed quality contract cannot be hidden by report capture.

The current 40-case replay passes **40/40 cases**, with **74.52% weighted
estimated token reduction**, **100% required-evidence preservation**, **100%
processor-identity match**, and **100% no-hallucination rate**. These fixtures
model documented real-world CLI output shapes; they are not claimed to be
production-log captures, model-token billing measurements, or evidence of
end-to-end coding-task cost reduction.

### Frozen provenance-backed CLI corpus v1

A second output-compression validation layer uses raw output from **real CLI
executions**, captured before inspecting or tuning against those outputs. The
capture harness attempted 31 commands on a GitHub-hosted Ubuntu 24 runner and
successfully captured **30**; Terraform was the only skipped tool because its
executable was absent. Every raw capture is committed under
`benchmarks/cli-output-real-v1/`, with the exact tool version, command, exit
code, byte/line counts, and SHA-256 in the frozen manifest. The original Actions
artifact SHA-256 is also recorded.

The first same-input comparison pins `ppgranger/token-saver` at
`19d47b2cc19457c865f2414ad78f8efa80204b43`. Both engines receive the exact
same 30 raw outputs and are scored with the same Token Saver token estimator and
critical-line survival predicate:

| Engine | weighted estimated token reduction | critical-line survival | changed cases |
| --- | ---: | ---: | ---: |
| elyeshkiri/token-saver | **23.72%** | **100.00%** | 8/30 |
| ppgranger/token-saver @ 19d47b2c | **23.95%** | **81.25%** | 21/30 |

The reduction difference is **6 estimated output tokens across the full
corpus** (2,016 versus 2,010). The largest peer reduction advantages occur on
Git log/status/diff and small Go outputs; the current project is substantially
smaller on the captured Cargo build/test, Docker build, and Ruff outputs.

This is stronger evidence than representative synthetic fixtures, but its scope
is still bounded. These are controlled CI executions rather than production
user logs; several available-tool cases are version/configuration outputs rather
than large workloads; and critical-line survival is a mechanical diagnostic
predicate, not a semantic proof that every useful detail survived. Corpus v1 is
kept immutable. Any tuning informed by its case-level results must treat v1 as
burned development evidence and validate the change on a fresh corpus version.

Corpus v1 was subsequently used exactly that way: Git log/status/diff and Go
compression were tuned from its case-level deltas. On the **burned development
corpus**, the candidate moved from **23.72% to 28.91%** weighted estimated token
reduction while retaining **100%** critical-line survival; the pinned peer
remained at **23.95% / 81.25%**. These post-tuning v1 numbers are development
evidence only and are not used as the proof claim.

### Fresh provenance-backed CLI corpus v2

Corpus v2 was constructed with a different Git history/worktree shape and
different Go failure modes, plus unrelated control commands. Processor behavior
was locked at commit
`bb246458069527e5555bfb9c9625f2750fe53936` before capture. The capture-only
workflow then executed **27/27 real commands with 0 skips**, producing 9,025 raw
bytes. No compressor comparison was run before the exact Actions artifact was
frozen into Git at `benchmarks/cli-output-real-v2/corpus.zip`.

The frozen proof records source workflow run `35581545244`, source artifact
`10629774546`, artifact SHA-256
`6fc01f573b80a6f4768118d27fe38dedddab1543a2d499ee477e286e36051253`,
and capture-definition SHA-256
`ea2461863c384c4c0b56437882a961a817632e6d2af99e81c83b157d220b404b`.
Only after that freeze was committed was the same pinned ppgranger revision
enabled in the comparator.

On this untouched v2 proof set:

| Engine | weighted estimated token reduction | critical-line survival | estimated output tokens |
| --- | ---: | ---: | ---: |
| elyeshkiri/token-saver | **30.80%** | **100.00%** | **1,777** |
| ppgranger/token-saver @ 19d47b2c | **28.23%** | **76.92%** | 1,843 |

That is a **2.57 percentage-point overall reduction advantage** and 66 fewer
estimated output tokens for the candidate on the same 27 raw outputs, while all
mechanically detected critical lines survive.

The tuned subfamilies are not uniformly ahead, so the result is reported
without hiding the remaining gap:

| Fresh v2 subset | elyeshkiri reduction | ppgranger reduction | elyeshkiri critical survival | ppgranger critical survival |
| --- | ---: | ---: | ---: | ---: |
| Git diff | **31.84%** | 28.86% | 100% | 100% |
| Go build/test | **36.67%** | 24.29% | **100%** | 75% |
| Git status | 49.71% | **54.91%** | 100% | 100% |
| Git log | 62.62% | **79.05%** | 100% | 100% |
| Git status/diff + Go, excluding Git log | **38.87%** | 34.93% | **100%** | 75% |
| All targeted Git status/diff/log + Go | 48.80% | **53.39%** | **100%** | 75% |

The fresh corpus therefore validates a real overall gain and specifically
validates the Git-diff and Go improvements, but it also shows that Git log
compression remains materially more aggressive in the pinned peer and Git
status retains a smaller residual gap. No processor tuning was performed after
observing v2. Any future work on those remaining gaps must treat v2 as burned
and prove changes on a fresh v3 corpus.

### Fresh provenance-backed CLI corpus v3

Corpus v3 targets the remaining Git log/status gap using a new nine-commit Git
history, mixed staged/unstaged/untracked worktree state, porcelain v1/v2 status,
verbose/stat/reverse/fuller/oneline/graph log variants, and unrelated control
commands. Git log/status behavior was locked at commit
`18ebda5d623fc01ef2ea5cdf79054ecee7ba76e6` before capture.

The capture-only workflow executed **29/29 real commands with 0 skips** and
produced 14,068 raw bytes. The source workflow is `35584642288`, source
artifact `10630834204`, source artifact SHA-256
`f5345e19b1b77ccf41257c7393242c14b6e5dc88d7cc72f0833e0f032241742b`,
and capture-definition SHA-256
`0866719efa899c3d1d81fc2aa70eabe116ceb4401148ced000d854571581baae`.

The first archive-backed comparison attempt was rejected before evaluation
because the committed ZIP digest did not match the source artifact. No result
was produced from that attempt. The corpus was then stored as the independently
verified raw capture files with their original per-file SHA-256s; CI verifies
all raw hashes and the frozen definition before invoking either compressor.

On this untouched v3 proof set:

| Engine | weighted estimated token reduction | critical-line survival |
| --- | ---: | ---: |
| elyeshkiri/token-saver | 50.50% | **100.00%** |
| ppgranger/token-saver @ 19d47b2c | **51.25%** | 80.00% |

The overall compression difference is only **0.75 percentage points** on the
same 29 raw outputs, while the candidate preserves every mechanically detected
critical line.

The target families show that the original gap is now close to parity:

| Fresh v3 subset | elyeshkiri reduction | ppgranger reduction |
| --- | ---: | ---: |
| Git status (4 cases) | **62.90%** | 61.75% |
| Git log (6 cases) | 78.21% | **79.63%** |
| Git log + status (10 cases) | 75.28% | **76.20%** |

Compared with v2, Git status moved from a peer advantage to a **1.15-point
candidate advantage**, and the Git-log gap contracted from **16.43 points**
(62.62% versus 79.05%) to **1.42 points**. Combined Git log/status is now within
**0.92 percentage points** of the pinned peer on fresh evidence.

The per-shape results remain intentionally visible. The candidate is ahead on
the fresh long-status and porcelain-v2 cases and on `--format=fuller --stat`,
while the pinned peer remains more aggressive on several standard
`git log --stat` variants. Already compact one-line and graph log outputs are
left unchanged by both implementations in this corpus.

No processor tuning was performed after observing v3. Corpus v3 is now burned
proof evidence; any further Git-log compression work requires a fresh v4 corpus.

The previously recorded broad 24-task SWE-bench run remains
**non-publishable evidence** (historical only): it exposed harness/grader issues rather
than a trustworthy product-effect estimate. Version 1.6.0 repairs the
experiment, telemetry, blind-grading, cache-pricing, and publication-gate path
and wires the same frozen **24 tasks × 3 trials** into a paid/manual workflow.
That workflow has not yet been executed for this release candidate.
**No 144-run aggregate savings claim is made for 1.7.0** until the frozen
workflow actually completes and its strict publication gate passes.

## Frozen external holdout program

Token Saver now maintains twelve frozen external holdout suites. Ground truth is
written before evaluation, normalized into a path-independent payload, sealed
with SHA-256, and enforced with `--require-holdout`. Once a suite is evaluated,
it is considered burned for tuning.

### Query difficulty and comparability

The frozen suites do **not** all measure the same query difficulty.

The original 6-task external holdout uses natural-language behavior descriptions
without embedding the target symbol/type identity. By contrast, later suites
including #11 and #12 contain many **identifier-bearing queries** whose wording
names the target class/type and member (for example, asking for a named method
on a named type). Their strong exact-identity numbers therefore validate
navigation, scoping, overload resolution, and identity recovery under
identifier-bearing tasks; they must not be read as evidence that semantic
natural-language retrieval improved monotonically from the early suites to
100%.

This distinction is now part of the benchmark protocol. Future headline
semantic holdouts must follow the no-identifier-leakage query-construction rule
in [BENCHMARKING.md](BENCHMARKING.md#query-construction-protocol), and should
publish a trivial lexical baseline on the same frozen tasks. Identifier-bearing
tasks remain valid when that vocabulary genuinely appears in the upstream user
task, but are reported as a separate query class.

### Holdout #12 — latest fresh external evidence

Holdout #12 follows the pre-declared design from the #11 review: **72
source-grounded tasks across 12 repositories never used in holdouts #1-#11**,
with **6 tasks per repository across 6 languages** (Python, Go, Rust, Java,
TypeScript, and C#).

Repositories: itsdangerous, encode/httpcore, gorilla/websocket, zerolog, uuid,
crossbeam, Apache Commons Text, Apache Commons Codec, Zustand, React Hook Form,
Humanizer, and Newtonsoft.Json.

Frozen ground-truth SHA-256:

`625de623c409f6e77ac695612533f722330db3fd329dfc4b0eb82a0bb6994f54`

Ground truth freeze commit: `6cd5fc8bb5efe16e43e2e5e9625cc12420165135`.
First and only canonical fresh evaluation: GitHub Actions run **35442135225**
from launch commit `20d109d37ea467fe03767cb491b1fe892371d74d`.

| Metric | Fresh first run |
| --- | ---: |
| File recall | **100.00% (72/72)** |
| Bare symbol recall | **100.00% (72/72)** |
| Symbol recall in expected files | **100.00% (72/72)** |
| Qualified-symbol recall | **100.00% (72/72)** |
| Exact symbol-identity recall | **100.00% (72/72)** |
| Mean estimated context reduction | **94.30%** |

All 12 repositories are perfect through exact identity. This is the first fresh
suite in the program to reach 100% at every retrieval/identity level while also
meeting the larger 72-task / 12-repository design.

The context-reduction result must be reported just as literally: **94.30%** is
below the `>=97%` efficiency target proposed after holdout #11. The main reason
is corpus size sensitivity under a fixed 6,000-token budget: the smallest
repository in this suite, itsdangerous, averages only **65.65%** reduction,
while several large repositories exceed 99%. No repository or task is excluded
or reweighted to improve the aggregate.

The exact untouched first-run artifact is checked in as
`benchmarks/holdout-external-12.result.json`. Holdout #12 is now burned for
tuning; later reruns can be regression evidence only.

Two earlier attempts are retained explicitly as rejected audit evidence and are
not counted as canonical holdout #12:

- run **35441174123** reused repositories already present in holdouts #1-#11;
  its manifest/result remain under
  `benchmarks/holdout-external-12-candidate-rejected*.json`;
- run **35441476809** used genuinely unseen repositories but only **25 tasks
  across 5 repositories / 5 languages**, so it did not satisfy the already
  documented 72-task / 12-repository / 6-language design. Its manifest/result
  remain under `benchmarks/holdout-external-12-pilot-rejected*.json`.

Neither rejected attempt was used to tune ranking before the canonical #12
first run.

### Holdout #11 — previous fresh external evidence

Holdout #11 contains **60 source-grounded tasks across 10 repositories never
used in holdouts #1-#10**, spanning C#, Java, TypeScript, Rust, Go, and Python.

Frozen ground-truth SHA-256:

`011dffedad4fe5ea99400cc58655850dcf43f38b3664b9219b4f5cf92a7f94ec`

First and only fresh evaluation: GitHub Actions run **35395304893**.

| Metric | Fresh first run |
| --- | ---: |
| File recall | **96.67%** |
| Bare symbol recall | **96.67%** |
| Symbol recall in expected files | **93.33%** |
| Qualified-symbol recall | **91.67%** |
| Exact symbol-identity recall | **88.33%** |
| Mean estimated context reduction | **99.71%** |

Six repositories were perfect through exact identity: .NET Runtime, EF Core,
Spring Framework, tracing, gRPC-Go, and SQLAlchemy. The fresh C# results are
especially important because .NET Runtime and EF Core independently validate
the C# 14 extension-block recovery introduced after holdout #10.

The seven non-perfect tasks were concentrated in four general classes: dense
Java overload identity, TypeScript interface/generic-member identity, a
same-name TypeScript function in the wrong file, and a Go receiver/member query
overwhelmed by common call-site noise.

After those classes were fixed generically, frozen #11 was rerun **once** as a
burned development diagnostic (run **35399929752**). That diagnostic reached
**100% file, bare, scoped, qualified, and exact identity recall across all
60 tasks**, with **99.71% mean context reduction** and zero misses. This is
regression confirmation only; it does **not** replace the fresh 88.33% exact
first-run result above.

The exact untouched first-run artifact is checked in as
`benchmarks/holdout-external-11.result.json`.

## Historical first external holdout (1.2-era)

A 6-task suite against independently-authored public repositories at
pinned revisions -- [encode/httpx](https://github.com/encode/httpx)
`b5addb6` and [colinhacks/zod](https://github.com/colinhacks/zod)
`59bbc03` -- with ground truth (target files/symbols for a
natural-language query) written from reading the actual source before
ever running the tool, frozen via `--print-ground-truth-hash`, and
evaluated with `--require-holdout` (`benchmarks/holdout-external.json` /
`.result.json`).

- **First run (1.1.0 validation cycle): 83.3% mean file recall, 16.7%
  mean symbol recall**, ~98.5% mean estimated token reduction -- the
  honest, frozen number, not a cherry-picked one, and materially worse on
  symbol recall than this repository's own self-benchmark, exactly the
  generalization gap freezing ground truth in advance exists to catch.
  Two disclosed root causes: per-file symbol sub-ranking could prefer a
  densely-worded helper method over the semantically-correct class/
  function the query was about, and file-level BM25 ranking could prefer
  a prose-rich file discussing a topic over a terser file that is
  actually the correct answer.
- **Current result: 83.3% mean file recall, 83.3% mean symbol
  recall**, ~98.5% mean token reduction unchanged. `httpx-digest-auth`,
  `httpx-redirects`, `httpx-multipart`, `zod-error-tree`, and
  `zod-flatten-error` are all now at 1.0/1.0 symbol recall. Each fix
  along the way was designed and validated against this repository's own
  25-task self-benchmark first (never iterated against this frozen
  suite), then measured against it once, after the fact, purely as an
  observation of generalization -- consistent with this project's
  standing rule against tuning against the same suite that found a gap.
  That process surfaced two of its own regressions along the way (a
  parent-credit symbol-window fix that briefly broke `httpx-redirects`,
  and a file-ranking dampening attempt that broke it again while fixing
  `zod-email-regex`); both are disclosed in full, with root cause and
  resolution, in CHANGELOG.md.
- **Correction (bisected after 1.3.0):** the per-task attribution above is
  stale, and `benchmarks/holdout-external.result.json` (6/6 at 1.0/1.0) no
  longer reproduces. That artifact was accurate when written -- the suite
  scored 6/6 at `3462828` -- but regressed twice afterwards, undetected,
  because this suite ran in no CI job:
  - `6f47fd2` "stop containers from double-counting descendant relevance"
    broke `zod-error-tree` symbol recall (1.000 -> 0.667; partially
    recovered to 0.833 at `3361bdb`, and `zod-error-tree` has failed ever
    since);
  - `7acb0d8` "align structural leaf gates with query tokenization" broke
    `zod-email-regex` file recall (1.000 -> 0.833).

  Current main therefore measures 83.3% file recall, 83.3% bare-symbol
  recall, and 66.7% symbol recall in expected files. The scoped metric is
  lower because `zod-email-regex` can still find a same-named symbol outside
  `regexes.ts`, while `zod-error-tree` misses its expected symbol. The
  aggregate 83.3% bare figures matching the 1.2.0 result are therefore a
  coincidence of offsetting changes.

  `.github/workflows/ci.yml` now runs this suite on every pull request and
  again on every push to `main` via `scripts/check_holdout.py`, enforcing
  file, bare-symbol, and expected-file-scoped symbol floors recorded in
  `benchmarks/holdout-external.floor.json`. The floor update command is
  monotonic and refuses to lower any existing threshold. Neither regression has been
  "fixed" by adjusting ranking: this is a burned holdout, and tuning
  against it to move the number is exactly what the protocol forbids. The
  floor is set at the current value and should be ratcheted upward only
  when a root-cause fix, validated on the self-benchmark first, raises it.
- **Remaining known gap: `zod-email-regex` (0.0 file recall).** Root
  cause identified precisely: `rank_files()`'s outline-term bonus is
  presence-only, not normalized by outline size, so a large file with a
  sprawling outline (`schemas.ts`) picks up more distinct query-term hits
  than a small, precisely on-topic file (`regexes.ts`) purely from having
  more surface area -- even though raw BM25 alone already correctly
  favors the smaller file. A fix (dampening the bonus by outline size)
  was tried and reverted after it broke a different, previously-fixed
  task (`httpx-redirects`, itself a large file that is genuinely the
  correct answer) -- a flat per-file size penalty can't distinguish
  "large and diffusely matching" from "large and genuinely on-topic."
  PR #4 (`fix/authoritative-file-ranking`, see below) targeted this same
  gap via a different mechanism and does not resolve it either:
  `regexes.ts` has no direct incoming `semantic-ref` edge from a file
  that independently outranks `schemas.ts`. Deliberately left unfixed
  pending a *new*, separately-frozen holdout suite to validate a future
  fix against -- re-running a change against the same frozen tasks that
  found the weakness would not demonstrate generalization.

## Merged without their own release (PR #1-#4)

PR #1 (`feat/index-backed-retrieval`), PR #2 (`feat/semantic-retrieval-v2`),
PR #3 (`fix/graph-aware-symbol-ranking`), and PR #4
(`fix/authoritative-file-ranking`) all merged directly to `main` between
1.1.0 and this release, without their own version bump or CHANGELOG entry;
summarized here rather than individually re-documented (see each PR's
description and CHANGELOG.md's entries for full detail):

- PR #1/#2: index-backed retrieval performance, stronger JS/TS module
  semantics, adaptive retrieval budgeting, provider-aware exact token
  counting, multi-repository/frozen-holdout evaluation infrastructure, a
  TypeScript-compiler semantic overlay, and `token-saver host-check`.
- PR #3: caller-graph-aware symbol ranking and exact incoming
  semantic-reference evidence in `_symbol_windows()`.
- PR #4: a strong, deliberately non-transitive one-hop ranking weight for
  exact `semantic-ref` edges. Merged with its own CI check failing on
  every push (only a separate, narrower frozen-holdout workflow was
  green); the underlying gap (`dependency_closure`'s seed set is too
  small to discover a relevant-but-low-raw-score provider) was diagnosed
  and fixed as part of this release -- see CHANGELOG.md.

## Other validation carried over from 1.1.0

- Differential testing verified the `RepositoryIndex` reverse-index
  caching (`symbol_callers`/`neighbors`/test-file signatures) produces
  byte-for-byte identical output to the pre-caching per-call scan it
  replaced, checked across 625 real files and 10 symbols in a separate
  application's repository (not included here).
- Real-world validation: a real 129-file diff from a separate production
  application (private, not included in this repository) was reviewed by
  an isolated model instance with no access to that repository, at a fixed
  4,000-token `pack-diff` budget, against a full-repository-access baseline
  (100,416 tokens, 42 tool calls) and an independently-built 15-item
  ground-truth list. Result: roughly 12-13/15 ground-truth items
  recovered, including two findings the baseline missed, at effectively
  flat token cost (37,306 -> 37,036 tokens). Single diff, not a
  statistically validated benchmark; see
  `tests/test_evidence.py::test_mixed_diff_represents_every_evidence_category_within_budget`
  for the checked-in regression fixture that guards this result without
  depending on the private repository.
- Live host validation executed against a real, separate Claude Code host
  process (version 2.1.274), not a simulated payload: a headless
  `claude -p` session with Token Saver's hooks installed produced a
  captured debug log showing the host receiving
  `hookSpecificOutput.updatedToolOutput` and logging `Hook PostToolUse
  (token-saver hook) replaced tool output`. `token-saver host-check
  --live-evidence <captured-log> --require-live` exits 0 with
  `live_verified: true`.
- Paired coding-agent trials against real bug-fix tasks in
  [encode/httpx](https://github.com/encode/httpx), full-context baseline
  vs. Token Saver's hooks, outcomes independently verified by running the
  target tests directly. Both conditions produced the byte-for-byte
  identical correct fix in both trials. No reliable cost effect was
  demonstrated either way: Token Saver's filtering/guard mechanism never
  actually activated in either trial (both file reads and command output
  stayed under its size thresholds). See CHANGELOG.md.
- Regression coverage exercises bounded dependency closure,
  Tree-sitter-backed JS/TS/JSX/TSX symbol ranges, patch-aware context
  generation, public-signature/removed-symbol/missing-test detection, the
  persistent MCP index service, paired agent-outcome evaluation,
  incremental index reuse, near-duplicate suppression, task-session
  continuity, hard context-pack token caps, exact line-numbered source
  windows, sensitive-path rejection, symlink containment, secret
  redaction, structured Bash output, subprocess hook transport, and
  model/TTL pricing.

## Not executed

- Windows execution of the locking branch.
- A production benchmark proving that task-aware packs reduce total task
  cost for a representative workload; the pack tests prove ranking/budget
  invariants, not end-to-end model quality.
- A fresh, never-seen frozen holdout suite to validate a `zod-email-regex`
  fix against (the original suite is now burned for that specific gap,
  having been used to diagnose and disprove two fix attempts).

No real-world token savings percentage is claimed beyond the private-diff
review and the external holdout benchmark described above, both explicitly
hedged (single diff; six tasks across two repositories), and the paired
coding-agent trials explicitly demonstrated no reliable cost effect either
way rather than a savings claim. Synthetic and unit tests exercise
mechanics and validation, not general product efficacy. See BENCHMARKING.md
for live integration and paired-task measurement procedures.
