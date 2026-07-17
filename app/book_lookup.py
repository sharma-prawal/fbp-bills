from __future__ import annotations

import random

import httpx


def parse_openlibrary_docs(payload: dict) -> list[dict]:
    results: list[dict] = []
    for item in payload.get("docs", [])[:10]:
        title = item.get("title")
        if not title:
            continue
        authors = item.get("author_name") or []
        publishers = item.get("publisher") or []
        results.append(
            {
                "title": title,
                "author": ", ".join(authors[:2]),
                "publisher": publishers[0] if publishers else "",
                "description": item.get("first_sentence", [""])[0] if isinstance(item.get("first_sentence"), list) else "",
                "source": "OpenLibrary",
            }
        )
    return results


async def search_openlibrary(keyword: str) -> list[dict]:
    if not keyword.strip():
        return []
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get("https://openlibrary.org/search.json", params={"q": keyword, "limit": 10})
        response.raise_for_status()
    return parse_openlibrary_docs(response.json())


def search_openlibrary_sync(keyword: str) -> list[dict]:
    if not keyword.strip():
        return []
    with httpx.Client(timeout=10, follow_redirects=True) as client:
        response = client.get("https://openlibrary.org/search.json", params={"q": keyword, "limit": 10})
        response.raise_for_status()
    return parse_openlibrary_docs(response.json())


FALLBACK_DYNAMIC_BOOKS = [
    {
        "title": "The Pragmatic Programmer",
        "author": "Andrew Hunt, David Thomas",
        "publisher": "Addison-Wesley",
        "description": "Software engineering practices and professional development guidance.",
        "source": "Fallback catalog",
    },
    {
        "title": "Clean Architecture",
        "author": "Robert C. Martin",
        "publisher": "Pearson",
        "description": "Design principles for maintainable software systems.",
        "source": "Fallback catalog",
    },
    {
        "title": "Designing Data-Intensive Applications",
        "author": "Martin Kleppmann",
        "publisher": "O'Reilly Media",
        "description": "Distributed data systems, storage, and processing concepts.",
        "source": "Fallback catalog",
    },
    {
        "title": "Accelerate",
        "author": "Nicole Forsgren, Jez Humble",
        "publisher": "IT Revolution Press",
        "description": "Research-backed software delivery and organizational performance practices.",
        "source": "Fallback catalog",
    },
]


def dynamic_book(keyword: str = "software engineering business") -> dict:
    books = []
    try:
        books = search_openlibrary_sync(keyword)
    except Exception:
        books = []
    if not books:
        books = FALLBACK_DYNAMIC_BOOKS
    return random.choice(books)
