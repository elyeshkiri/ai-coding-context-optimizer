# `acco browser-context`

Compress a captured HTML or accessibility-like payload around a task query.

## Synopsis

```bash
acco browser-context INPUT [--path PROJECT] [--query TEXT] [--max-lines N] [--json]
```

## Arguments and options

- `INPUT` — local captured HTML/text file, or `-` for stdin.
- `--path PROJECT` — project root used for exact recovery storage.
- `--query TEXT` — focus terms used to retain nearby visible/actionable context.
- `--max-lines N` — maximum focused lines; default 120.
- `--json` — emit transformation metadata and compressed text.

`auto` recognizes HTML, accessibility/ARIA snapshots, and browser-shaped JSON such as role/name/children trees or embedded AX snapshots. It keeps query neighborhoods plus a bounded structural/actionable skeleton, strips hidden/script/style HTML noise, and preserves useful control state such as labels, values, checked/selected/expanded state, headings, landmarks, links, and buttons. Ordinary JSON is not treated as browser JSON.\n\nThis command never fetches a URL, executes page JavaScript, or takes screenshots.

## Exit codes

`0` payload processed; `2` invalid input or I/O error.

## Output contract

A smaller result includes a `tsr_...` exact-recovery handle. If focused output
is not smaller, the original payload is returned unchanged.

## Authoritative runtime help

Run `acco browser-context --help` for the installed version.
