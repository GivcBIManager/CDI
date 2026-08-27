"""Layer 2: lexical retrieval over the clause store (SQLite FTS5, BM25).

Title matches are weighted 5x body matches. Queries are sanitized to bare
terms (FTS5 syntax stripped) and OR-joined; expansions (synonyms from the
requirement model) are OR-appended.
"""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cdi_kb.clauses import Clause

_TERM = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class SearchHit:
    clause_id: str
    section_title: str
    score: float


def _fts_query(query: str, expansions: list[str] | None) -> str:
    phrases = [query] + list(expansions or [])
    parts: list[str] = []
    for phrase in phrases:
        terms = _TERM.findall(phrase)
        if terms:
            parts.append('"' + " ".join(terms) + '"')      # exact phrase
            parts.extend(f'"{t}"' for t in terms if len(t) > 2)  # individual terms
    return " OR ".join(parts)


class SearchIndex:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS clause_fts USING fts5("
            "clause_id UNINDEXED, section_title, body)"
        )

    def rebuild(self, clauses: list[Clause]) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM clause_fts")
            self._conn.executemany(
                "INSERT INTO clause_fts VALUES (?, ?, ?)",
                [(c.clause_id, c.section_title, c.text) for c in clauses],
            )

    def search(self, query: str, expansions: list[str] | None = None, limit: int = 10) -> list[SearchHit]:
        fts = _fts_query(query, expansions)
        if not fts:
            return []
        rows = self._conn.execute(
            "SELECT clause_id, section_title, bm25(clause_fts, 0.0, 5.0, 1.0) AS rank "
            "FROM clause_fts WHERE clause_fts MATCH ? ORDER BY rank LIMIT ?",
            (fts, limit),
        ).fetchall()
        # bm25() returns lower-is-better; expose higher-is-better scores
        return [SearchHit(clause_id=r[0], section_title=r[1], score=round(-r[2], 4)) for r in rows]

    def close(self) -> None:
        self._conn.close()
