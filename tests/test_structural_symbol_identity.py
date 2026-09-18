import json
import textwrap

from token_saver.evaluate import evaluate_manifest, ground_truth_hash
from token_saver.pack import build_context_pack


def test_qualified_parent_terms_disambiguate_same_named_methods(tmp_path):
    source = textwrap.dedent("""
        namespace Demo {
            class AuditLogger {
                public void Information(string message) {
                    Emit(message);
                }
            }

            class UserLogger {
                public void Information(string message) {
                    Emit(message);
                }
            }
        }
    """)
    (tmp_path / "loggers.cs").write_text(source)

    pack = build_context_pack(
        tmp_path,
        "UserLogger information message",
        max_tokens=700,
        changed_boost=False,
    )

    assert any(
        identity.startswith("loggers.cs:UserLogger.Information@")
        for identity in pack.selected_symbol_identities
    )


def test_qualified_symbol_evaluation_is_opt_in_and_source_visible(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "service.py").write_text(textwrap.dedent("""
        class AdminService:
            def run(self):
                return "admin"

        class UserService:
            def run(self):
                return "user"
    """))
    manifest = tmp_path / "holdout.json"
    payload = {
        "repositories": {"repo": "repo"},
        "tasks": [{
            "id": "qualified",
            "repository": "repo",
            "query": "UserService run user",
            "files": ["service.py"],
            "symbols": ["run"],
            "qualified_symbols": ["service.py:UserService.run"],
            "max_tokens": 800,
        }],
        "protocol": {
            "ground_truth_frozen": True,
            "development_excluded": True,
            "frozen_at": "2026-09-18T12:45:00Z",
        },
    }
    payload["protocol"]["ground_truth_sha256"] = ground_truth_hash(payload)
    manifest.write_text(json.dumps(payload))

    result = evaluate_manifest(
        tmp_path, manifest, max_tokens=800, require_holdout=True
    )
    task = result["tasks"][0]
    assert task["symbol_recall"] == 1.0
    assert task["qualified_symbol_recall"] == 1.0
    assert result["summary"]["mean_qualified_symbol_recall"] == 1.0


def test_legacy_holdout_hash_does_not_gain_implicit_qualified_field():
    payload = {
        "suite_version": 1,
        "repositories": {},
        "tasks": [{
            "id": "legacy",
            "query": "handler",
            "files": ["handler.py"],
            "symbols": ["handle"],
            "max_tokens": 6000,
        }],
    }
    without = ground_truth_hash(payload)
    explicit = json.loads(json.dumps(payload))
    explicit["tasks"][0]["qualified_symbols"] = []
    with_empty = ground_truth_hash(explicit)

    assert without != with_empty
