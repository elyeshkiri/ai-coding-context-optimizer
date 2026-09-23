from acco.lexical import fuzzy_symbol_terms, symbol_terms, terms


def test_acronym_prefixed_identifiers_split_at_every_word_boundary():
    # Found via the second frozen external holdout (psf/requests):
    # HTTPBasicAuth previously tokenized as ['httpbasic', 'auth'] because the
    # camelCase splitter only recognized a lower/digit-to-upper transition,
    # not an upper-run-to-title-case one -- so a query for "HTTP basic
    # authentication" never matched HTTPBasicAuth's own name at all, and a
    # loosely-related helper function won the symbol-window competition
    # instead.
    assert terms("HTTPBasicAuth") == ["http", "basic", "auth"]
    assert terms("HTTPDigestAuth") == ["http", "digest", "auth"]
    assert terms("URLPattern") == ["url", "pattern"]
    assert terms("XMLHttpRequest") == ["xml", "http", "request"]


def test_plain_acronym_and_ordinary_camel_case_still_tokenize_correctly():
    assert terms("ID") == ["id"]
    assert terms("fetchUserId") == ["fetch", "user", "id"]
    assert terms("DigestAuth") == ["digest", "auth"]


def test_single_leading_capital_is_not_treated_as_a_one_letter_acronym():
    # Found via the second frozen external holdout (expressjs/express): a
    # naive "two consecutive uppercase letters" rule would have split
    # "ETag" into "E" + "Tag", never matching the plain "etag" property
    # name used elsewhere in the same codebase for the same concept.
    # Requiring *two* preceding uppercase letters (not one) keeps a single
    # leading capital -- almost always an ordinary capitalized word, not an
    # acronym -- as one token.
    assert terms("ETag") == ["etag"]
    assert terms("etag") == ["etag"]
    assert terms("IPage") == ["ipage"]


def test_symbol_terms_add_conservative_inflection_equivalents():
    assert "connect" in symbol_terms("connection timeout")
    assert "equal" in symbol_terms("deep equality")
    assert "complete" in symbol_terms("shell completion")
    assert "validate" in symbol_terms("schema validation")
    assert "persist" in symbol_terms("cookie persistence")


def test_symbol_terms_add_small_code_oriented_synonym_set_only():
    assert "start" in symbol_terms("first day of week")
    # Repository-wide terms remain unchanged; the richer equivalence is
    # deliberately confined to within-file symbol ranking.
    assert "start" not in terms("first day of week")



def test_fuzzy_symbol_terms_recovers_high_confidence_identifier_typos():
    matches = fuzzy_symbol_terms(
        {"conection", "rendr"},
        {"connection", "render", "redirect"},
    )
    assert matches["conection"][0] == "connection"
    assert matches["rendr"][0] == "render"


def test_fuzzy_symbol_terms_rejects_ambiguous_near_ties():
    matches = fuzzy_symbol_terms(
        {"rende"},
        {"render", "rendez"},
        min_ratio=0.80,
        min_margin=0.08,
    )
    assert "rende" not in matches
