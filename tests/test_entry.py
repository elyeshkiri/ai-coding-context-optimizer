import json
import json
import textwrap

from token_saver.entry import main


def test_dispatcher_preserves_legacy_commands(capsys):
    assert main(["budget", ".", "--window", "1000", "--no-user-scope"]) == 0
    assert "TOTAL_PLANNED" in capsys.readouterr().out


def test_dispatcher_exposes_pack(tmp_path, capsys):
    (tmp_path / "auth.py").write_text(textwrap.dedent("""
        def refresh_session(token: str) -> str:
            return rotate_token(token)
    """))
    assert main([
        "pack", str(tmp_path), "--query", "refresh session", "--max-tokens", "500"
    ]) == 0
    out = capsys.readouterr().out
    assert "TOKEN-SAVER CONTEXT PACK" in out
    assert "auth.py" in out


def test_dispatcher_exposes_output_policy(capsys):
    assert main(["output-policy", "--mode", "terse", "--max-tokens", "250"]) == 0
    out = capsys.readouterr().out
    assert "target <= 250 tokens" in out
    assert "Do not restate the task" in out


def test_dispatcher_exposes_output_save(tmp_path, capsys):
    response = tmp_path / "response.txt"
    response.write_text(
        "Sure!\n\nImplemented.\n\nImplemented.\n",
        encoding="utf-8",
    )
    assert main(["output-save", str(response), "--mode", "terse"]) == 0
    out = capsys.readouterr().out
    assert "Sure!" not in out
    assert out.count("Implemented.") == 1



def test_dispatcher_exposes_context_browser(tmp_path, capsys):
    (tmp_path / "views.py").write_text(textwrap.dedent("""
        def renderTemplate(template):
            return template
    """))
    assert main([
        "browse", str(tmp_path), "--query", "rendr template",
        "--max-files", "3", "--no-changed-boost",
    ]) == 0
    out = capsys.readouterr().out
    assert "CONTEXT BROWSER" in out
    assert "views.py" in out
    assert "renderTemplate" in out



def test_dispatcher_exposes_output_benchmark(tmp_path, capsys):
    manifest = tmp_path / "output.json"
    manifest.write_text(json.dumps({
        "cases": [{
            "id": "duplicate",
            "text": "Done.\n\nDone.\n",
            "mode": "terse",
        }]
    }))

    assert main(["output-benchmark", str(manifest)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["case_count"] == 1
    assert payload["cases"][0]["removed_units"] >= 1



def test_dispatcher_exposes_cost_report(tmp_path, capsys):
    baseline = tmp_path / "baseline.json"
    optimized = tmp_path / "optimized.json"
    baseline.write_text(json.dumps([{
        "task_id": "task", "success": True,
        "input_tokens": 1000, "output_tokens": 200, "cost_usd": 1.0,
    }]))
    optimized.write_text(json.dumps([{
        "task_id": "task", "success": True,
        "input_tokens": 400, "output_tokens": 100, "cost_usd": 0.4,
    }]))

    assert main(["cost-report", str(baseline), str(optimized)]) == 0
    out = capsys.readouterr().out
    assert "PAIRED TASKS: 1" in out
    assert "cost/success:" in out
    assert "60.0% reduction" in out



def test_cost_report_accepts_single_paired_agent_manifest(tmp_path, capsys):
    manifest = tmp_path / "agent-runs.json"
    manifest.write_text(json.dumps({
        "runs": [
            {
                "task": "task", "condition": "baseline", "success": True,
                "input_tokens": 1000, "output_tokens": 200,
                "seconds": 2.0, "cost_usd": 1.0,
            },
            {
                "task": "task", "condition": "token-saver", "success": True,
                "input_tokens": 400, "output_tokens": 100,
                "seconds": 1.0, "cost_usd": 0.4,
            },
        ]
    }), encoding="utf-8")

    assert main(["cost-report", str(manifest)]) == 0
    out = capsys.readouterr().out
    assert "PAIRED TASKS: 1" in out
    assert "60.0% reduction" in out
