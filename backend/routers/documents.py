"""The policy wording and the claims manual, by section."""

from typing import Any

from fastapi import APIRouter, HTTPException

from backend.db import DB

EXCERPT = 200

router = APIRouter(prefix="/api/documents")


@router.get("/search", operation_id="search_documents")
def search_documents(query: str, conn: DB) -> list[dict[str, str]]:
    """Find the sections of the wording and the manual holding every query word."""
    words = query.lower().split()
    rows = conn.execute(
        "SELECT document, section, title, text FROM sections "
        "ORDER BY document DESC, position"
    )
    found = []
    for row in rows:
        text = row["text"].lower()
        if words and all(w in text or w in row["title"].lower() for w in words):
            start = max(text.find(words[0]) - EXCERPT // 2, 0)
            found.append(
                {
                    "document": row["document"],
                    "section": row["section"],
                    "title": row["title"],
                    "excerpt": row["text"][start : start + EXCERPT],
                }
            )
    return found


@router.get("/{document}", operation_id="get_contents")
def get_contents(document: str, conn: DB) -> dict[str, Any]:
    """Get a document's title, introduction and list of sections."""
    row = conn.execute(
        "SELECT title, intro FROM documents WHERE document = ?", (document,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"No document {document}")
    sections = conn.execute(
        "SELECT section, title FROM sections WHERE document = ? ORDER BY position",
        (document,),
    )
    return {**dict(row), "sections": [dict(s) for s in sections]}


@router.get("/{document}/sections/{section}", operation_id="get_section")
def get_section(document: str, section: str, conn: DB) -> dict[str, str]:
    """Get one section of a document."""
    row = conn.execute(
        "SELECT document, section, title, text FROM sections "
        "WHERE document = ? AND section = ?",
        (document, section),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"No section {section} in {document}")
    return dict(row)
