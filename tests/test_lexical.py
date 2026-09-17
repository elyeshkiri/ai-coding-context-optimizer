from token_saver.lexical import terms


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
