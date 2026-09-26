# `acco completion`

Generate top-level shell completion.

## Synopsis

```bash
acco completion <bash|zsh|fish|powershell>
```

## Arguments and options

- `shell` is one of `bash`, `zsh`, `fish`, `powershell`.

## Exit codes

`0` success; argparse usage errors exit `2`.

## Output contract

Shell source on stdout. PowerShell output uses `Register-ArgumentCompleter -Native` and can be added to the user's PowerShell profile.

## Authoritative runtime help

Run `acco completion --help` for argparse's exact usage text for the installed version.
