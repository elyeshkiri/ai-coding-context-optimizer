"""Self-contained local HTML rendering for session-efficiency reports."""

from __future__ import annotations

from html import escape


def _number(value: object) -> str:
    """Format one token or event count for display."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "0"
    number = float(value)
    if abs(number) >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"{number / 1_000:.1f}K"
    return f"{number:.0f}"


def _rows(items: dict) -> str:
    """Render a deterministic two-column metric table body."""
    if not items:
        return '<tr><td colspan="2">No events recorded</td></tr>'
    return "".join(
        "<tr><td>"
        + escape(str(key).replace("_", " "))
        + "</td><td>"
        + escape(_number(value))
        + "</td></tr>"
        for key, value in sorted(items.items())
    )


def render_dashboard_html(report: dict) -> str:
    """Render one dashboard report as a dependency-free local HTML document."""
    savings = report.get("savings", {})
    continuity = report.get("continuity", {})
    behavior = report.get("behavior", {})
    usage = report.get("billed_usage", {})
    days = report.get("window_days", 0)
    total_saved = savings.get("estimated_tool_context_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    input_tokens = usage.get("input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    behavior_events = behavior.get("events", 0)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ACCO Dashboard</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 1100px; margin: 0 auto;
       padding: 32px 20px; line-height: 1.45; }}
h1 {{ margin-bottom: 4px; }}
.muted {{ opacity: .7; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(180px,1fr));
          gap: 12px; margin: 24px 0; }}
.card {{ border: 1px solid currentColor; border-radius: 10px; padding: 16px; }}
.value {{ font-size: 1.8rem; font-weight: 700; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(300px,1fr));
         gap: 20px; }}
section {{ border: 1px solid currentColor; border-radius: 10px; padding: 18px; }}
table {{ width: 100%; border-collapse: collapse; }}
td {{ border-top: 1px solid currentColor; padding: 8px 4px; }}
td:last-child {{ text-align: right; font-variant-numeric: tabular-nums; }}
.note {{ margin-top: 24px; padding: 14px; border: 1px solid currentColor;
         border-radius: 10px; }}
</style>
</head>
<body>
<h1>ACCO Dashboard</h1>
<div class="muted">Local operational telemetry · last {escape(str(days))} days</div>
<div class="cards">
  <div class="card"><div>Estimated tool-context saved</div>
    <div class="value">{escape(_number(total_saved))}</div><div>tokens</div></div>
  <div class="card"><div>Observed fresh input</div>
    <div class="value">{escape(_number(input_tokens))}</div><div>tokens</div></div>
  <div class="card"><div>Observed cache reads</div>
    <div class="value">{escape(_number(cache_read))}</div><div>tokens</div></div>
  <div class="card"><div>Observed output</div>
    <div class="value">{escape(_number(output_tokens))}</div><div>tokens</div></div>
  <div class="card"><div>Behavior signals</div>
    <div class="value">{escape(_number(behavior_events))}</div><div>events</div></div>
  <div class="card"><div>Continuity restores</div>
    <div class="value">{escape(_number(continuity.get("restores", 0)))}</div>
    <div>events</div></div>
</div>
<div class="grid">
<section><h2>Estimated savings by feature</h2>
<table>{_rows(savings.get("by_feature", {}))}</table></section>
<section><h2>Behavioral waste signals</h2>
<table>{_rows(behavior.get("signals", {}))}</table></section>
<section><h2>Observed billed usage</h2>
<table>{_rows({
    "fresh_input": usage.get("input_tokens", 0),
    "cache_creation": usage.get("cache_creation_input_tokens", 0),
    "cache_read": usage.get("cache_read_input_tokens", 0),
    "output": usage.get("output_tokens", 0),
    "model_calls": usage.get("model_calls", 0),
})}</table></section>
<section><h2>Continuity</h2>
<table>{_rows({
    "restores": continuity.get("restores", 0),
    "tracked_sessions": continuity.get("tracked_sessions", 0),
})}</table></section>
</div>
<div class="note"><strong>Evidence boundary.</strong>
{escape(str(report.get("evidence", {}).get("note", "")))}
Estimated savings are not billed-dollar claims.</div>
</body>
</html>
"""
