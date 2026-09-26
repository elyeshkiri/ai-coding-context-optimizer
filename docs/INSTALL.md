# Installation

ACCO's default install path is intentionally short:

```bash
uv tool install acco
cd /path/to/project
acco setup
acco start
```

`uv` keeps ACCO isolated from project virtual environments and gives
`acco update` a clean upgrade path.

## One-off bootstrap

Use `uvx` when you want to configure a project before deciding whether to
keep a global ACCO command:

```bash
cd /path/to/project
uvx acco setup
```

## pipx

```bash
pipx install acco
acco setup
```

## pip compatibility path

```bash
python -m pip install --upgrade acco
acco setup
```

This remains fully supported, but isolated CLI installers are preferred because
they avoid project-environment and PATH confusion.

## Claude Code marketplace

Claude Code 2.1.229+ can install ACCO's generated plugin directly:

```text
/plugin marketplace add elyeshkiri/ai-coding-context-optimizer
/plugin install acco@acco-tools
```

The plugin contains ACCO hooks, MCP integration, Compaction Guardian support,
the ingress skill, and ACCO Lean.

## Standalone release binaries

Tagged releases publish smoke-tested single-file executables:

- `acco-linux-x86_64`
- `acco-macos-arm64`
- `acco-windows-x86_64.exe`

Each binary has a matching SHA-256 sidecar. These binaries are built from the
release tag and run `acco --help` plus a provider-free `acco demo` smoke test
before upload.

Linux/macOS users can use the repository installer after a release containing
standalone assets:

```bash
curl -fsSL https://raw.githubusercontent.com/elyeshkiri/ai-coding-context-optimizer/main/scripts/install-standalone.sh | sh
```

This path is optional. Review the script first if your environment does not
permit piped shell installers.

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/elyeshkiri/ai-coding-context-optimizer/main/scripts/install-standalone.ps1 | iex
```

Both installers verify the downloaded SHA-256 checksum before installation.

## Homebrew without a tap

Tagged releases also publish an `acco.rb` formula generated from the verified
standalone checksums. Install the latest release formula directly:

```bash
brew install --formula \
  https://github.com/elyeshkiri/ai-coding-context-optimizer/releases/latest/download/acco.rb
```

A short `brew install acco` requires acceptance into Homebrew core or a
separate tap repository; ACCO does not pretend that namespace exists when it
does not.

## Upgrade and repair

Inspect the package-manager command ACCO would use:

```bash
acco update
```

Apply it explicitly:

```bash
acco update --apply
acco setup
```

`setup` is idempotent and doubles as the integration repair/migration command.
It also refreshes the structural index and verifies readiness.

## Remove

```bash
acco uninstall . --host all
acco uninstall . --host all --remove-config
```

Only ACCO-owned integration entries are removed.
