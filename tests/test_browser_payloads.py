"""Tests for specialized browser/context payload optimization."""

from __future__ import annotations

import json

from acco.browser_context import (
    compress_browser_payload,
    detect_browser_payload_kind,
)
from acco.context_router import detect_context_kind, route_context
from acco.recovery import RecoveryStore


def _root(tmp_path, monkeypatch):
    """Create an isolated project and recovery state."""
    monkeypatch.setenv("ACCO_STATE_DIR", str(tmp_path / "state"))
    root = tmp_path / "repo"
    root.mkdir()
    return root


def test_ax_snapshot_focus_keeps_target_and_actionable_controls(
    tmp_path, monkeypatch
):
    """AX text should retain query evidence plus a bounded actionable skeleton."""
    root = _root(tmp_path, monkeypatch)
    lines = [
        '- navigation "Primary"',
        '- link "Home" [ref=e1]',
        '- link "Orders" [ref=e2]',
        '- main',
        '- heading "Orders" [level=1]',
    ]
    for index in range(180):
        lines.append(f'- row "ORD-{index:04d} Status {index}"')
    lines.extend([
        '- button "Save order" [ref=e500]',
        '- button "Cancel" [ref=e501]',
    ])
    text = "\n".join(lines)

    result = compress_browser_payload(
        text,
        query="ORD-0173 save",
        max_lines=30,
        recovery=RecoveryStore(root),
    )

    assert result.kind == "ax"
    assert result.changed is True
    assert "ORD-0173" in result.text
    assert 'button "Save order"' in result.text
    assert result.interactive_items >= 1
    assert result.source_items > result.shown_items
    assert RecoveryStore(root).get(result.recovery_handle).payload.decode() == text


def test_browser_json_snapshot_is_flattened_semantically_and_recoverable(
    tmp_path, monkeypatch
):
    """Browser tree JSON should focus semantic nodes rather than generic list samples."""
    root = _root(tmp_path, monkeypatch)
    children = [
        {
            "role": "row",
            "name": f"ORD-{index:04d} Status {index}",
            "children": [
                {"role": "cell", "name": f"ORD-{index:04d}"},
                {"role": "cell", "name": f"Status {index}"},
            ],
        }
        for index in range(160)
    ]
    children.append(
        {
            "role": "button",
            "name": "Save order",
            "disabled": False,
        }
    )
    payload = {
        "accessibility": {
            "role": "main",
            "name": "Orders",
            "children": children,
        }
    }
    text = json.dumps(payload, indent=2)

    assert detect_browser_payload_kind(text) == "json"
    result = compress_browser_payload(
        text,
        query="ORD-0127 save",
        max_lines=32,
        recovery=RecoveryStore(root),
    )

    assert result.changed is True
    assert result.kind == "json"
    assert "ORD-0127" in result.text
    assert "Save order" in result.text
    assert '"children"' not in result.text
    assert result.output_tokens < result.original_tokens
    assert RecoveryStore(root).get(result.recovery_handle).payload.decode() == text


def test_hidden_html_noise_is_not_promoted_into_focused_context(
    tmp_path, monkeypatch
):
    """Hidden/script content should not beat visible actionable browser evidence."""
    root = _root(tmp_path, monkeypatch)
    html = (
        "<html><body>"
        "<script>SECRET_SCRIPT_NOISE " + "x" * 5000 + "</script>"
        "<div hidden>HIDDEN_SECRET " + "y" * 3000 + "</div>"
        "<main><h1>Checkout</h1>"
        "<button aria-label='Save order'>Save</button>"
        "<p>Order ORD-0042 ready</p></main>"
        "</body></html>"
    )

    result = compress_browser_payload(
        html,
        query="ORD-0042 save",
        max_lines=20,
        recovery=RecoveryStore(root),
    )

    assert result.changed is True
    assert "ORD-0042" in result.text
    assert "Save order" in result.text
    assert "SECRET_SCRIPT_NOISE" not in result.text
    assert "HIDDEN_SECRET" not in result.text


def test_generic_json_does_not_get_browser_specialization(tmp_path, monkeypatch):
    """Ordinary JSON should remain on the general context-router path."""
    root = _root(tmp_path, monkeypatch)
    text = json.dumps(
        {
            "items": [
                {"id": index, "name": f"entry-{index}", "detail": "noise " * 20}
                for index in range(80)
            ]
        }
    )

    assert detect_browser_payload_kind(text) == "text"
    assert detect_context_kind(text) == "json"
    result = route_context(
        text,
        query="entry-44",
        recovery=RecoveryStore(root),
        min_reduction=0.05,
    )
    assert result.kind == "json"
    assert result.changed is True


def test_context_router_auto_selects_browser_ax_and_browser_json(
    tmp_path, monkeypatch
):
    """Generic tool-result routing should specialize only recognized browser payloads."""
    root = _root(tmp_path, monkeypatch)
    store = RecoveryStore(root)
    ax = "\n".join(
        [f'- button "Action {index}" [ref=e{index}]' for index in range(120)]
    )
    browser_json = json.dumps(
        {
            "snapshot": {
                "role": "main",
                "name": "Page",
                "children": [
                    {"role": "link", "name": f"Product {index}"}
                    for index in range(120)
                ],
            }
        }
    )

    assert detect_context_kind(ax) == "browser-ax"
    ax_result = route_context(
        ax,
        query="Action 77",
        recovery=store,
        max_lines=24,
        min_reduction=0.05,
    )
    assert ax_result.kind == "browser-ax"
    assert ax_result.metadata["browser_kind"] == "ax"
    assert "Action 77" in ax_result.text

    assert detect_context_kind(browser_json) == "browser-json"
    json_result = route_context(
        browser_json,
        query="Product 88",
        recovery=store,
        max_lines=24,
        min_reduction=0.05,
    )
    assert json_result.kind == "browser-json"
    assert json_result.metadata["browser_kind"] == "json"
    assert "Product 88" in json_result.text


def test_browser_min_tokens_preserves_small_payload_without_recovery(
    tmp_path, monkeypatch
):
    """Explicit size gating should leave small browser payloads byte-for-byte unchanged."""
    root = _root(tmp_path, monkeypatch)
    text = '<html><body><button>Save</button></body></html>'

    result = compress_browser_payload(
        text,
        query="save",
        min_tokens=500,
        recovery=RecoveryStore(root),
    )

    assert result.kind == "html"
    assert result.changed is False
    assert result.text == text
    assert result.recovery_handle is None
