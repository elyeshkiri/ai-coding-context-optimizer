from __future__ import annotations

import textwrap

from token_saver.closure import dependency_closure
from token_saver.pack import rank_files
from token_saver.repo_index import build_index


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
