from __future__ import annotations

import textwrap

from acco.closure import dependency_closure
from acco.pack import build_context_pack, rank_files
from acco.repo_index import build_index
from acco.syntax import symbols


def test_exported_data_constant_is_indexed_without_value_in_signature():
    found = {symbol.name: symbol for symbol in symbols(
        "const local = /local/;\nexport const email: RegExp = /@example\\.com$/;\n",
        ".ts",
    )}

    assert "local" not in found
    assert "email" in found
    assert "@example" not in found["email"].signature


def test_semantic_ref_promotes_terse_provider_without_global_size_penalty(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "patterns.ts").write_text(
        "export const slug = /^[a-z0-9-]+$/;\n",
        encoding="utf-8",
    )
    (src / "validator.ts").write_text(
        textwrap.dedent(
            """
            import * as patterns from "./patterns.js";

            export function validateSlug(value: string) {
              const activePattern = patterns.slug;
              return activePattern.test(value);
            }
            """
        ),
        encoding="utf-8",
    )
    for n in range(8):
        (src / f"slug_docs_{n}.ts").write_text(
            "// validate slug string schema request address format\n"
            f"export function describeSlug{n}() {{ return 'slug validation schema'; }}\n",
            encoding="utf-8",
        )

    ranked = rank_files(
        tmp_path,
        "validate slug string schema request",
        changed_boost=False,
        seed_limit=6,
    )

    top = ranked[:3]
    assert "src/patterns.ts" in {item.rel for item in top}
    provider = next(item for item in top if item.rel == "src/patterns.ts")
    assert any(reason.startswith("graph:semantic-ref@1") for reason in provider.reasons)


def test_semantic_ref_is_strong_but_does_not_expand_transitively(tmp_path):
    (tmp_path / "a.ts").write_text(
        'import { policy } from "./b.js";\nexport const current = policy;\n',
        encoding="utf-8",
    )
    (tmp_path / "b.ts").write_text(
        'import { limit } from "./c.js";\nexport const policy = limit;\n',
        encoding="utf-8",
    )
    (tmp_path / "c.ts").write_text("export const limit = 10;\n", encoding="utf-8")

    index = build_index(tmp_path, persist=False)
    closure = dependency_closure(index, ["a.ts"], max_hops=2, max_items=20)

    by_path = {item.path: item for item in closure}
    assert by_path["b.ts"].reason == "semantic-ref"
    assert by_path["b.ts"].distance == 1
    assert "c.ts" not in by_path


def test_emitted_js_specifier_prefers_real_js_file_when_it_exists(tmp_path):
    (tmp_path / "consumer.ts").write_text(
        'import { policy } from "./provider.js";\nexport const current = policy;\n',
        encoding="utf-8",
    )
    (tmp_path / "provider.js").write_text("export const policy = 'js';\n", encoding="utf-8")
    (tmp_path / "provider.ts").write_text("export const policy = 'ts';\n", encoding="utf-8")

    index = build_index(tmp_path, persist=False)
    closure = dependency_closure(index, ["consumer.ts"], max_hops=1, max_items=20)
    by_path = {item.path: item for item in closure}

    assert by_path["provider.js"].reason == "semantic-ref"
    assert "provider.ts" not in by_path


def test_exact_value_ref_is_not_hidden_by_an_unrelated_call_to_same_provider(tmp_path):
    (tmp_path / "consumer.ts").write_text(
        textwrap.dedent(
            """
            import * as provider from "./provider.js";
            export const currentPattern = provider.email;
            export function run() { return provider.helper(); }
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "provider.ts").write_text(
        "export const email = /@/;\nexport function helper() { return true; }\n",
        encoding="utf-8",
    )

    index = build_index(tmp_path, persist=False)
    closure = dependency_closure(index, ["consumer.ts"], max_hops=1, max_items=20)
    by_path = {item.path: item for item in closure}

    assert by_path["provider.ts"].reason == "semantic-ref"
    assert by_path["provider.ts"].confidence == 3.5


def test_context_pack_reserves_budget_for_exact_provider_behind_large_consumer(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "patterns.ts").write_text(
        "export const slug = /^[a-z0-9-]+$/;\n",
        encoding="utf-8",
    )
    helpers = "\n".join(
        f"export function validateSlugSchemaHelper{n}(value: string) {{ return value.length > {n}; }}"
        for n in range(100)
    )
    (src / "validator.ts").write_text(
        textwrap.dedent(
            """
            import * as patterns from "./patterns.js";
            export function validateSlug(value: string) {
              const activePattern = patterns.slug;
              return activePattern.test(value);
            }
            """
        )
        + helpers
        + "\n",
        encoding="utf-8",
    )
    # Keep the tiny provider outside the adaptive budget's lexical seed set,
    # so it has to be recovered via the validator's exact semantic reference.
    for n in range(5):
        (src / f"validate_slug_schema_request_{n}.ts").write_text(
            "// validate slug string schema request format address\n"
            f"export function validateSlugSchemaRequest{n}(value: string) {{ return value.length > 0; }}\n",
            encoding="utf-8",
        )

    pack = build_context_pack(
        tmp_path,
        "validate slug string schema request",
        max_tokens=1200,
        changed_boost=False,
        persist_index=False,
    )

    assert "src/validator.ts" in pack.selected_files
    assert "src/patterns.ts" in pack.selected_files
    provider = next(item for item in pack.ranked if item.rel == "src/patterns.ts")
    assert any(reason.startswith("graph:semantic-ref@1") for reason in provider.reasons)
