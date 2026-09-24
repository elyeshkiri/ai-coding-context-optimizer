# `acco sdk-serve`

Run the local versioned SDK bridge for TypeScript and other non-Python custom
agents.

## Synopsis

```bash
acco sdk-serve [path] [--bind IP] [--port PORT] [--recovery-capacity-mb N]
               [--allow-non-loopback]
```

## Arguments and options

- `path` — project root used for recovery/prefix state; default current directory.
- `--bind IP` — bind address; default `127.0.0.1`.
- `--port PORT` — TCP port; default `8770`.
- `--recovery-capacity-mb N` — exact-recovery capacity; default 512 MiB.
- `--allow-non-loopback` — allow binding beyond loopback. ACCO does not add
  remote authentication/TLS, so use this only behind your own access controls.

The service exposes `/v1/health`, `/v1/provider/optimize`,
`/v1/context/optimize`, `/v1/output/optimize`, `/v1/route`, and
`/v1/recover`. Request content is not written to access logs.

See [Middleware SDKs](../SDK.md) for Python and TypeScript examples.

## Exit codes

- `0` — service stopped normally by interrupt.
- `2` — invalid root/bind/port/capacity or server startup error.

## Output contract

This is a long-running HTTP service rather than a one-shot JSON command. The
versioned JSON endpoint contracts are documented in [Middleware SDKs](../SDK.md).

The bridge binds to loopback by default. Exact recovery remains project-scoped
and uses ACCO's existing content-addressed recovery store.

## Authoritative runtime help

Run `acco sdk-serve --help` for argparse's exact usage text for the installed version.
