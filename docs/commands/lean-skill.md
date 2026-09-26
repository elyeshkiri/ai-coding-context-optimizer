# `acco lean-skill`

Print or install ACCO's portable terse-output skill.

## Synopsis

```bash
acco lean-skill [path] [--install] [--host claude|agents|all] [--force] [--json]
```

## Arguments and options

- `path` — project root; defaults to `.`.
- `--install` — write the skill instead of printing it.
- `--host claude|agents|all` — target `.claude/skills`, portable `.agents/skills`, or both.
- `--force` — allow replacement when a different file already occupies ACCO's skill path.
- `--json` — emit installed paths as JSON in install mode.

Without `--install`, the canonical skill body is printed to stdout. Lean mode
controls final prose only and explicitly preserves investigation,
verification, required code/diffs, diagnostics, safety information, and
material caveats.

## Exit codes

- `0` — skill printed or installed.
- `2` — invalid options, unsupported host, filesystem failure, or protected existing content.

## Output contract

Print mode emits exactly the maintained ACCO Lean skill text. Install JSON mode
returns `{"installed": [...]}`. Existing non-ACCO content is not overwritten
unless `--force` is supplied.

## Authoritative runtime help

Run `acco lean-skill --help` for the installed version.
