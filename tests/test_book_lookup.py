from app.book_lookup import parse_openlibrary_docs


def test_book_lookup_parser() -> None:
    payload = {
        "docs": [
            {
                "title": "Example Book",
                "author_name": ["Ada Lovelace"],
                "publisher": ["Example Press"],
                "first_sentence": ["A precise description."],
            }
        ]
    }
    results = parse_openlibrary_docs(payload)
    assert results == [
        {
            "title": "Example Book",
            "author": "Ada Lovelace",
            "publisher": "Example Press",
            "description": "A precise description.",
            "source": "OpenLibrary",
        }
    ]

