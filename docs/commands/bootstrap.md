# `acco bootstrap`

Persistently install ACCO with an isolated CLI package manager, then configure
and verify the current project.

## Synopsis

```bash
acco bootstrap [path] [--host HOST ...] [--no-index] [--no-lean]
```

The intended one-command entry is:

```bash
uvx acco bootstrap
```

## Arguments and options

- `path` — project root; defaults to `.`.
- `--host` — repeat to select explicit coding-agent integrations.
- `--no-index` — skip setup's structural-index warm-up.
- `--no-lean` — skip the managed Claude Lean skill.

Bootstrap requires `uv` or `pipx`. It first installs/upgrades ACCO
persistently using that isolated CLI manager, then invokes the normal
`acco setup` workflow. This prevents host integration files from depending on
the temporary environment used by `uvx`.

## Exit codes

- returns setup's exit code after a successful persistent package installation.
- `2` — neither `uv` nor `pipx` is available.
- otherwise returns the package manager's nonzero exit code when persistent
  installation fails.

## Output contract

Text mode reports which persistent installer succeeded, then emits the ordinary
setup/readiness output. Package-manager stdout is suppressed on success to keep
the first-run output concise; failed installer stdout/stderr is surfaced.

## Authoritative runtime help

Run `acco bootstrap --help` for the installed version.
