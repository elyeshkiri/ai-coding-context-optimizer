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
