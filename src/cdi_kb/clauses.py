"""Layer 1: verbatim clause store with stable citation anchors.

The booklet has a clean dot-leader TOC (pages ~2-8). Chunking strategy:
1. Parse TOC entries `Title ..... page`.
2. Locate each title as a standalone line in the body (searching from after the
   TOC), assign section spans from one title line to the next.
3. Split each section into paragraph clauses; clause_id anchors to the section
   slug + paragraph ordinal so re-chunking never breaks citations
   (proposal section 2.3).
"""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cdi_kb.config import SOURCE_ID
from cdi_kb.extract import PageText
from cdi_kb.normalize import normalize

_TOC_LINE = re.compile(r"^(?P<title>.{3,120}?)\s*\.{4,}\s*(?P<page>\d{1,3})\s*$")
_NON_SLUG = re.compile(r"[^a-z0-9]+")
MIN_CLAUSE_CHARS = 120  # skip caption fragments and stray lines


@dataclass(frozen=True)
class TocEntry:
    title: str
    page: int


@dataclass(frozen=True)
class Clause:
    clause_id: str
    section_title: str
    page: int
    text: str


def slugify(title: str) -> str:
    return _NON_SLUG.sub("-", title.lower()).strip("-")


def parse_toc(pages: list[PageText]) -> list[TocEntry]:
    entries: list[TocEntry] = []
    for page in pages[:10]:  # TOC lives in the front matter
        for line in page.text.splitlines():
            match = _TOC_LINE.match(line.strip())
            if match:
                entries.append(TocEntry(title=match.group("title").strip(), page=int(match.group("page"))))
    return entries


def _split_paragraphs(text: str) -> list[str]:
    """Split section text into paragraph-sized chunks.

    pdfplumber's extract_text() does not preserve blank lines between
    paragraphs (confirmed by inspection: every section's blank-line split
    collapsed to a single chunk), so the primary split is a sentence-boundary
    heuristic: a paragraph ends at a line ending in "." when the following
    line starts with a capital letter. Blank-line splitting is tried first in
    case some sections do carry blank lines.
    """
    blank_split = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(blank_split) > 1:
        return [p for p in blank_split if len(p) >= MIN_CLAUSE_CHARS]
    lines = text.split("\n")
    paragraphs: list[str] = []
    current: list[str] = []
    for index, line in enumerate(lines):
        current.append(line)
        ends_sentence = line.rstrip().endswith(".")
        next_starts_capital = index + 1 < len(lines) and lines[index + 1][:1].isupper()
        if ends_sentence and next_starts_capital:
            paragraphs.append("\n".join(current))
            current = []
    if current:
        paragraphs.append("\n".join(current))
    return [p.strip() for p in paragraphs if len(p.strip()) >= MIN_CLAUSE_CHARS]


def _locate_sections(pages: list[PageText], toc: list[TocEntry]) -> list[tuple[TocEntry, int]]:
    """Return (entry, global_line_index) for each TOC title found as a body line."""
    lines: list[tuple[int, str]] = []  # (page_number, line)
    for page in pages:
        if page.page_number <= 8:  # skip cover + TOC itself
            continue
        for line in page.text.splitlines():
            lines.append((page.page_number, line.strip()))
    located: list[tuple[TocEntry, int]] = []
    cursor = 0  # titles appear in TOC order; search forward only
    for entry in toc:
        target = normalize(entry.title)
        for index in range(cursor, len(lines)):
            if normalize(lines[index][1]) == target:
                located.append((entry, index))
                cursor = index + 1
                break
    return located


def chunk_booklet(pages: list[PageText]) -> list[Clause]:
    toc = parse_toc(pages)
    body_lines: list[tuple[int, str]] = []
    for page in pages:
        if page.page_number <= 8:
            continue
        for line in page.text.splitlines():
            body_lines.append((page.page_number, line.strip()))
    located = _locate_sections(pages, toc)
    clauses: list[Clause] = []
    seen_slugs: dict[str, int] = {}
    for position, (entry, start) in enumerate(located):
        end = located[position + 1][1] if position + 1 < len(located) else len(body_lines)
        slug = slugify(entry.title)
        seen_slugs[slug] = seen_slugs.get(slug, 0) + 1
        if seen_slugs[slug] > 1:  # duplicate headings (e.g. same condition in two chapters)
            slug = f"{slug}-{seen_slugs[slug]}"
        section_page = body_lines[start][0]
        section_text = "\n".join(line for _, line in body_lines[start + 1 : end])
        paragraphs = _split_paragraphs(section_text)
        for ordinal, paragraph in enumerate(paragraphs, start=1):
            clauses.append(Clause(
                clause_id=f"{SOURCE_ID}/{slug}/p{ordinal}",
                section_title=entry.title,
                page=section_page,
                text=paragraph,
            ))
    return clauses


class ClauseStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS clauses ("
            " clause_id TEXT PRIMARY KEY, section_title TEXT NOT NULL,"
            " page INTEGER NOT NULL, text TEXT NOT NULL)"
        )

    def rebuild(self, clauses: list[Clause]) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM clauses")
            self._conn.executemany(
                "INSERT INTO clauses VALUES (?, ?, ?, ?)",
                [(c.clause_id, c.section_title, c.page, c.text) for c in clauses],
            )

    def get(self, clause_id: str) -> Clause | None:
        row = self._conn.execute(
            "SELECT clause_id, section_title, page, text FROM clauses WHERE clause_id = ?", (clause_id,)
        ).fetchone()
        return Clause(*row) if row else None

    def all(self) -> list[Clause]:
        rows = self._conn.execute("SELECT clause_id, section_title, page, text FROM clauses ORDER BY clause_id")
        return [Clause(*row) for row in rows]

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM clauses").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
