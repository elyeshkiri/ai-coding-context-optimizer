# Unreleased

- **Hardened the four failure classes exposed by frozen holdout #11.**
  JS/TS parsing now keeps structurally valid declarations around isolated
  Tree-sitter `ERROR` nodes instead of degrading an entire file to generic
  regex extraction, preserving interface members such as generic
  `Slice.getSelectors` and `Slice.injectInto`. File ranking now gives
  stronger parser-backed authority to an explicit `Container member` pair and
  uses callable-signature evidence to distinguish same-named top-level
  functions; exported top-level API declarations receive a small bounded edge
  over equivalent file-local helpers. Overload ranking now removes terms
  explicitly negated by `without ...` from positive lexical evidence and
  applies a decisive same-family penalty when an overload still carries the
  excluded parameter. These changes target general failure classes rather than
  holdout task IDs, with synthetic regressions for partial TypeScript parsing,
  interface-member identity, Java negative-parameter overloads, cross-file
  same-name top-level TypeScript functions, and Go receiver/member authority
  under many `context.WithTimeout` call sites. The repository index version is
  bumped so persisted indexes cannot retain the old JS/TS fallback records.
  Holdout #11 remains burned; any rerun is development evidence only.

- **Built and first-ran an eleventh frozen external holdout after C# 14 extension-block support.**
  `benchmarks/holdout-external-11.json` contains **60 source-grounded tasks
  across 10 previously-unused repositories**: .NET Runtime and EF Core (C#),
  Spring Framework and Apache HttpComponents Core (Java), Redux Toolkit and
  Vitest (TypeScript), tracing (Rust), go-redis and gRPC-Go (Go), and SQLAlchemy
  (Python). The suite deliberately includes real C# 14 `extension(...)` blocks
  outside RestSharp, dense Java overload families, TypeScript overloads and
  implementation signatures, Rust same-name span members, Go receiver methods,
  and Python class methods in very large source files. All repositories are
  pinned to exact revisions. Ground truth was committed before evaluation and
  frozen at SHA
  `011dffedad4fe5ea99400cc58655850dcf43f38b3664b9219b4f5cf92a7f94ec`.

  Run `35395304893` is the **first and only fresh evaluation** of that frozen
  manifest. It completed successfully with the holdout protocol enforced.

  **First-ever result: 96.67% file recall, 96.67% bare symbol recall, 93.33%
  symbol recall in expected files, 91.67% qualified-symbol recall, 88.33% exact
  symbol-identity recall, and ~99.71% estimated context reduction.** Six
  repositories scored 100% across file/bare/scoped/qualified/exact: .NET
  Runtime, EF Core, Spring Framework, tracing, gRPC-Go, and SQLAlchemy. The two
  fresh C# repositories therefore provide independent confirmation that C# 14
  extension-block extraction generalizes beyond the RestSharp development case.

  The remaining misses are concentrated rather than broad: HttpComponents Core
  has 100% file/bare/scoped/qualified recall but 66.7% exact identity inside a
  dense `EntityUtils.toString` overload family; Redux Toolkit reaches 100%
  file but 83.3% bare, 66.7% scoped and 50% qualified/exact on its selected
  TypeScript callable families; go-redis misses one of six Client tasks at the
  file-selection stage; and Vitest misses one expected file while still
  retaining 100% bare-name recall. The exact untouched result is preserved in
  `benchmarks/holdout-external-11.result.json`. Holdout #11 is now burned for
  tuning.

- **Added compatibility extraction for C# 14 extension blocks.**
  The published `tree-sitter-c-sharp 0.23.x` grammar predates
  `extension_declaration`, so modern source shaped as
  `extension(Receiver receiver) { ... }` could preserve the outer class while
  dropping every inner method from Token Saver's callable index. Token Saver
  now performs a narrow balanced-source recovery pass for those blocks: it
  masks comments and string/character/raw literals, finds only top-level
  extension members, preserves the enclosing class as the qualified parent,
  carries the receiver text into the structural signature, and records exact
  declaration identity lines. Recovered symbols are deduplicated against
  parser-native symbols so a future grammar release can supersede the
  compatibility path without duplicate callables. The repository index version
  is bumped to invalidate stale C# records. Synthetic regressions cover
  overload identity, generic methods, expression-bodied methods, receiver
  evidence, and false-positive protection inside comments/strings. Holdout #10
  remains burned and any rerun is development evidence only. A development-only
  rerun of that burned suite moved bare recall from 89.6% to 100%, scoped recall
  from 87.5% to 100%, qualified recall from 87.5% to 100%, and exact identity
  from 87.5% to 100%; file recall remained 100% and context reduction remained
  ~98.98%. RestSharp specifically moved from 16.7% bare and 0%
  scoped/qualified/exact to 100% on all retrieval and identity metrics. These
  numbers are regression diagnostics, not independent generalization evidence.

- **Built and first-ran a tenth frozen external holdout after callable-identity v5.**
  `benchmarks/holdout-external-10.json` contains **48 source-grounded tasks
  across 8 previously-unused repositories**: RestSharp and Shouldly (C#),
  Mockito and Apache Commons Collections (Java), the MongoDB Node.js driver and
  TanStack Query (TypeScript), futures-rs (Rust), and GORM (Go). The suite
  stresses overload parameter shapes, TypeScript overload signatures versus
  implementations, lower-case container members, trait methods, and a single
  Go receiver type split across multiple source files. All repositories are
  pinned to exact revisions. Ground truth was committed before evaluation and
  frozen at SHA
  `685ac9b9ca60fa02ea2ad797c7b768ee47790b015b9baaff447a74d37c1209f7`.
  A separate hash-only workflow computed and verified the freeze hash without
  cloning benchmark repositories or performing any evaluation.

  **First-ever result: 100% file recall, 89.6% bare symbol recall, 87.5% symbol
  recall in expected files, 87.5% qualified-symbol recall, 87.5% exact
  symbol-identity recall, and ~98.98% estimated context reduction.** Seven of
  eight repositories scored 100% on every retrieval/identity metric:
  Shouldly, Mockito, Commons Collections, MongoDB, TanStack Query, futures-rs,
  and GORM. RestSharp scored 100% file recall but 16.7% bare symbol recall and
  0% scoped/qualified/exact recall on its six C# extension-member tasks.

  Holdout #10 therefore provides fresh evidence that the callable-identity v5
  work generalizes across Java overload families, TypeScript overload
  declarations/implementations, Rust trait members, and Go receiver methods.
  It also exposes a sharply isolated remaining frontier around the modern
  RestSharp C# extension-block source shape: the correct source file is found,
  but the expected extension members are not retained as parser-backed callable
  evidence. The exact untouched first-run output is preserved in
  `benchmarks/holdout-external-10.result.json`. Holdout #10 is now burned for
  tuning.

- **Hardened exact callable identity after holdout #9 exposed lower-case
  member and overload-shape blind spots.** Container/member detection now treats
  member casing as language-specific, so structural hints such as
  `StringUtils split`, `SelectQueryBuilder select`, `ClassTransformer
  instanceToPlain`, and `Sender send` receive the same parser-backed
  authority that PascalCase C# members already had. JS/TS symbols now retain
  structural kinds (function/method/constructor/class/interface/type), with an
  index-version bump so persisted indexes cannot keep the old generic kind.
  Overload ranking also uses explicit zero/one-parameter wording, positive or
  negative array intent, excluded parameter terms, and declaration-vs-
  implementation shape when a TypeScript-style overload family contains both.
  Explicit package/module/top-level requests now prefer top-level definitions
  over same-named receiver/class members. These changes are covered by new
  cross-language synthetic regressions; holdout #9 remains burned and is not
  reused as fresh evidence. A development-only rerun of that burned suite moved
  scoped recall from 87.5% to 95.8%, qualified recall from 85.4% to 95.8%, and
  exact identity from 70.8% to 93.75%, while file recall stayed at 100% and
  context reduction stayed ~97.63%. These numbers are regression diagnostics,
  not independent generalization evidence.

- **Built and first-ran a ninth frozen external holdout under the stricter scoped-symbol metric.**
  `benchmarks/holdout-external-9.json` contains **48 source-grounded tasks
  across 8 previously-unused repositories**: NLog and FluentAssertions (C#),
  Caffeine and Apache Commons Lang (Java), TypeORM and class-transformer
  (TypeScript), Tokio (Rust), and Logrus (Go). The suite targets dense overload
  families, giant source files, declaration-vs-implementation overloads,
  same-name members in different containers, and same-name symbols in different
  files. All repositories are pinned to exact revisions. Ground truth was
  committed before any evaluation and frozen at SHA
  `5c07f59e7a96bb7b6c97764c02aecae2e7597afe6be25b84f95a8154617d7ecf`.

  The initial workflow attempt stopped before evaluating any task because the
  repositories were cloned one directory above the manifest-relative paths.
  Only the workflow clone destinations were corrected; the frozen manifest and
  hash were unchanged. Run `35385165759` is therefore the **first actual
  evaluation** of the frozen ground truth.

  **First actual result: 100% file recall, 95.8% bare source-visible symbol
  recall, 87.5% symbol recall in expected files, 85.4% qualified-symbol recall,
  70.8% exact symbol-identity recall, and ~97.63% estimated context reduction.**
  Per repository file/bare/scoped/qualified/identity recall:
  NLog 100/100/100/100/100, FluentAssertions 100/100/100/100/100,
  Caffeine 100/100/100/100/100, Commons Lang 100/83.3/66.7/66.7/50,
  TypeORM 100/100/83.3/83.3/33.3, class-transformer
  100/83.3/83.3/83.3/33.3, Tokio 100/100/83.3/66.7/66.7, and Logrus
  100/100/83.3/83.3/83.3.

  This is the first untouched external suite created after
  `symbol_recall_in_expected_files` was added. It confirms why the scoped
  metric matters: bare-name recall can remain high when a same-named symbol is
  selected from the wrong file or container. File retrieval remains perfect on
  this suite; the exposed frontier is exact overload/declaration identity,
  especially TypeScript overload declarations/implementations, very large Java
  overload families, and same-leaf container resolution in Rust. The first-run
  result is preserved in `benchmarks/holdout-external-9.result.json`.
  Holdout #9 is now burned for tuning.

- **Built and first-ran an eighth frozen external holdout focused on adversarial callable resolution.**
  `benchmarks/holdout-external-8.json` contains **48 source-grounded tasks
  across 8 previously-unused repositories**: FluentValidation and Polly (C#),
  Guice and Retrofit (Java), class-validator and tsyringe (TypeScript), Rayon
  (Rust), and Viper (Go). The suite deliberately stresses overload families,
  partial classes, generic arity, nested builders, interface/trait members,
  async/sync twins, and package-level functions sharing names with receiver
  methods. All repositories are pinned to exact revisions. Ground truth was
  committed before evaluation and frozen at SHA
  `ea638a0cf9a5777ac5799982a728b6f895aaa952cf7b9f04a714991650c0d7ab`.

  **First-ever result: 100% file recall, 97.9% bare source-visible symbol
  recall, 91.7% qualified-symbol recall, 81.25% exact symbol-identity recall,
  and ~95.31% estimated context reduction.** Per repository
  file/bare/qualified/identity recall: FluentValidation 100/83.3/83.3/83.3,
  Polly 100/100/100/100, Guice 100/100/100/100, Retrofit
  100/100/83.3/83.3, class-validator 100/100/100/50, tsyringe
  100/100/100/66.7, Rayon 100/100/100/100, and Viper
  100/100/66.7/66.7.

  The suite validates the post-Dapper partial-class and overload work on fresh
  repositories: file retrieval is perfect and exact declaration identity
  crosses 80% on an intentionally overload-heavy benchmark. The remaining
  misses are concentrated in TypeScript overload declaration identity,
  package-level-vs-receiver disambiguation in Go, and isolated nested/member
  selection cases. The exact first-run output is preserved in
  `benchmarks/holdout-external-8.result.json`. Holdout #8 is now burned for
  tuning.

- **Fixed six issues found in review of the recent structural-ranking and
  cost-report changes, each with a regression test that fails on the previous
  source.**
  1. *One pathological file no longer aborts indexing.* Deeply nested generated
     sources (JS/Go/Rust/Java/C#, and Python via `ast`) raised `RecursionError`
     from the recursive tree walkers and killed whole-repo indexing.
     `syntax.symbols()` now converts it to a `ValueError`, the Python extractor,
     outline and signature rendering tolerate it, and the file falls back to
     generic extraction. A missing tree-sitter grammar likewise degrades import
     extraction to the regex path instead of raising `ImportError`.
  2. *Structural file authority is narrower and cheaper.* It no longer fires on
     generic callable names defined in more than three files (`get`, `add`),
     is applied before the low-value-directory dampening so tests/examples no
     longer keep an undampened boost, and the query terms, explicit
     container/member pairs and per-name file counts are computed once per
     query instead of once per file.
  3. *Explicit `Name<T>` generic arity now works.* The regex was double-escaped
     inside an rf-string, so `QueryAsync<T>` in a query never set a requested
     arity; only the "two input types ... return type" wording did.
  4. *`cost-report` no longer keeps the last run for duplicate task ids.* Runs
     pair on `(task_id, trial)`; an optional `trial` field supports repeated
     attempts, true duplicates raise with a pointer to `trial`, and the report
     prints a seeded 95% cluster-bootstrap interval over tasks (or `n/a` for
     fewer than two tasks), so a handful of tasks is not read as a precise
     saving.
  5. *Bare-name symbol recall can be checked against the expected files.* The
     evaluator adds `symbol_recall_in_expected_files` (and its mean in the
     summary): a same-named symbol in an unrelated file no longer counts toward
     it. The existing bare `symbol_recall` is unchanged, so frozen holdout
     numbers stay comparable.
  6. *Missing-grammar robustness only.* Tree-sitter grammars remain hard
     dependencies and the version is not bumped; moving them to optional extras
     and cutting a release are packaging decisions left to the maintainer.

  Self-benchmark is unchanged at 100% file and symbol recall (~97.3% context
  reduction). Any re-run of already-burned holdouts after these changes is a
  non-regression diagnostic, not fresh evidence: on holdouts #1-#3 (77 tasks)
  against the previous source, file recall rose on 3 tasks (holdout #2
  87.8% vs 85.4%, #3 96.7% vs 90.0%, #1 unchanged at 100%) and symbol recall
  moved by +1 task in #2, +1 in #3 and -1 in #3. The one loss,
  `scrapy-scheduler-next-request`, comes from finding 2's narrowing: the old
  authority boosted `scheduler.py` because `next_request` matched, but that
  same generic-name boost also lifted unrelated test files. The file is still
  retrieved; its `next_request` window is no longer selected. It was not
  tuned around.

- **Hardened partial-class and overload retrieval after holdout #7's Dapper failures.**
  Repository ranking now gives a bounded, length-independent boost to files that
  structurally define the requested container/member, preventing very large
  implementation files from losing solely to BM25 length normalization. Within
  a file, callable overloads now use overload-family-local signature IDF plus
  structural features for generic arity, arrays, async callables, generic type
  parameter roles, and CommandDefinition-style discriminators. This targets
  exact overload selection without changing holdout #7 or treating a rerun as
  fresh evidence.

- **Built and first-ran a seventh frozen external holdout after callable symbol
  ranking v3, before any tuning against its repositories.**
  `benchmarks/holdout-external-7.json` contains **48 source-grounded tasks
  across 8 previously-unused repositories**: Rich (Python), NestJS
  (TypeScript), Echo and Fx (Go), Hyper and Serde (Rust), Jackson Databind
  (Java), and Dapper (C#). The suite deliberately stresses overloaded members,
  same-name methods in different containers/files, builders, traits/interfaces,
  constructors, and exact declaration identity. All repositories are pinned to
  exact revisions. Ground truth was frozen before the first evaluation at SHA
  `ebd45fda46047399cf3d68a494760e25002cbe0e384b3ae2913834be5afa1249`.

  **First-ever result: 91.7% file recall, 85.4% bare source-visible symbol
  recall, 72.9% qualified-symbol recall, 68.8% exact symbol-identity recall,
  and ~98.71% estimated context reduction.** Per repository
  file/bare/qualified/identity recall: Rich 100/83.3/83.3/83.3, NestJS
  100/100/100/100, Echo 100/100/75/75, Fx 100/100/100/100, Hyper
  100/100/100/100, Serde 100/75/75/75, Jackson Databind 100/100/70/70,
  and Dapper 60/50/30/10.

  This is the first untouched external suite to measure the post-#15 callable
  ranking changes. It provides strong fresh evidence that precise symbol
  selection generalized substantially beyond holdout #6, while exposing Dapper
  as the dominant remaining file/member-selection outlier. The exact first-run
  output is preserved in `benchmarks/holdout-external-7.result.json`.
  Holdout #7 is now burned for tuning.

- **Built and first-ran a sixth frozen external holdout after structural symbol
  graph v2, before any tuning against its repositories.**
  `benchmarks/holdout-external-6.json` contains **24 source-grounded tasks
  across 6 previously-unused repositories**: go-playground/validator and
  spf13/cobra (Go), seanmonstar/reqwest and tokio-rs/bytes (Rust), google/gson
  (Java), and LuckyPennySoftware/AutoMapper (C#). Every repository is pinned to
  an exact revision. Ground truth includes file, bare symbol, qualified symbol,
  and exact `path:qualified@line` identity and was frozen at SHA
  `6c069bc6ef9fcaffd19f6960b9da5e45797a1cbc6f30f9938b937dd2ac7f0535`
  before the repositories were cloned into the validation run.

  **First-ever result: 91.7% file recall, 58.3% bare source-visible symbol
  recall, 50.0% qualified-symbol recall, 45.8% exact symbol-identity recall,
  and ~97.41% estimated context reduction.** Per repository file/bare/qualified/
  identity recall: validator 75/75/50/50, Cobra 100/25/25/25, reqwest
  100/75/75/75, bytes 100/75/75/75, Gson 100/75/75/50, and AutoMapper
  75/25/0/0.

  This is the first fresh suite to measure overload/container identity directly,
  and it confirms the remaining bottleneck is primarily symbol selection inside
  already-correct files rather than file retrieval. The exact first-run output
  is preserved in `benchmarks/holdout-external-6.result.json`. This suite is
  now burned for tuning; follow-up fixes must use independent synthetic
  fixtures and another untouched suite for fresh generalization evidence.

- **Added a deterministic Output Saver benchmark harness.**
  `token-saver output-benchmark manifest.json` runs compaction over inline or
  file-backed responses and reports weighted/mean output-token reduction,
  exact fenced-code preservation, required-content preservation, removed
  units, and budget-overflow rate. The harness intentionally does not claim
  generation-time savings from post-processing; real generated-token and
  invoice effects belong in paired agent runs measured by `cost-report`.

- **Added paired cost-per-success reporting for real agent runs.**
  `token-saver cost-report baseline.json optimized.json` compares identical
  task IDs across baseline and Token Saver runs using success outcomes,
  input/output/cache tokens, model/tool calls, latency, and cost. It reports
  total token and invoice reductions, success-rate change, improved/regressed
  tasks, and the primary commercial metric: **cost per successful task**.
  Costs can be supplied directly per run or derived from configurable
  per-million input/output/cached-input pricing. Mismatched workloads are
  rejected by default so savings cannot be inflated by comparing different
  task sets. The command also accepts the existing single-file
  `agent-evaluate` paired manifest format (`task` +
  `condition=baseline|token-saver`), so quality parity and economics can be
  computed from the same experiment record rather than duplicated data.

- **Built and first-ran a fifth frozen external holdout after the multi-language
  parser work.** `benchmarks/holdout-external-5.json` contains **30
  source-grounded tasks across 6 previously-unused repositories**: chi and zap
  (Go), clap and tower (Rust), Guava (Java), and Serilog (C#). Ground truth and
  exact repository revisions were frozen before Token Saver saw any selected
  repository at SHA
  `9f2d7b6df3971aee95f906a1a85da4fde3c26226d10f3cecc2bafb6ce1c4fca3`.

  **First-ever result: 90.0% file recall, 56.7% source-visible symbol recall,
  and ~97.28% estimated context reduction.** Per repository: chi 100%/100%,
  zap 100%/60%, clap 100%/40%, tower 80%/60%, Guava 60%/40%, and Serilog
  100%/40% (file/symbol recall). The exact first-run output is preserved in
  `benchmarks/holdout-external-5.result.json`.

  This suite is now burned for tuning. Subsequent structural improvements are
  developed on independent synthetic fixtures; a later untouched suite is
  required for fresh generalization evidence.

- **Added structural cross-language symbol graph v2.** Parser-backed Go, Rust,
  Java, and C# symbols now contribute AST-native method calls and import/use
  targets to the repository graph instead of relying on generic call/import
  regexes. `SymbolRecord` now persists qualified identities (for example
  `UserLogger.Information`) and the index format is version 7.

  Context packing keeps the legacy bare-name symbol labels for compatibility
  while also emitting source-visible `path + qualified symbol + line`
  identities. The evaluator can opt into stricter `qualified_symbols`
  ground truth and, when overload/member disambiguation matters, exact
  `symbol_identities` such as `Formatter.cs:Formatter.Format@7`. Both
  fields are opt-in, so historical frozen manifests keep their original hashes.

  Within-file ranking now uses qualified/container names plus a bounded
  parser-derived call signal. Container symbols no longer inherit all
  descendant body vocabulary or additively double-count child relevance;
  this prevents large classes/types from becoming lexical hubs while still
  allowing relevant children to credit their container.

  Validation: **381 tests passing**, Python 3.10/3.12/3.13 CI green, and the
  25-task self benchmark remains **100% file / 100% source-visible symbol
  recall** at **~96.6% estimated context reduction**. Development used
  independent synthetic fixtures; frozen holdout #5 is diagnostic only.

- **Built and first-ran a fourth frozen external holdout before any tuning
  against its repositories.** `benchmarks/holdout-external-4.json` contains
  **40 source-grounded tasks across 8 previously-unused public repositories**:
  Jinja and Werkzeug (Python), ESLint and Undici (JavaScript), gorilla/mux and
  Gin (Go), and Axum and serde_json (Rust). All repositories are pinned to
  exact revisions. Ground truth was authored from source first, frozen at SHA
  `73b66da6cc5b5595ee956154b8c05242a44b011e2d0bd22b3c86faa0278edb38`,
  verified by the evaluator before cloning, and only then evaluated once.

  **First-ever result: 95.0% mean file recall, 45.0% source-visible symbol
  recall, and ~97.18% mean estimated context reduction.** The exact first-run
  output is preserved in `benchmarks/holdout-external-4.result.json`.

  The language split is especially useful: Python measured 90% file / 60%
  symbol recall, JavaScript 90% / 80%, Go 100% / 10%, and Rust 100% / 30%.
  Thus the suite provides strong new evidence that file retrieval generalizes
  across additional languages while exposing a substantial Go/Rust
  symbol-level gap. This suite is now considered burned for tuning; fixes
  inspired by these misses must be developed on independent synthetic fixtures
  and validated by another untouched external suite before being claimed as
  fresh generalization evidence.

- **Added parser-backed symbol extraction for Go, Rust, Java, and C#.**
  These languages no longer rely on the generic one-line declaration regex:
  the shared Tree-sitter syntax layer now records exact source spans, compact
  signatures, symbol kinds, container/receiver relationships, and method-local
  calls. Qualified names preserve ownership across language idioms, including
  Go receiver methods (`Engine.ServeHTTP`), Rust `impl`/trait methods
  (`Json.into_response`, `Handler.call`), Java members, and C# methods,
  constructors, properties, events, and delegates.

  The same structural information now powers repository indexing, code maps,
  and exact named-symbol snippets. The persisted index format was bumped to
  version 6 so older regex-only records are rebuilt automatically. Unsupported
  or malformed source retains the existing conservative generic fallback.

  A first implementation placed the new parsers in a separate generic
  `syntax_multilang.py` module. The self-benchmark immediately caught that
  module becoming an artificial lexical hub and displacing the real
  `snippet.py` target (100/100 -> 96/96). Rather than special-case ranking,
  the language registry was folded into the existing syntax module; the
  temporary diagnostic was removed and the benchmark returned to **100% file /
  100% source-visible symbol recall** at **~96.4% estimated context reduction**.
  Validation: **374 tests passing** and CI green on Python 3.10/3.12/3.13.

  Development used generic synthetic fixtures rather than holdout #4 task IDs.
  Holdout #4 remains burned/diagnostic; it is not re-run here as fresh
  generalization evidence.

- **Added conservative typo-tolerant retrieval and an inspectable context browser.**
  Repository-scope typo normalization now compares query words only against
  indexed identifier vocabulary, requires a high similarity score plus a clear
  margin over the next candidate, and retains the original query term instead
  of rewriting it. Within an already-selected file, a bounded fuzzy identifier
  bonus provides a slightly broader fallback for misspelled symbol names. This
  keeps fuzzy matching subordinate to BM25/graph/structural evidence rather
  than turning it into a new global retrieval strategy.

  Added `token-saver browse` with ranked files, reasons, source-backed selected
  symbols, redacted previews, estimated preview tokens, and visible fuzzy
  corrections. `--show N` prints a detailed candidate and `--interactive`
  provides a small terminal inspection loop (`list`, `show N`, `quit`).
  The browser deliberately reuses the production ranker/source-window/redaction
  path. The same surface is exposed to agents through MCP as
  `browse_context`.

  Validation: **368 tests passing** on Python 3.10/3.12/3.13. The 25-task
  self-benchmark remains **100% file / 100% source-visible symbol recall** at
  **~96.3% estimated context reduction**. The fresh external holdout #3 was
  created and run before this work (90.0% file / 51.7% symbol / ~97.3%
  reduction), so it is not being reused as a tuning target for these changes;
  another untouched holdout is required to make a fresh generalization claim
  about fuzzy retrieval.

- **Built and ran a third, genuinely fresh frozen external holdout
  suite** (`benchmarks/holdout-external-3.json` / `.result.json`): 30
  tasks across 6 independently-authored public repositories never used
  in either prior suite -- [pallets/flask](https://github.com/pallets/flask),
  [tornadoweb/tornado](https://github.com/tornadoweb/tornado),
  [scrapy/scrapy](https://github.com/scrapy/scrapy),
  [tj/commander.js](https://github.com/tj/commander.js),
  [koajs/koa](https://github.com/koajs/koa), and
  [socketio/socket.io](https://github.com/socketio/socket.io) (server
  package). Ground truth authored the same way as the second suite: by
  isolated agents reading each repository's actual source, before
  token-saver was ever run against it, then frozen via
  `--print-ground-truth-hash`. This suite exists because both prior
  suites are now heavily reused for diagnosing and validating fixes --
  a third, untouched suite is needed to check those fixes generalize
  rather than having been quietly tuned to the specific repos that found
  them.

  **First-ever result: 90.0% mean file recall, 51.7% mean symbol
  recall**, ~97.3% mean estimated token reduction. File recall is
  markedly better than either prior suite started at (83.3% and 58.5%
  respectively, before any fixes), consistent with this cycle's fixes
  generalizing rather than overfitting. Symbol recall (51.7%) sits
  between the two prior suites' *current*, already-fixed numbers
  (100% and 63.4%), which is a reasonable, expected outcome for a
  never-tuned suite rather than a red flag on its own.

  One clear repository-level outlier: scrapy, at 40% file / 20% symbol
  recall (3 of 5 tasks missed entirely), spot-checked directly rather
  than left as an unexplained number. All three misses are buried well
  down the file ranking (position 5, 9, and 20) behind several other
  files that are *also* genuinely, non-coincidentally about
  downloading/requests/crawling (`core/downloader/handlers/http11.py`,
  `exceptions.py`, `pipelines/media.py`, `spiders/crawl.py`, ...) --
  the same already-disclosed "large/broadly-related hub file"
  competition pattern found and deliberately left unfixed on the second
  suite (pydantic's `core_schema.py`/`_generate_schema.py`), not a new,
  cleanly-fixable bug. Not chased further in this pass, for the same
  reason: a blanket fix for "many files legitimately share this
  vocabulary" broke a different, previously-correct case (httpx's large
  but genuinely-correct `_client.py`) the one time it was tried this
  release.

- **Fixed a real regression on the first (httpx/zod) frozen external
  holdout: `httpx-redirects` dropped from 1.0 to 0.0 symbol recall**,
  surfaced by re-running that suite after this cycle's stricter
  visible-source-only symbol labeling (see the entry below) started
  correctly filtering out labels whose source doesn't actually survive
  budget fitting. This wasn't the stricter check introducing a bug -- it
  correctly caught a latent fragility in an earlier fix (from before this
  cycle): crediting a boosted parent's matching child with a label
  assumed the parent's *entire* window would render, so the child's code
  would "already be there." For a genuinely large container -- httpx's
  `Client` spans ~1400 lines -- real cross-file budget competition clips
  the window long before reaching the credited child's line (`_client.py`
  was truncated at line 907, well short of `_send_handling_redirects` at
  964), so the label pointed at source that was never actually rendered.

  Fixed by rendering a tight window around the credited child instead of
  the container's full span, once the container exceeds 200 lines (a
  conservative threshold -- small classes like `DigestAuth` keep
  rendering in full, unaffected). A second regression was found and fixed
  while validating this: substituting only the child's window dropped the
  *container's own* declaration line, so its own label then failed the
  same visible-source check for the same reason -- fixed by also keeping
  a couple of lines at the container's declaration alongside the child's
  tight window.

  New regression test
  `test_symbol_window_uses_tight_window_for_credited_child_in_large_container`
  (`tests/test_pack.py`), confirmed via git stash to fail without the fix.
  Verified: 361 tests passing (was 360), self-benchmark unchanged at
  100%/100%, and a one-time re-run of both frozen external holdouts (not
  a tuning loop): the first suite is back to a clean 100%/100%, the
  second, larger suite is unaffected either way (zero regressions, zero
  new passes) -- none of its 41 tasks happened to exercise this specific
  large-container-with-credited-child shape.

- **Improved actual symbol-source recall rather than metadata-only recall.**
  Added a conservative, query-only symbol normalization layer for nearby
  code-oriented wording such as `connection -> connect`,
  `equality -> equal`, `completion -> complete`,
  `validation -> validate`, `persistence -> persist`, and
  `first/begin -> start`. The richer terms are used only after a file has
  already been selected, so repository-wide BM25/file ranking is unchanged.

  Fixed two context-allocation bugs uncovered while making the metric stricter:
  (1) `selected_symbols` previously credited labels even when their exact
  source had been clipped out of the final section, and (2) exact source
  windows were emitted after ranking metadata/full outlines and then sorted by
  source line, allowing lower-value navigation or an earlier weaker symbol to
  consume a tight per-file budget before the higher-scoring implementation.
  Symbol labels now count only when their source line survives, exact source is
  emitted before metadata/outlines, and source windows preserve symbol-score
  order before lexical navigation windows.

  The stricter accounting initially exposed the self-benchmark's previous
  100% symbol result as partly metadata-only (88% when source presence was
  enforced). The source-priority fixes recovered a **real 100% file / 100%
  symbol recall** on the 25-task self-benchmark at ~96.0% estimated context
  reduction. Full suite: **360 tests passing** on Python 3.10/3.12/3.13.

  A one-time diagnostic run of the already-burned 41-task external suite is
  intentionally *not* treated as new generalization evidence. Under the new
  stricter source-visible metric it measured 87.8% file / 59.8% symbol recall;
  compared task-by-task with the old stored result, `requests-connect-timeout`
  improved from 0 to 1 while three old positive symbol hits disappeared because
  their labels did not have source surviving in the actual pack. Further
  tuning against that suite was stopped; a fresh holdout is required for a new
  generalization claim.

- **Added Output Saver, a deterministic output-token layer for coding agents.**
  Generation-time `output-policy` produces terse/normal/detailed response
  contracts with explicit token targets, no task restatement/tool narration,
  diff/reference-first code guidance, compact validation reporting, structured
  agent-to-agent state, and stop-on-success behavior. `output-save` safely
  compacts already-generated responses by removing trivial filler, exact
  repeated prose/status echoes, and pretty-print JSON overhead; optional
  `--enforce-budget` trims prose only. Fenced code and diffs are never
  truncated: if preserved code cannot fit, the result explicitly reports
  `budget_exceeded` rather than corrupting source. Both capabilities are also
  available as MCP tools (`output_policy`, `compact_output`) and report
  estimated before/after token counts so output savings can be measured
  separately from input-context savings.

- **Investigated the second holdout suite's remaining 19 misses in
  detail; fixed one more real bug, attempted and reverted one extraction
  extension, and disclosed the rest as genuinely hard rather than forcing
  a fix.**

  Fixed: the acronym-boundary regex added for `HTTPBasicAuth` was itself
  slightly too eager -- `(?<=[A-Z])(?=[A-Z][a-z])` fires on a *single*
  leading capital too, so `ETag` split into `E`+`Tag` and never matched
  the plain `etag` property name used for the same concept elsewhere in
  the same codebase (expressjs/express). Tightened the lookbehind to
  require *two* preceding uppercase letters (`(?<=[A-Z][A-Z])`), so
  genuine acronym prefixes (`HTTP`, `XML`, `IO`) still split but a single
  leading capital (`ETag`, `IPage` -- almost always just an ordinarily-
  capitalized word) does not. New test
  `test_single_leading_capital_is_not_treated_as_a_one_letter_acronym`
  (`tests/test_lexical.py`).

  Attempted and reverted: extending `assignment_expression` extraction to
  cover `exports.etag = createETagGenerator({...})` (a CommonJS export
  whose value is a call result, not a function literal) by treating any
  `exports.X = <anything>` as an exported data symbol, mirroring the
  existing treatment of `export const X = <data>`. This swept up trivial
  one-line re-export aliases too (`exports.request = req`,
  `exports.response = res`, in express's own `lib/express.js`), and one
  of those aliases' name happened to coincidentally match a different
  task's query vocabulary strongly enough to displace the genuinely
  correct symbol (`createApplication`) -- a real, measured regression
  (`express-create-application`, 1.0 -> 0.0 symbol recall), not a
  measurement artifact this time. Reverted; `exports.etag` itself remains
  unextracted (a real, disclosed extraction gap), though the query terms
  now at least match its plain `etag` symbol thanks to the acronym fix
  above -- it competes closely (a 1-point score gap against two sibling
  helpers) rather than being invisible.

  Investigated but deliberately left unfixed, each for a distinct,
  disclosed reason rather than silently dropped:
  - `pydantic/errors.py`, `pydantic/root_model.py`: buried at file rank
    49 and 19 respectively behind pydantic's few large, genuinely
    heavily-cross-referenced "hub" files (`core_schema.py`,
    `_generate_schema.py`, `json_schema.py`) that legitimately discuss
    schema/model/validation extensively for nearly every query in this
    domain. This is the same large-file-dominance shape that broke
    `httpx-redirects` when a blanket size-based dampening was tried
    earlier this release (and reverted) -- not attempted again without a
    fundamentally different, more targeted signal than file size.
  - `requests/exceptions.py` (`ConnectTimeout`): loses to its own parent
    classes (`ConnectionError`, `Timeout`) partly because "connect" and
    "connection" are different word forms the tokenizer doesn't stem
    together -- a general English-morphology gap (also behind
    `lodash-deep-equal`'s `equality`/`equal` mismatch and
    `date-fns-start-of-week`'s `start`/`first` synonym gap), not a
    single targeted bug; a real stemmer or synonym table is a much larger
    change than this pass's scope.
  - `axios-cancel-request-timeout`, `date-fns-start-of-week`: many
    structurally-similar sibling files (date-fns's `getWeek`/
    `getWeekOfMonth`/`getWeekYear`/...) all receive the identical
    `graph:semantic-ref@1` boost via their own `fp/` re-export, so the
    signal doesn't discriminate the correct sibling from the others here.
  - `express-negotiate-accept-header` (`accepts` vs `header`): a genuine
    near-tie (22 vs 21 raw score), not a clear miss.

  Verified: 342 tests passing (was 341), self-benchmark unchanged at a
  clean 100%/100%, and the second frozen holdout ends this investigation
  net neutral on its own numbers (87.8%/62.2%, matching the pre-
  investigation state) but with one additional real bug fixed and
  disclosed rather than a regression shipped -- the reverted attempt was
  caught before being kept specifically because of the discipline of
  re-checking both frozen holdouts, not the self-benchmark alone, before
  trusting a change.

- **Strengthened test/doc-file deprioritization for "how does X work"
  queries** -- the largest remaining root cause behind the second frozen
  external holdout's misses (8 of the original 19), and the same class of
  problem two earlier, reverted file-ranking attempts targeted with
  novel, ad-hoc signals (symbol-name rarity, outline size). This attempt
  used neither: `file_priority()` (`skeleton.py`) already correctly tags
  `tests/`, `docs/`, `fixtures/`, and similar directories as low-value,
  and is already used elsewhere (the repo map/skeleton listing) without
  issue -- `rank_files()` just applied it far too weakly to matter, a
  flat `+0.3`-vs-`+1.2` additive bonus against BM25 scores that routinely
  run into the tens of points. A test file that exercises a feature
  extensively, or a doc page that explains it in prose, both legitimately
  share a lot of vocabulary with a query about that feature without being
  the right answer to it, and nothing was strong enough to say so.

  Fixed by dampening (not just lightly nudging) a low-value-directory
  file's whole computed score by 0.35x, so the penalty scales with
  however large the underlying score actually is, rather than adding a
  fixed, easily-swamped amount. New regression test
  `test_rank_files_prefers_implementation_over_test_file_for_how_does_x_work`
  (`tests/test_pack.py`), confirmed via git stash to fail without the fix.

  Verified: 341 tests passing (was 340), self-benchmark reached a clean
  **100%/100%** (up from 92%/96%, including `pack-cli`, a self-referential
  failure present since early in this session that was never chased down
  before), and a one-time re-run of both frozen external holdouts: the
  first httpx/zod suite remains 100%/100%; the second, larger suite rose
  from 58.5% to **87.8% mean file recall** and 58.5% to **62.2% mean
  symbol recall**, with 4 tasks newly passing and 2 partial regressions
  (`click-group-dispatch`, `pydantic-json-schema-generation`, both
  1.0->0.5 symbol recall) that turned out, on direct inspection, not to be
  real behavior regressions at all: in both cases the *previous* 1.0 was
  itself a false positive -- a test file (`tests/test_commands.py`,
  `tests/test_json_schema.py`) happened to define its own, unrelated
  method with the exact same bare name as the ground-truth symbol
  (`resolve_command`, `generate`), which the recall metric counts as a
  match regardless of which file it came from. Suppressing that test file
  correctly removed the accidental match and exposed a real, separate,
  disclosed gap this fix doesn't touch: the actual `resolve_command`/
  `generate` methods in their correct files aren't independently winning
  their own symbol-window competition against sibling classes/methods.

  The self-benchmark's 100%/100% here is not the same warning sign the
  reverted outline-size attempt's 100%/100% was: that one broke a
  different, previously-fixed holdout task outright (`httpx-redirects`).
  This one was checked against both frozen holdouts before being trusted,
  and produced zero real regressions on either.

- **Fixed a JS/TS symbol-extraction gap and generalized the parent-credit
  symbol-window boost past Python.** Two changes shipped together because
  the second was found as a direct regression from the first.

  1. **`obj.prop = function () {...}` was invisible to symbol
     extraction.** tree-sitter gives this common CommonJS/prototype-
     assignment pattern its own `assignment_expression` node type with
     "left"/"right" fields, not the "name"/"value" fields the extractor
     already handled for `const x = function(){}` (`variable_declarator`)
     and object-literal methods (`pair`). Left unhandled, an entire public
     API surface written this way -- as expressjs/express's
     response.js/request.js near-universally are -- never appeared in the
     index at all (`res.cookie`, `req.accepts`, and similar were
     completely missing). Fixed in `syntax.py` by handling
     `assignment_expression` the same way.
  2. **Regression:** once `View.prototype.lookup`/`render` became visible,
     they immediately began outscoring and displacing `View` itself --
     the same DigestAuth-shaped failure, just newly exposed for JS/TS's
     pre-ES6 constructor-function/prototype-method pattern rather than
     fixed for it, since the earlier DigestAuth fix's parent-credit boost
     is gated on `kind == "class"`, which JS/TS symbols never carry
     (tree-sitter extraction tags all of them `"symbol"` regardless of
     shape). Fixed by generalizing the boost's eligibility check from
     `kind == "class"` to "has at least one other symbol recording it as
     `parent`" -- a structural definition that already exactly matches
     Python's `kind == "class"` in practice (parent is only ever set for
     class-contained methods there) but also now correctly covers real JS/
     TS `class` bodies and the new `X.prototype.method` pattern. This
     required also fixing *what* records a `parent` link in the first
     place: previously *any* accepted symbol (including an ordinary
     function) prefixed its descendants' qualified names, so an ordinary
     function containing a nested helper function would have newly
     qualified as a "container" too under the broadened check -- reintroducing
     the exact over-boosting bug fixed earlier for `zod-error-tree`/
     `zod-flatten-error`. Restricted qualified-name prefixing in
     `syntax.py` to genuine containers (`class_declaration`,
     `interface_declaration`, `enum_declaration`) plus the new
     `X.prototype.method` link, so ordinary function nesting creates no
     parent link in either language, same as Python already didn't.

  New tests:
  `test_member_assignment_function_is_indexed_with_prototype_owner_as_parent`
  (`tests/test_v1.py`, direct extraction/parent-linking check) and
  `test_symbol_window_boosts_prototype_constructor_over_its_own_methods`
  (`tests/test_pack.py`, end-to-end); the existing
  `test_symbol_window_does_not_boost_function_nested_in_another_function`
  regression test continues to pass, confirming the nested-function fix
  wasn't undone.

  Verified: 340 tests passing (was 338), self-benchmark file recall shows
  a one-task self-referential-corpus dip (96% -> 92%: this commit's own
  new comment in `syntax.py`, which mentions "symbol extraction",
  coincidentally overlaps the self-benchmark's `snippet` task query more
  than before -- not a logic regression, the same category of noise
  `snippet`/`pack-cli` have shown before), and a one-time re-run of both
  frozen external holdouts (not a tuning loop): the second, larger suite's
  mean symbol recall rose from 56.1% to **58.5%** with zero regressions
  across all 41 tasks, the first httpx/zod suite remains a clean 100%/100%.

- **Fixed an acronym-prefixed identifier tokenization bug.** `terms()`'s
  camelCase splitter only recognized a lowercase/digit-to-uppercase
  transition, not an uppercase-run-to-title-case one, so an identifier
  like `HTTPBasicAuth` tokenized as one fused word (`httpbasic`, `auth`)
  instead of `http`, `basic`, `auth`. Found via the second frozen external
  holdout: a query for "HTTP basic authentication" never matched
  `HTTPBasicAuth`'s own name at all (scored 0), so an unrelated helper
  function that merely mentioned "basic"/"HTTP" in prose comments won the
  symbol-window competition instead of the obviously correct class. Fixed
  by adding the missing boundary pattern to `_CAMEL` in `lexical.py`
  (`URLPattern`, `XMLHttpRequest`, and similar acronym-prefixed names are
  affected the same way; plain acronyms like `ID` are unaffected). New
  tests: `tests/test_lexical.py` (direct tokenizer unit tests) and
  `test_symbol_window_matches_acronym_prefixed_class_name`
  (`tests/test_pack.py`, an end-to-end reproduction of the real shape),
  both confirmed via git stash to fail without the fix.

  Verified: 338 tests passing (was 335), self-benchmark unchanged (96%
  file / 96% symbol recall -- this repository's own identifiers happen not
  to hit the acronym-prefix shape), and a one-time re-run of both frozen
  external holdouts (not a tuning loop -- this is a general tokenizer
  correctness fix, not tuned to either suite's scores): the second, larger
  suite's mean symbol recall rose from 53.7% to **56.1%** with zero
  regressions (`requests-basic-auth` now 1.0/1.0), the first httpx/zod
  suite remains a clean 100%/100%.

- **Built and ran a second, larger, genuinely fresh frozen external
  holdout suite** (`benchmarks/holdout-external-2.json` /
  `.result.json`): 41 tasks across 8 independently-authored public
  repositories never used in any prior validation --
  [pallets/click](https://github.com/pallets/click),
  [pydantic/pydantic](https://github.com/pydantic/pydantic),
  [psf/requests](https://github.com/psf/requests),
  [tiangolo/fastapi](https://github.com/tiangolo/fastapi),
  [axios/axios](https://github.com/axios/axios),
  [date-fns/date-fns](https://github.com/date-fns/date-fns),
  [expressjs/express](https://github.com/expressjs/express), and
  [lodash/lodash](https://github.com/lodash/lodash). Ground truth for
  each repository was authored independently (by isolated agents with no
  access to token-saver's own source or the tool's known weaknesses'
  specifics beyond "include some large-file-correct and some
  terse-file-correct cases if the repo naturally supports them"), from
  reading the actual source, before token-saver was ever run against it,
  then frozen via `--print-ground-truth-hash` exactly as the first
  holdout suite was. This suite exists specifically because the first
  6-task httpx/zod suite was explicitly disclosed as "burned" for further
  `zod-email-regex`-style diagnosis after two failed fix attempts against
  it -- validating a future fix needs ground truth that was never used to
  find or chase that fix.

  **Result: 58.5% mean file recall, 35.4% mean symbol recall**, ~98.4%
  mean estimated token reduction -- the honest, frozen, first-ever number
  on this suite, and materially worse than both this repository's own
  self-benchmark (92%/96%) and the now-much-improved first external
  holdout (83.3%/83.3%). This is a significant, previously-invisible
  generalization gap that neither of the smaller/narrower benchmarks used
  so far happened to surface.

  Root-caused by inspecting every one of the 16 missed tasks directly
  (not by guessing from the aggregate number): two distinct, compounding
  causes, not one.
  1. **Test and documentation files systematically outrank
     implementation files for "how does X work" queries.** 10 of 16
     misses had a test file (`tests/test_validators.py`,
     `tests/test_requests.py`, ...) or a docs page ranked #1, ahead of
     the actual implementation. This isn't an unreasonable BM25 outcome
     in isolation -- a test file that exercises a feature extensively
     genuinely does share a lot of vocabulary with a query about that
     feature -- but nothing in the ranking signal set distinguishes "a
     file that exercises/discusses the concept" from "the file that
     implements it," which is what most of these queries were actually
     asking for.
  2. **No cap on how much of the total budget a single file can consume.**
     `build_context_pack`'s per-candidate budget loop has no general
     fair-share limit (the existing `slots_left` fair-share logic only
     applies to explicitly-passed `priority_files`, and the
     `authoritative_reserve` mechanism only protects one specific
     semantic-ref provider). When the #1-ranked file is both large and
     the (arguably mis-ranked) top scorer, it can consume the entire
     budget in one shot, e.g. `tests/test_validators.py` alone used 5993
     of pydantic's 6000-token budget, leaving literally nothing for
     `pydantic/functional_validators.py` -- the actual, correctly-ranked
     #4 candidate -- to ever be considered. This compounds cause 1 into
     complete, one-file-only failures: every task with only 1-2 files in
     `selected_files` hit this pattern.

  Deliberately not fixed in the same commit as the diagnosis -- see the
  next entry for cause 2's fix, designed and validated against the
  self-benchmark first, per this project's standing discipline.

- **Fixed cause 2 above: no cap on how much of the budget a single file
  can consume.** `build_context_pack`'s per-candidate loop now caps an
  ordinary (non-`priority_files`) candidate's share of what's left to
  `max(remaining * 3/5, 300 tokens)`, mirroring the existing
  `priority_files` fair-share mechanism but generalized to every
  candidate. The cap only applies while more candidate files and
  selection slots remain -- the true last usable candidate still gets
  whatever's left rather than wasting it unused, so this never shrinks a
  pack when only one or two files are genuinely relevant. New regression
  test `test_context_pack_does_not_let_one_large_file_monopolize_the_budget`
  (`tests/test_pack.py`), confirmed via git stash to fail without the fix.

  Verified: 335 tests passing (was 334), self-benchmark **improved**
  (92% -> 96% file recall, 96% symbol recall unchanged -- the pre-existing
  `snippet` self-referential-corpus failure is fixed as a side effect, only
  `pack-cli` drift remains), and a one-time re-run of both frozen external
  holdouts (not a tuning loop -- this fix targets the general budget
  mechanism, not either suite's specific scores): the second, larger suite
  went from **58.5% to 80.5% mean file recall, 35.4% to 53.7% mean symbol
  recall**, zero regressions across any of the 41 tasks, 10 tasks newly
  passing. The first, smaller httpx/zod suite -- unrelated in design intent
  to this fix -- incidentally also went to a clean **100%/100%**: its one
  remaining disclosed gap, `zod-email-regex`, turned out to be the exact
  same budget-monopolization pattern (`schemas.ts` was starving
  `regexes.ts` of any room at all), not solely the outline-size ranking
  bias two earlier, reverted attempts targeted.

  Remaining known gaps on the larger suite, both untouched by this fix and
  disclosed rather than chased further in this pass: cause 1 (test/doc
  files outranking implementation files) accounts for 8 of the 20
  remaining misses (file recall still 0). The other 12 are a third,
  previously-uncharacterized failure mode -- the correct *file* is found
  (file recall 1.0) but the correct *symbol* isn't selected within it
  (`requests-basic-auth`, `lodash-clone-deep`, `lodash-deep-equal`,
  `express-generate-etag`, and others) -- distinct from the DigestAuth-
  shaped symbol-window bugs fixed earlier in 1.2.0, since those files
  aren't classes with a competing method or a type alias; worth its own
  root-cause investigation before attempting a fix.

# 1.2.0

Note: PR #3 (`fix/graph-aware-symbol-ranking`) and PR #4
(`fix/authoritative-file-ranking`) merged directly to `main` without their
own version bump or CHANGELOG entry; summarized here rather than
re-documented in detail (see the PR descriptions for full rationale).
PR #3 added caller-graph-aware symbol ranking and exact incoming
semantic-reference evidence to `_symbol_windows()`, targeting the same
generalization gap the first frozen holdout found, without tuning against
that frozen suite. PR #4 gave exact `semantic-ref` edges a strong,
deliberately non-transitive one-hop ranking weight, aimed at the
`zod-email-regex`-shaped gap (a terse provider file supplying an exact
value a query-relevant consumer file describes in prose) -- it merged with
its own CI check failing (see the fix below) and, per a fresh one-time
holdout check after that fix, does not actually resolve `zod-email-regex`
itself: `regexes.ts` has no direct incoming `semantic-ref` from a file
that independently outranks `schemas.ts`, so the underlying outline-size
bias documented below is still the live, unfixed root cause.

- **Fixed CI on `main`**, broken by PR #4 (`fix/authoritative-file-ranking`,
  merged despite its own `CI` check failing on every push -- only its
  separate, narrower `PR4 Frozen Holdout` workflow was green). The failing
  test, `test_context_pack_reserves_budget_for_exact_provider_behind_large_consumer`,
  exposed a real gap in that PR's own "authoritative provider" mechanism,
  not an interaction with unrelated work: `rank_files()` only seeds
  `dependency_closure` from the top `seed_limit` files by raw score
  (deliberately small and cost-bounded, since most edge kinds it walks are
  transitive and can fan out), so a source file that's clearly on-topic but
  ranks below that cutoff -- e.g. behind several near-duplicate files that
  outscore it on raw term overlap alone -- never got a chance to surface an
  exact value it imports via a `semantic-ref` edge. `build_context_pack`'s
  budget-reservation search window for that same signal was independently
  too narrow for the same reason. Fixed with `closure.authoritative_providers`
  (`src/token_saver/closure.py`): a separate, cheap, non-transitive one-hop
  scan over every relevant candidate (not just the seed set) for
  `semantic-ref` edges specifically -- cheap because that edge kind never
  expands further regardless of how many sources it's checked from, unlike
  the general closure walk. `build_context_pack`'s reservation search now
  scans all candidates for the resulting tag instead of a truncated prefix,
  since the tag itself is already the bounded, authoritative signal.
  Verified: 334 tests passing (was 328), self-benchmark unchanged
  (92%/96%), frozen external holdout unchanged (83.3%/83.3%, one-time
  re-run, not a tuning loop).

- **Fixed both remaining symbol-selection root causes behind
  `zod-flatten-error` and `zod-error-tree`** (the other two frozen external
  holdout tasks disclosed as unfixed in VALIDATION.md), found by
  investigating `zod-flatten-error` fresh rather than reusing the
  previously-abandoned "terse implementation" file-ranking framing --
  both turned out to be *symbol-window* bugs, not file-ranking bugs (file
  recall was already 1.0 for both).

  1. **Type alias signatures went untruncated.** `type_alias_declaration`
     has no tree-sitter "body" field (functions/classes/interfaces do), so
     its inline right-hand side -- however large -- went straight into its
     captured `signature`, double-counting every word in it at both the
     20x name-term ranking weight (signature) and the 1x body-term weight
     it already gets like any other symbol's body. A type alias describing
     `flattenError`'s return shape (`_FlattenedError`, whose fields are
     literally named `formErrors`/`fieldErrors`) outscored `flattenError`
     itself purely from its own field names matching the query. Fixed in
     `syntax.py` by truncating a type alias's signature at its `value`
     field, the same way a function/class signature truncates at its
     `body` field. New direct test:
     `test_type_alias_signature_is_truncated_like_a_function_body`
     (`tests/test_v1.py`), confirmed via git stash to fail without the fix.

  2. **The parent-credit boost (from the DigestAuth fix above) wasn't
     scoped to classes.** It also applied when a *function* contained a
     nested helper function -- a fundamentally different relationship
     from class/method: a class groups multiple members that can each
     independently be the right, narrower answer; a function's nested
     helper is just an implementation detail of that one function, not a
     set of candidate answers. A top-level distractor function's own body
     already includes its nested helper's text (so its own score already
     reflects the helper), but the boost added the helper's score a
     *second* time, letting an unrelated function outscore the file's
     actually correct, unrelated top-level function (`treeifyError` /
     `flattenError`, depending on the query). Fixed in `pack.py` by
     restricting the boost to parents with `kind == "class"` -- available
     for Python (`ast.ClassDef`); JS/TS symbols are all tagged `"symbol"`
     today regardless of shape, so this disables the boost for JS/TS
     entirely for now rather than mis-scoping it, a disclosed limitation,
     not a regression (no passing JS/TS behavior depended on it). New
     regression test:
     `test_symbol_window_does_not_boost_function_nested_in_another_function`
     (`tests/test_pack.py`), confirmed via git stash to fail without the
     fix.

  Verified: 328 tests passing (was 326), self-benchmark unchanged
  (92%/96%), and a one-time re-run of the frozen external holdout (not a
  tuning loop -- both fixes are general correctness fixes discovered by
  reading the symbol-extraction and boosting code, not by iterating
  against this suite's specific scores) shows **`zod-flatten-error` and
  `zod-error-tree` both now at 1.0/1.0** with no new regressions across
  any of the 5 previously-passing tasks: mean symbol recall
  **66.7% -> 83.3%**, file recall and token reduction unchanged.

  **A third attempt, at the actual remaining `zod-email-regex` file-ranking
  gap, was tried and reverted.** Root cause identified precisely this
  time: `rank_files()`'s `symbol_hits` bonus (`+5` per distinct query term
  present anywhere in a file's outline) is presence-only, not
  frequency-normalized, unlike the properly length-normalized BM25 term
  right above it in the same function -- so a file with a sprawling,
  many-hundred-symbol outline (`schemas.ts`, 201,606 outline characters)
  picks up far more distinct query-term hits than a small, precisely
  on-topic file (`regexes.ts`, 900 outline characters) purely from having
  more surface area, even though raw BM25 alone (before this bonus is
  added) already correctly favors the smaller file (15.8 vs 8.0).
  Dampening the bonus by how far a file's outline exceeds the corpus's
  average outline size fixed `zod-email-regex` and, unexpectedly, pushed
  the self-benchmark to a clean 100%/100% -- but it also broke a
  previously-fixed, previously-passing task, `httpx-redirects` (1.0 ->
  0.0 file recall): `_client.py` is *itself* a large, many-symbol file
  that is genuinely the correct answer, and the same dampening that
  correctly demotes `schemas.ts` also demotes `_client.py` below a test
  file with high raw term overlap. A flat per-file outline-size dampener
  can't distinguish "large file, diffusely and incidentally matching" from
  "large file, genuinely and heavily on-topic" -- the same class of
  failure the earlier "terse implementation" attempts hit, now confirmed
  a third time on a different mechanism. Reverted; `zod-email-regex`
  remains a disclosed, deliberately unfixed gap. The self-benchmark's
  100%/100% result on the reverted version is itself worth noting: it
  would have shipped clean on the self-benchmark alone had the frozen
  external holdout not been re-checked before committing.

- **Fixed the DigestAuth per-file symbol-selection bug** the external
  holdout benchmark found (`httpx-digest-auth`: found the right file,
  `_auth.py`, but selected helper methods `_parse_challenge`/
  `_build_auth_header` over the actually-relevant class `DigestAuth`).
  Distinct from PR #3's graph-aware ranking (which fixes a *different*
  failure shape -- a top-level distractor function reached via
  caller-graph evidence): here the outranking symbols are the class's own
  nested methods, so no caller-graph signal applies. Root cause: a
  class-level symbol's extracted body always includes its own methods, but
  a lone method's *signature* (with type-annotated parameters) can rack up
  more name-term matches than the class's own bare `class Foo:` line, and
  a class's `__init__`/dispatch code doesn't carry its methods' body-match
  credit at all -- so a helper can outscore and displace the class it
  belongs to, even though the class's window would show that same
  helper's code anyway.

  Fixed by crediting a matching parent symbol with its single
  best-matching child's score (not the sum of all matching children --
  tried that first, and it let a class with many mediocre-but-nonzero
  matching methods out-accumulate a more precisely-matching standalone
  function, regressing 2 self-benchmark tasks; reverted and used max
  instead of sum). Children are not excluded from the running -- a
  specific method can still legitimately win when nothing else in its
  class is independently relevant (verified against an existing test
  expecting exactly a method name, not its class, in the result).

  Verified: 325 tests passing (was 324), self-benchmark unchanged at the
  PR #3 baseline (92% file recall / 96% symbol recall, only the
  pre-existing `snippet`/`pack-cli` self-referential-corpus drift), and
  the original motivating case now selects `DigestAuth` directly (checked
  against the real httpx source, not the frozen holdout as a tuning loop).

  **Re-ran the frozen external holdout suite once, after the fact, as a
  one-time measurement** (not a tuning loop -- the fix above was designed
  and validated entirely against the self-benchmark, per this project's
  own discipline; this run only *observes* its effect on the suite that
  originally found the bug). Result: mean symbol recall rose from 16.7%
  to **50%** (`benchmarks/holdout-external.result.json`), file recall and
  token reduction unchanged. Three tasks flipped to full symbol recall
  (`httpx-digest-auth`, `httpx-multipart`, `zod-error-tree`), consistent
  with the parent-credit mechanism fixing genuinely the same shape of bug
  in each. But **one task regressed**: `httpx-redirects` went from 1.0 to
  0.0 symbol recall. Root cause, confirmed by direct inspection: the
  query's actual answer is a single specific method,
  `_send_handling_redirects`, and *both* of the classes containing it
  (`Client` and `AsyncClient`, httpx's sync/async twins) now score high
  enough via the parent-credit boost to take both of the file's top-2
  window slots themselves, pushing the method that was the genuinely
  correct, narrower answer out of `selected_symbols` entirely -- even
  though its source bytes are still present inside the classes' windows,
  since symbol recall here is measured by name match against
  `selected_symbols`, not byte coverage. This is a real, disclosed
  regression, not swept under the self-benchmark's unchanged numbers
  (which don't exercise the two-classes-share-one-target-method shape).

  **Fixed** -- not by re-tuning the parent-credit heuristic against this
  frozen suite, but by fixing the actual underlying correctness gap it
  exposed: a boosted parent's window already contains its credited
  child's source (a class's line range always spans its own methods), so
  the child that earned a parent its window slot is now also added to
  `selected_symbols` as a label, without spending a second window slot on
  source that's already rendered. `_symbol_windows()` no longer collapses
  windows and labels into one 1:1 list; labels can now include a
  window-less credited child. New regression test
  (`test_symbol_window_credits_shared_method_name_when_two_classes_both_win_slots`)
  reproduces the Client/AsyncClient shape synthetically and is verified,
  via git stash, to fail without this fix. Verified: 326 tests passing
  (was 325), self-benchmark still unchanged (92%/96%), and a second
  one-time re-run of the frozen holdout now shows `httpx-redirects` back
  at 1.0 with no new regressions -- **mean symbol recall 16.7% -> 66.7%**
  across the two fixes, file recall and token reduction unchanged.
  Remaining known gap on this frozen suite: `zod-flatten-error` and
  `zod-email-regex` (the disclosed, still-unfixed file-level terse-file
  ranking weakness), unrelated to symbol-window selection.

- **Attempted and reverted: a "terse implementation" file-ranking signal**
  to address the external holdout benchmark's `zod-email-regex` finding
  (a file of bare regex constants losing the file-ranking competition to a
  larger, prose-richer file merely discussing the same topic). Two
  designs were tried, each validated against this repository's own
  25-task self-benchmark (per the explicit instruction not to tune
  against the external holdout that found the weakness):
  1. A flat bonus for any query term exactly matching a defined symbol
     name. Regressed 2 self-benchmark tasks: common English words used as
     ordinary parameter/fixture names (`input`, `baseline`, `enabled`)
     got the same bonus as a genuinely rare, specific name, and
     verbosely-named test functions (whose names decompose into many
     individual word-tokens) racked up several such "matches" at once.
  2. A version requiring most of a *whole, short* (<=3-token) symbol
     name to be covered by the query, with an IDF-style discount for
     names that recur across many files. This fixed design 1's failures,
     but introduced 2 new ones: in a codebase whose actual subject matter
     is symbol/outline extraction (this one), short words like `extract`,
     `outline`, and `symbol` aren't rare identifiers -- they're the
     domain's own vocabulary, appearing as short-name components across
     many genuinely-different files, so the IDF discount wasn't steep
     enough to suppress them.

  Reverted rather than ship either regression. Root cause understood
  well enough to say why it's hard, not just that it failed: a
  file-ranking signal based on symbol-name matching alone can't
  distinguish "this name is specific to the one right answer" from "this
  name is common domain vocabulary that recurs everywhere on-topic,"
  without something like caller/import-graph or compiler-resolved
  reference signals -- which is exactly what the original diagnosis
  (CHANGELOG's frozen external holdout entry) proposed as fix #1, not
  fix #2. Left for a future attempt with that additional signal, or with
  a more conservative version of the IDF discount tuned against a fresh,
  never-seen suite rather than iterated against this one.

Note: PR #1 (`feat/index-backed-retrieval`) and PR #2
(`feat/semantic-retrieval-v2`) merged directly to `main` after 1.1.0 was cut,
adding index-backed retrieval performance, stronger JS/TS module semantics,
adaptive retrieval budgeting, provider-aware exact token counting,
multi-repository/frozen-holdout evaluation, a TypeScript-compiler semantic
overlay, and `token-saver host-check` -- without their own version bump or
CHANGELOG entry. Not re-documented here in detail; see the PR descriptions.
This entry covers only the validation work below, done against that merged
state.

- **First frozen external holdout benchmark actually executed.** The
  multi-repository/frozen-holdout infrastructure existed but had never been
  run against real, independently-authored repositories. Built a 6-task
  suite against two well-known public repos at pinned revisions --
  [encode/httpx](https://github.com/encode/httpx) `b5addb6` and
  [colinhacks/zod](https://github.com/colinhacks/zod) `59bbc03` -- with
  ground truth (target files/symbols for a natural-language query) written
  from reading the actual source before ever running the tool, then frozen
  via `--print-ground-truth-hash` and `--require-holdout`.

  Result: **83.3% mean file recall, 16.7% mean symbol recall**, ~98.5%
  estimated token reduction (`benchmarks/holdout-external.json` /
  `.result.json`). This is the honest number, not a cherry-picked one -- and
  it is materially worse on symbol recall than the tool's own repository
  self-benchmark (88-92%), which is exactly the generalization-gap risk
  freezing ground truth in advance exists to catch.

  Two disclosed, unfixed root causes (deliberately not patched against this
  frozen suite -- doing so would defeat holdout evaluation's purpose):
  1. Per-file symbol sub-ranking can pick densely-worded helper methods
     over the semantically-correct but sparser class/function the query
     was actually about (`httpx-digest-auth`: found `_auth.py` but
     selected `_parse_challenge`/`_build_auth_header` over `DigestAuth`).
  2. BM25 file ranking favors prose-rich files over terse-but-correct ones
     (`zod-email-regex`: `regexes.ts`, mostly bare regex constants, lost to
     `schemas.ts`, which merely discusses email validation in fuller
     sentences).
- **Fixed a real bug found while validating `host-check` against an actual
  live host** (not a simulated payload): spawned a genuinely separate
  `claude -p --debug-file` session (2.1.274) against a scratch project with
  Token Saver's hooks installed, and inspected its real debug log. It
  proved genuine acceptance (`Hook PostToolUse (token-saver hook) replaced
  tool output`), but `_host_evidence()`'s exact-string check
  (`"token-saver: filtered output"`) still reported no acceptance, because
  the host's own debug-log redaction independently rewrote "filtered" to
  "[REDACTED]" inside the marker text (confirmed unrelated to Token Saver:
  invoking the hook directly produces the unmangled note). Fixed by
  checking for the recovery command's generated hex id instead of exact
  prose, since nothing but Token Saver produces
  `token-saver output <32-hex-chars>` and generic redaction of the
  surrounding sentence doesn't remove it.
- **Paired coding-agent trials against real bug-fix tasks**, same model/
  prompt/revision, full-context baseline vs. Token Saver's hooks installed,
  independently verified by running the target tests directly (not by
  trusting either agent's self-report). Two trials against
  [encode/httpx](https://github.com/encode/httpx):
  1. A small, targeted fix (NO_PROXY handling in a ~500-line file).
  2. A fix requiring locating a bug in a 2019-line file
     (`httpx/_client.py`), specifically to exercise the read guard.

  **Both trials: both conditions produced the byte-for-byte identical,
  correct fix**, verified by independently running the target tests
  (`tests/test_utils.py`'s `test_get_environment_proxies`, 12/12;
  `tests/client/test_redirects.py`, 31/31) -- Token Saver's hooks do not
  change *what* gets fixed. On cost: trial 1 showed Token Saver 27% more
  expensive; trial 2 showed it 56% cheaper. Inspecting the actual hook
  debug logs (not inferring from cost alone) shows why neither number
  should be trusted as a real effect: **Token Saver's filtering/guard
  mechanism never actually activated in either trial** -- `hook.py`'s
  `main()` only writes output when there is something to filter, and in
  both trials every Read/Bash call stayed under the size thresholds that
  would trigger it. In trial 2 specifically, the agent used `Grep` to
  locate the bug directly rather than reading the whole 2019-line file,
  avoiding the expensive read the guard exists to prevent, in both
  conditions identically. The observed cost differences are inter-run
  variance in how much each independent agent run explored/re-verified
  after the fix, not a demonstrated effect of the tool.

  This is a genuine, disciplined finding, not a null result to paper over:
  across the validation done this session, Token Saver's clearest,
  best-evidenced value is in the pre-compiled context path (`pack`/
  `pack-diff` curating context up front, as in the external holdout
  benchmark and the earlier pikivo review validation) rather than the
  reactive hook-based guard/filter layer, at least for a capable agent
  doing normal file-editing work that already tends to avoid expensive
  full reads on its own. A task genuinely forcing an expensive full read or
  very verbose command output (neither of these two did) remains untested.

# 1.1.0

- Fixed `pack-diff`/`review` silently returning an empty pack (exit 0, no
  output) on large diffs: the ranking query embedded every changed
  file/symbol name uncapped, which could itself exceed `max_tokens` before
  any file content was even considered.
- Fixed a 20-30x performance cliff in impact analysis on large diffs:
  `RepositoryIndex` now caches reverse caller/neighbor/test-file indexes
  once per build instead of rescanning every record on every
  `symbol_callers()`/`neighbors()` call -- verified byte-for-byte identical
  output via differential testing against the old per-call scan.
- Fixed `pack-diff`'s changed-file boost being a no-op for a historical
  `--base` range: it only ever checked live working-tree git status, so a
  diff review never got the boost or closure-seeding it was meant to give.
- Fixed small, genuinely-modified files losing selection to large newly-added
  files at tight budgets: `build_context_pack()` now takes `priority_files`,
  which orders selection ahead of raw BM25 score (with a fair-share cap so
  one large priority file can't consume the whole budget either).
- Widened indexing beyond source code to `.sql`, `.json`, `.yaml`/`.yml`, and
  safe `.env.example`-style templates (real secret files stay blocked;
  `redact_secrets()` remains a backstop). Added dedicated extractors so
  these are real evidence with meaningful symbols -- SQL tables, npm
  scripts, CI job ids, env vars -- reusing the existing symbol/call-graph
  machinery rather than a parallel relationship-graph subsystem.
- Added budgeted evidence allocation: database/config/CI/test evidence that
  is entirely newly-added (so the priority-file mechanism can't reach it)
  gets a small, fair-share-capped budget reservation instead of competing
  purely on BM25 score against large new source files.
- Added a coverage manifest (`build_diff_context`'s `coverage` key, and a
  `# coverage: N/M changed files represented (...)` footer in `pack-diff`'s
  text output) that distinguishes selected, closure-only, policy-excluded,
  and simply-didn't-fit evidence -- so a caller can tell "nothing relevant
  here" from "this pack has a real, disclosed blind spot."
- Fixed `should_skip_dir()` excluding `.github/workflows` (and
  `.gitlab`/`.circleci`) under a blanket "starts with dot" rule -- these are
  committed, human-authored CI config, not VCS/tooling internals like `.git`
  or `.venv`.

Validated end-to-end against a real 129-file diff from a separate production
application (a private third-party codebase, not included in this
repository): reviewed independently by an isolated model instance with no
access to the source repository, at a fixed 4,000-token `pack-diff` budget,
against a full-repository-access baseline and an independently-built 15-item
ground-truth list, before any of this session's fixes existed and again
after each stage:

```
before these fixes:  pack-diff returned an empty pack (the query-size bug)
after the bug fixes:            4/15 ground-truth items, 37,306 tokens
after evidence widening:       11/15 ground-truth items, 38,186 tokens
after fair-share allocation:   12/15 ground-truth items, 37,036 tokens,
                                plus 2 findings a 100,416-token,
                                full-repository-access baseline missed
```

This is a single diff and a single reviewing model, not a statistically
validated benchmark -- no claim here generalizes beyond it. A synthetic
regression fixture reproducing the diff's key structural properties (a
genuinely modified file carrying real risk, mixed with a large batch of
newly-added source, SQL, CI, config, and test files) is checked in at
`tests/test_evidence.py::test_mixed_diff_represents_every_evidence_category_within_budget`
so these results are guarded going forward without depending on the private
repository the original diff came from.

# 1.0.0

- Added bounded, confidence-decayed dependency closure with explicit provenance.
- Replaced regex-only JS/TS definition ranges with Tree-sitter-backed exact
  function, class, method, interface, type, enum, and arrow-function spans.
- Added `pack-diff` and `review` commands for changed-symbol context, dependency
  impact, public-signature changes, removed symbols, and missing-test signals.
- Added a persistent MCP index service with `index_status`, `refresh_index`,
  `build_diff_context`, and `review_diff` alongside the v0.9 tools.
- Added paired agent-outcome evaluation. Savings claims are suppressed when the
  enabled condition does not preserve baseline task success.
- Added Codex, Claude Code, Cursor, and GitHub Actions integration artifacts.
- Added lexical normalization for common code-task inflections and structural
  terminology while retaining deterministic, inspectable scoring.
- Included benchmark: 96% file recall, 100% symbol recall, 92.94% estimated
  context reduction across 25 repository tasks at a 6,000-token cap.

# 0.9.1

- Fixed symbol selection when task vocabulary appears in a definition body but
  not its name or signature, including ambiguous CLI `main` functions.
- Hardened corrupted-cache handling, atomic index durability, and private cache
  permissions without changing the v0.9 on-disk schema.
- Made selector evaluation reproducible by excluding dirty-worktree and learned
  feedback boosts. On the expanded v0.9.1 corpus the included benchmark reports
  92% relevant-file recall and 88% relevant-symbol recall; no 100% claim is made.

# 0.9.0

- Upgraded the content-addressed index to store symbol ranges, signatures,
  parent classes, and per-symbol calls with automatic v1 cache invalidation.
- Added exact symbol-body context packing through `--target-symbol`, structured
  JSON output, selected-symbol metadata, and high-confidence secret redaction.
- Added `token-saver impact` for explainable file/symbol blast-radius analysis
  across imports, callers, and related tests.
- Added bounded local relevance feedback and a ground-truth context evaluator
  measuring file recall, symbol recall, and token reduction.
- Added a 25-task repository benchmark manifest and a dependency-free stdio MCP
  server exposing context, symbol lookup, impact, and feedback tools.
- Hardened repository scanning against sensitive paths, generated/vendor trees,
  escaping symlinks, and oversized context exposure.
- Full suite: 259 tests pass in the release environment.

# 0.8.0

- Added an incremental, content-addressed repository index. It extracts symbols,
  imports, calls, and normalized identifiers and reuses unchanged records.
- Added dependency and symbol-call graph expansion with configurable hop depth
  and distance-decayed ranking boosts.
- Added identifier-based near-duplicate suppression before context allocation.
- Added opt-in session working-set memory. Previous files are boosted only for
  follow-up queries sharing task terms, reducing stale-context carryover.
- Added optional local sentence-transformer reranking through the `embeddings`
  extra. Default behavior remains deterministic and dependency-free.
- Added atomic persistence for indexes and working sets, CLI controls, ranking
  explanations, and regression tests for every new subsystem.
- Full suite: 250 tests pass on Python 3.12 in the release environment.

# 0.7.0

- Added task-aware context packing with `token-saver pack` and the standalone
  `token-saver-pack` entry point.
- Added dependency-free BM25-style source ranking with stronger path and symbol
  weights, Git working-tree/staged-file boosts, and structural-priority fallback.
- Context packs combine compact outlines with exact line-numbered source windows
  around high-signal task matches instead of summarizing editable code.
- Added hard estimated-token caps, file-count/window controls, Git-ignore support,
  ranking explanations, and output-to-file support.
- Added conservative compression of consecutive duplicate lines in successful
  command output while keeping failures and diagnostics untouched.
- Added CI on Python 3.10 and 3.12 and regression coverage for relevance ranking,
  budget enforcement, exact source windows, dispatcher compatibility, JSON
  compaction, and failure preservation.
- Kept all 0.6 lifecycle, audit, recovery, source-read, and benchmark behavior;
  the new top-level dispatcher isolates `pack` from the mature legacy CLI.

Token Saver still does not claim a universal end-to-end savings percentage.
Task success and paired-run measurements remain the standard for savings claims.

# 0.6.0

- Corrected Bash replacement to the documented structured `updatedToolOutput`
  contract. Unsupported/image/interrupted outputs pass through.
- Preserved stderr and failure diagnostics. Shortened outputs are saved privately
  and recoverable by ID/range, without re-executing commands. Saving failures
  leave original output visible. Added `output` and `outputs-prune` commands.
- Scoped read state by project and session, with locked read-modify-write
  transactions, unique temporary files and atomic replacement. Compaction resets
  are installed. Only verified full-read contents are recorded.
- Removed the Stop hook's reliance on undocumented usage fields. Lifecycle advice
  remains based on explicit transcript analysis, not invented live usage.
- Tightened Read ranges: offsets alone and oversized/invalid limits no longer
  bypass the context budget. Relative paths resolve against the hook project.
- Replaced JS/TS snippet boundaries with Tree-sitter, added qualified names and
  ambiguity errors, removed silent 120-line truncation, and improved outlines.
- Excluded first cache observations and compaction epochs from suspected
  recreation. Reported only suspected overlapping prefixes, not all new tokens.
- Scoped repeated-read analysis by session and compaction epoch; stopped
  describing every repeat as waste. Preserved final streaming usage totals.
- Added explicit model/TTL pricing, with incomplete-cost results for unknown
  prices or TTLs. Unknown image sizes no longer use base64 length as token cost.
- Added paired-run benchmark evaluation including failed-attempt costs and
  quality outcomes. Removed historical savings percentages and absolute-ceiling
  claims without reproducible supporting data.
- Made settings updates atomic and refused malformed settings; preserved
  unrelated hooks sharing a matcher. Updated templates and upgrade guidance.

Validation: regression tests cover these fixes and subprocess hook transport.
See VALIDATION.md for executed results. A live Claude Code integration run and
real-task savings benchmark remain unexecuted; BENCHMARKING.md supplies the
protocol. The Windows locking branch is implemented but was not run on Windows.
