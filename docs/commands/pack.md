# `acco pack`

Build a task-aware bounded source context pack.

## Synopsis

```bash
acco pack [path] [-q|--query TEXT] [--max-tokens N] [--max-files N] [--context-lines N] [--no-gitignore] [--no-changed-boost] [--graph-hops N] [--closure-items N] [--duplicate-threshold F] [--session ID] [--embeddings|--semantic] [--typescript-semantic] [--strict-semantic] [--no-index-cache] [--no-retrieval-cache] [--target-symbol NAME] [--json] [--explain] [-o FILE]
```

## Arguments and options

- `path` default `.`; query default empty.
- Defaults: max tokens `6000`, max files `12`, context lines `6`, graph hops `1`, closure items `20`, duplicate threshold `0.92`.
- `--session` preserves working-set continuity.
- `--embeddings` / `--semantic` enables persistent chunk-level semantic retrieval plus bounded lexical/vector rank fusion using an already-downloaded local model. The final pack still renders live exact source windows.
- `--typescript-semantic` enables compiler-resolved JS/TS edges.
- `--strict-semantic` refuses semantic fallback.
- `--no-index-cache` disables persistent repository-index reuse.
- `--no-retrieval-cache` bypasses the completed-pack cache for this invocation.
- `--target-symbol` prioritizes one exact symbol.
- `--json` emits metadata + text; `--explain` writes scores to stderr; `-o` writes output.

## Exit codes

`0` success; `1` invalid path; `2` ranking/semantic/configuration failure.

## Output contract

Context text or JSON; see [Machine-readable contracts](../JSON_OUTPUTS.md#pack-json).

## Authoritative runtime help

Run `acco pack --help` for argparse's exact usage text for the installed version.
