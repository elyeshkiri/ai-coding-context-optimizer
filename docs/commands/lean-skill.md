# `acco lean-skill`

Print or install ACCO's portable terse-output skill.

```bash
acco lean-skill
acco lean-skill . --install --host claude
acco lean-skill . --install --host agents
acco lean-skill . --install --host all
```

`--host claude` writes `.claude/skills/acco-lean/SKILL.md`.
`--host agents` writes `.agents/skills/acco-lean/SKILL.md`.

Existing non-ACCO content is not overwritten unless `--force` is supplied.
Lean mode controls final prose only. It explicitly preserves investigation,
verification, required code/diffs, diagnostics, safety information, and
material caveats.
