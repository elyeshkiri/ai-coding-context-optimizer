from token_saver import pack as pack_module
from token_saver.pack import rank_files


def _reasons(ranked, rel):
    return next(item.reasons for item in ranked if item.rel == rel)


def _authority(reasons):
    for reason in reasons:
        if reason.startswith("structural-symbol:"):
            return float(reason.split(":", 1)[1])
    return 0.0


def _generic_repo(root):
    # `get`/`add` are defined in many files: ubiquitous API vocabulary.
    for n in range(6):
        (root / f"mod{n}.py").write_text(
            "def get(key):\n    return key\n\ndef add(a, b):\n    return a + b\n"
        )
    (root / "redirects.py").write_text(
        "def resolve_redirects(response):\n    return response\n"
    )


def test_generic_callable_names_do_not_grant_structural_authority(tmp_path):
    # Regression: a plain query containing "get"/"add" boosted every file that
    # defined a same-named helper by +20..+54, which on real repositories meant
    # 5/70 (requests) and 18/101 (flask) files, tests and examples included.
    _generic_repo(tmp_path)

    ranked = rank_files(
        tmp_path, "how do I get a value and add it to the total", changed_boost=False,
    )

    for n in range(6):
        assert _authority(_reasons(ranked, f"mod{n}.py")) == 0.0


def test_rare_callable_name_still_grants_structural_authority(tmp_path):
    _generic_repo(tmp_path)

    ranked = rank_files(
        tmp_path, "where does it resolve redirects for a response", changed_boost=False,
    )

    assert _authority(_reasons(ranked, "redirects.py")) > 0.0


def test_explicit_container_member_pair_stays_authoritative_for_generic_name(tmp_path):
    _generic_repo(tmp_path)
    (tmp_path / "sess.py").write_text(
        "class Session:\n    def get(self, key):\n        return key\n"
    )

    ranked = rank_files(tmp_path, "Session Get", changed_boost=False)

    assert _authority(_reasons(ranked, "sess.py")) >= 200.0
    assert _authority(_reasons(ranked, "mod0.py")) == 0.0


def test_structural_authority_is_dampened_in_low_value_directories(tmp_path, monkeypatch):
    # Regression: authority was added *after* the 0.35x low-value-directory
    # dampening, so a test/example file defining a matching callable kept the
    # whole boost while an ordinary source file was (correctly) not exempt.
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    body = "def resolve_redirects(response):\n    return response\n"
    (tmp_path / "src" / "redirects.py").write_text(body)
    (tmp_path / "tests" / "test_redirects.py").write_text(body)
    query = "where does it resolve redirects for a response"

    with_authority = {r.rel: r for r in rank_files(tmp_path, query, changed_boost=False)}
    monkeypatch.setattr(pack_module, "_structural_file_authority", lambda *a, **k: 0.0)
    without = {r.rel: r for r in rank_files(tmp_path, query, changed_boost=False)}

    src_gain = with_authority["src/redirects.py"].score - without["src/redirects.py"].score
    test_gain = (
        with_authority["tests/test_redirects.py"].score
        - without["tests/test_redirects.py"].score
    )
    assert src_gain > 30.0
    assert abs(test_gain - 0.35 * src_gain) < 1.0


def test_query_is_not_retokenized_once_per_file(tmp_path, monkeypatch):
    # Regression: symbol_terms(query) and the member-hint regex ran inside the
    # per-file authority call, so cost grew with file count on every query.
    for n in range(40):
        (tmp_path / f"f{n}.py").write_text(f"def helper_{n}(x):\n    return x\n")
    calls = []
    real = pack_module.symbol_terms
    monkeypatch.setattr(
        pack_module, "symbol_terms", lambda text: calls.append(text) or real(text)
    )

    rank_files(tmp_path, "resolve the helper for this request", changed_boost=False)

    assert len(calls) <= 2
