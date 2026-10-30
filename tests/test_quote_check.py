from backend.pull import verify_quote

DOC = {
    "pages": [
        "Opening remarks. Revenue grew in all markets.",
        "Overall, our eƯorts continue towards the 26% to 28% band, and we expect\n",
        "the data centre to start generating revenue in about 18 to 24 months.",
    ]
}


def test_exact_quote_with_ligature_glyph():
    assert verify_quote("Overall, our efforts continue towards the 26% to 28% band", DOC, 2) == 2


def test_quote_across_page_break():
    assert verify_quote("we expect the data centre to start generating revenue", DOC, 2) == 2


def test_wrong_page_is_corrected():
    assert verify_quote("start generating revenue in about 18 to 24 months", DOC, 1) == 3


def test_invented_quote_fails():
    assert verify_quote("we expect margins to expand to 30% by the end of next year", DOC, 2) is None


def test_changed_number_fails():
    assert verify_quote("Overall, our efforts continue towards the 27% to 29% band", DOC, 2) is None
