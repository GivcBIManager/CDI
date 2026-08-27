# CDI Audit KB Demo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A runnable, tested demo that audits a pasted clinical note against 20 diagnoses' documentation requirements, every finding carrying a citation string-verified against the actual source PDFs in `d:\CDI`.

**Architecture:** Three KB layers per the approved proposal (`docs/CDI-Audit-Assistant-MVP-Proposal.md` §2): Layer 1 clause store (SQLite, verbatim booklet text with stable clause IDs), Layer 2 retrieval (SQLite FTS5 BM25 with title boost + synonym expansion), Layer 3 requirement model (20 YAML entries: condition → required specificity axes → citation). The audit loop is **deterministic and offline-testable** (synonym/negation condition detection + axis vocabulary scan + template findings); an optional LLM stage (Anthropic `messages.parse`) adds treated-but-not-named condition inference and is `live`-marked in tests. A verification suite (V1–V5) enforces the "complete match against source documents" requirement. FastAPI paste-a-note UI + CLI.

**Tech Stack:** Python 3.13 (`/c/python/python`, verified), stdlib `sqlite3` + FTS5 (verified available), `pdfplumber`, `pydantic` v2, `pyyaml`, `anthropic` (model `claude-opus-5`), FastAPI + uvicorn, pytest 9.

## Global Constraints

- Python `>= 3.13`; modern type syntax (`list[str]`, `X | None`); dataclasses/pydantic, no untyped dicts across module boundaries.
- `pathlib.Path` everywhere; every `read_text`/`write_text` passes `encoding="utf-8"`.
- Absolute imports only; empty `__init__.py`; LBYL over exception control flow.
- Anthropic model ID is exactly `claude-opus-5`, only in `config.py`.
- **A finding without a citation that string-matches Layer 1 at ≥ 0.95 normalized similarity must never be returned** — enforced in `findings.py`, tested in Task 9.
- PDFs and build artifacts are never committed: `.gitignore` covers `CHI_Guidelines/`, `*.pdf`, `var/`, `kb_raw/`.
- `pytest` with no flags must pass **offline** (no network, no API key): all LLM tests carry `@pytest.mark.live` and are deselected by default via `addopts = "-m 'not live'"`.
- Run commands from repo root `d:\CDI` as `/c/python/python -m ...` (plain `python` may resolve to the WindowsApps shim).
- Source PDFs: `CDI Course Booklet - Clinicians.pdf` (primary citation source) at repo root. CHI PDFs are out of scope for the demo KB build (flowchart genre needs VLM linearization — post-demo; see proposal §3.2).

---

### Task 0: Project scaffold

**Files:**
- Create: `.gitignore`, `pyproject.toml`, `src/cdi_kb/__init__.py`, `src/cdi_kb/config.py`, `tests/__init__.py`, `tests/test_config.py`

**Interfaces:**
- Produces: package `cdi_kb` importable; `cdi_kb.config` constants: `REPO_ROOT: Path`, `BOOKLET_PDF: Path`, `VAR_DIR: Path`, `RAW_TEXT_DIR: Path`, `KB_DB: Path`, `REQUIREMENTS_DIR: Path`, `EVAL_DIR: Path`, `ANTHROPIC_MODEL: str`, `QUOTE_MATCH_THRESHOLD: float`, `SOURCE_ID: str`

- [ ] **Step 1: Initialize git and .gitignore**

```bash
cd /d/CDI && git init -b main
```

Write `.gitignore`:

```gitignore
__pycache__/
*.egg-info/
.pytest_cache/
var/
kb_raw/
CHI_Guidelines/
*.pdf
.env
```

- [ ] **Step 2: Write pyproject.toml**

```toml
[project]
name = "cdi_kb"
version = "0.1.0"
description = "CDI audit knowledge-base demo: clause store, retrieval, requirement model, audit loop"
requires-python = ">=3.13"
dependencies = [
    "pdfplumber>=0.11",
    "pydantic>=2.7",
    "pyyaml>=6.0",
    "anthropic>=1.0",
    "fastapi>=0.115",
    "uvicorn>=0.30",
]

[project.optional-dependencies]
dev = ["pytest>=8", "httpx>=0.27"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
addopts = "-m 'not live'"
markers = ["live: requires ANTHROPIC credentials and network"]
testpaths = ["tests"]
```

- [ ] **Step 3: Write src/cdi_kb/config.py** (and empty `src/cdi_kb/__init__.py`, `tests/__init__.py`)

```python
"""Central paths and constants for the CDI KB demo."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOKLET_PDF = REPO_ROOT / "CDI Course Booklet - Clinicians.pdf"

VAR_DIR = REPO_ROOT / "var"
RAW_TEXT_DIR = VAR_DIR / "raw_text"
KB_DB = VAR_DIR / "kb.sqlite"

REQUIREMENTS_DIR = REPO_ROOT / "data" / "requirements"
EVAL_DIR = REPO_ROOT / "data" / "eval"

ANTHROPIC_MODEL = "claude-opus-5"
QUOTE_MATCH_THRESHOLD = 0.95
SOURCE_ID = "CDI-2021"  # citation prefix for the booklet
```

- [ ] **Step 4: Write the failing smoke test** in `tests/test_config.py`

```python
from cdi_kb import config


def test_booklet_pdf_exists() -> None:
    assert config.BOOKLET_PDF.exists(), f"missing source PDF: {config.BOOKLET_PDF}"


def test_source_id_prefix() -> None:
    assert config.SOURCE_ID == "CDI-2021"
```

- [ ] **Step 5: Install and run**

```bash
cd /d/CDI && /c/python/python -m pip install -e ".[dev]" && /c/python/python -m pytest tests/test_config.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add .gitignore pyproject.toml src tests && git commit -m "chore: scaffold cdi_kb package"
```

---

### Task 1: Text normalization and quote matching (the citation firewall primitive)

**Files:**
- Create: `src/cdi_kb/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produces: `normalize(text: str) -> str`; `find_quote(quote: str, source: str, threshold: float = 0.95) -> QuoteMatch` where `QuoteMatch` is a frozen dataclass with `found: bool`, `score: float`. Every later layer (verification suite, findings composer) calls `find_quote`.

- [ ] **Step 1: Write the failing tests** in `tests/test_normalize.py`

```python
from cdi_kb.normalize import QuoteMatch, find_quote, normalize


def test_normalize_collapses_whitespace_and_case() -> None:
    assert normalize("Chronic  Kidney\n Disease") == "chronic kidney disease"


def test_normalize_unifies_typographic_quotes_and_dashes() -> None:
    assert normalize("\u201cstage\u201d \u2013 4") == '"stage" - 4'


def test_find_quote_exact_substring() -> None:
    match = find_quote("Stage 1 through to 5", "A disease may be described as Stage 1 through to 5.")
    assert match == QuoteMatch(found=True, score=1.0)


def test_find_quote_tolerates_small_ocr_noise() -> None:
    source = "results should be confirmed by repeat testing in the patient record"
    quote = "results should be confirmed by repeat testing in the patient records"
    match = find_quote(quote, source)
    assert match.found and match.score >= 0.95


def test_find_quote_rejects_fabrication() -> None:
    match = find_quote("document the CKD stage using eGFR", "the quick brown fox jumps over the lazy dog")
    assert not match.found


def test_find_quote_empty_quote_is_not_found() -> None:
    assert not find_quote("", "anything").found
```

- [ ] **Step 2: Run to verify failure**

Run: `/c/python/python -m pytest tests/test_normalize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cdi_kb.normalize'`

- [ ] **Step 3: Implement** `src/cdi_kb/normalize.py`

```python
"""Text normalization and fuzzy quote matching.

find_quote is the citation firewall primitive (proposal section 2.2): a quote
"matches" a source only if it appears verbatim after normalization, or at
>= threshold similarity in a sliding window. Callers must drop any citation
whose quote does not match.
"""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

_WHITESPACE = re.compile(r"\s+")
_CHAR_MAP = str.maketrans({
    "\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'",
    "\u2013": "-", "\u2014": "-", "\u00a0": " ", "\ufb01": "fi", "\ufb02": "fl",
})


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_CHAR_MAP)
    return _WHITESPACE.sub(" ", text).strip().lower()


@dataclass(frozen=True)
class QuoteMatch:
    found: bool
    score: float


def find_quote(quote: str, source: str, threshold: float = 0.95) -> QuoteMatch:
    norm_quote, norm_source = normalize(quote), normalize(source)
    if not norm_quote:
        return QuoteMatch(found=False, score=0.0)
    if norm_quote in norm_source:
        return QuoteMatch(found=True, score=1.0)
    window = len(norm_quote) + len(norm_quote) // 10
    step = max(1, len(norm_quote) // 4)
    best = 0.0
    for start in range(0, max(1, len(norm_source) - len(norm_quote) + 1), step):
        ratio = SequenceMatcher(None, norm_quote, norm_source[start : start + window]).ratio()
        best = max(best, ratio)
        if best >= 0.999:
            break
    return QuoteMatch(found=best >= threshold, score=round(best, 4))
```

- [ ] **Step 4: Run to verify pass**

Run: `/c/python/python -m pytest tests/test_normalize.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cdi_kb/normalize.py tests/test_normalize.py && git commit -m "feat: normalization and fuzzy quote matching"
```

---

### Task 2: PDF extraction with page-level cache

**Files:**
- Create: `src/cdi_kb/extract.py`
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes: `config.BOOKLET_PDF`, `config.RAW_TEXT_DIR`
- Produces: `PageText` (frozen dataclass: `page_number: int` 1-based physical page, `text: str`) and `extract_pages(pdf_path: Path, cache_dir: Path) -> list[PageText]`. Task 3 consumes this to chunk; verification V1 consumes it as ground truth.

- [ ] **Step 1: Write the failing tests** in `tests/test_extract.py`

```python
from cdi_kb import config
from cdi_kb.extract import extract_pages
from cdi_kb.normalize import normalize


def test_booklet_extracts_substantial_text() -> None:
    pages = extract_pages(config.BOOKLET_PDF, config.RAW_TEXT_DIR)
    assert len(pages) > 100
    total = sum(len(p.text) for p in pages)
    assert total > 300_000, f"expected >300K chars (corpus analysis measured ~368K), got {total}"


def test_known_sentence_present() -> None:
    # Verbatim from the Documenting for Specificity chapter (verified during corpus analysis).
    pages = extract_pages(config.BOOKLET_PDF, config.RAW_TEXT_DIR)
    full = normalize(" ".join(p.text for p in pages))
    assert "type, stage, agent, onset or causative factors and site" in full


def test_cache_is_used_on_second_call(tmp_path) -> None:
    first = extract_pages(config.BOOKLET_PDF, tmp_path)
    cache_files = list(tmp_path.glob("*.json"))
    assert len(cache_files) == 1
    second = extract_pages(config.BOOKLET_PDF, tmp_path)
    assert first == second
```

- [ ] **Step 2: Run to verify failure**

Run: `/c/python/python -m pytest tests/test_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cdi_kb.extract'`

- [ ] **Step 3: Implement** `src/cdi_kb/extract.py`

```python
"""PDF text extraction with a JSON page cache under var/raw_text/."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber


@dataclass(frozen=True)
class PageText:
    page_number: int  # 1-based physical page index
    text: str


def extract_pages(pdf_path: Path, cache_dir: Path) -> list[PageText]:
    cache_file = cache_dir / f"{pdf_path.stem}.json"
    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        return [PageText(**page) for page in cached]
    pages: list[PageText] = []
    with pdfplumber.open(pdf_path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            pages.append(PageText(page_number=number, text=page.extract_text() or ""))
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps([asdict(p) for p in pages]), encoding="utf-8")
    return pages
```

- [ ] **Step 4: Run to verify pass** (first run extracts ~150 pages; allow ~2–4 min)

Run: `/c/python/python -m pytest tests/test_extract.py -v`
Expected: 3 passed. If `test_known_sentence_present` fails, print the extracted text around "causative factors" and adjust `_CHAR_MAP` in `normalize.py` (pdfplumber may render ligatures differently than pdftotext did) — do not weaken the assertion to a shorter phrase without checking the actual text first.

- [ ] **Step 5: Commit**

```bash
git add src/cdi_kb/extract.py tests/test_extract.py && git commit -m "feat: cached PDF page extraction"
```

---

### Task 3: Layer 1 — clause store (TOC-driven booklet chunking + SQLite)

**Files:**
- Create: `src/cdi_kb/clauses.py`
- Test: `tests/test_clauses.py`

**Interfaces:**
- Consumes: `extract_pages`, `normalize`, `config.SOURCE_ID`
- Produces:
  - `Clause` (frozen dataclass): `clause_id: str`, `section_title: str`, `page: int`, `text: str`
  - `parse_toc(pages: list[PageText]) -> list[TocEntry]` — `TocEntry` frozen dataclass: `title: str`, `page: int`
  - `chunk_booklet(pages: list[PageText]) -> list[Clause]`
  - `ClauseStore` class: `ClauseStore(db_path: Path)`, `.rebuild(clauses: list[Clause]) -> None`, `.get(clause_id: str) -> Clause | None`, `.all() -> list[Clause]`, `.count() -> int`, `.close() -> None`
  - clause_id format: `CDI-2021/<section-slug>/p<n>` (e.g., `CDI-2021/documenting-for-specificity/p3`)

- [ ] **Step 1: Write the failing tests** in `tests/test_clauses.py`

```python
from cdi_kb import config
from cdi_kb.clauses import ClauseStore, chunk_booklet, parse_toc, slugify
from cdi_kb.extract import extract_pages
from cdi_kb.normalize import normalize


def _pages():
    return extract_pages(config.BOOKLET_PDF, config.RAW_TEXT_DIR)


def test_slugify() -> None:
    assert slugify("Chronic Kidney Disease (CKD)") == "chronic-kidney-disease-ckd"


def test_toc_finds_known_sections() -> None:
    titles = [entry.title for entry in parse_toc(_pages())]
    assert any("Documenting for Specificity" in t for t in titles)
    assert any("Chronic Kidney Disease" in t for t in titles)
    assert any("Sepsis" in t for t in titles)
    assert len(titles) > 100


def test_chunks_have_ids_and_specificity_text() -> None:
    clauses = chunk_booklet(_pages())
    assert len(clauses) > 200
    spec = [c for c in clauses if c.clause_id.startswith("CDI-2021/documenting-for-specificity/")]
    assert spec, "Documenting for Specificity section produced no clauses"
    joined = normalize(" ".join(c.text for c in spec))
    assert "type, stage, agent, onset" in joined


def test_store_roundtrip(tmp_path) -> None:
    clauses = chunk_booklet(_pages())
    store = ClauseStore(tmp_path / "kb.sqlite")
    store.rebuild(clauses)
    assert store.count() == len(clauses)
    first = clauses[0]
    fetched = store.get(first.clause_id)
    assert fetched is not None and fetched.text == first.text
    assert store.get("CDI-2021/no-such-section/p1") is None
    store.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `/c/python/python -m pytest tests/test_clauses.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cdi_kb.clauses'`

- [ ] **Step 3: Implement** `src/cdi_kb/clauses.py`

```python
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
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section_text) if len(p.strip()) >= MIN_CLAUSE_CHARS]
        if not paragraphs and len(section_text.strip()) >= MIN_CLAUSE_CHARS:
            paragraphs = [section_text.strip()]
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
```

- [ ] **Step 4: Run to verify pass**

Run: `/c/python/python -m pytest tests/test_clauses.py -v`
Expected: 4 passed. Likely failure modes and fixes (diagnose, don't loosen tests): (a) TOC page range wrong → widen `pages[:10]`; (b) body line match misses because pdfplumber merges heading with following text → relax `_locate_sections` equality to `startswith` on the normalized title **only if** exact match found fewer than 80% of TOC entries; (c) paragraphs not blank-line separated in extraction → split on lines ending with `.` followed by a line starting with a capital, as fallback.

- [ ] **Step 5: Commit**

```bash
git add src/cdi_kb/clauses.py tests/test_clauses.py && git commit -m "feat: layer 1 clause store with TOC-driven chunking"
```

---

### Task 4: Layer 2 — FTS5 retrieval with title boost and synonym expansion

**Files:**
- Create: `src/cdi_kb/index.py`
- Test: `tests/test_index.py`

**Interfaces:**
- Consumes: `Clause`, `ClauseStore`
- Produces: `SearchHit` (frozen dataclass: `clause_id: str`, `section_title: str`, `score: float`) and `SearchIndex` class: `SearchIndex(db_path: Path)` (same SQLite file as ClauseStore), `.rebuild(clauses: list[Clause]) -> None`, `.search(query: str, expansions: list[str] | None = None, limit: int = 10) -> list[SearchHit]`, `.close() -> None`. Production upgrade path (hybrid BGE-M3 dense + rerank, proposal §3.3) plugs in behind this same search signature — out of demo scope.

- [ ] **Step 1: Write the failing tests** in `tests/test_index.py`

```python
from cdi_kb.clauses import Clause
from cdi_kb.index import SearchIndex

CLAUSES = [
    Clause("CDI-2021/chronic-kidney-disease-ckd/p1", "Chronic Kidney Disease (CKD)", 119,
           "Chronic kidney disease must be documented with its stage, based on eGFR."),
    Clause("CDI-2021/sepsis/p1", "Sepsis", 118,
           "Sepsis documentation requires the causative organism and any organ dysfunction."),
    Clause("CDI-2021/fractures/p1", "Fractures", 120,
           "Fracture documentation requires site, open or closed type, and mechanism."),
]


def _index(tmp_path) -> SearchIndex:
    index = SearchIndex(tmp_path / "kb.sqlite")
    index.rebuild(CLAUSES)
    return index


def test_search_ranks_matching_section_first(tmp_path) -> None:
    hits = _index(tmp_path).search("chronic kidney disease stage")
    assert hits and hits[0].clause_id == "CDI-2021/chronic-kidney-disease-ckd/p1"


def test_synonym_expansion_finds_full_name(tmp_path) -> None:
    hits = _index(tmp_path).search("CKD", expansions=["chronic kidney disease"])
    assert any(h.clause_id.startswith("CDI-2021/chronic-kidney-disease") for h in hits)


def test_query_with_fts_special_chars_does_not_raise(tmp_path) -> None:
    hits = _index(tmp_path).search('sepsis "organism" (severe) - shock?')
    assert isinstance(hits, list)


def test_limit_respected(tmp_path) -> None:
    assert len(_index(tmp_path).search("documentation", limit=2)) <= 2
```

- [ ] **Step 2: Run to verify failure**

Run: `/c/python/python -m pytest tests/test_index.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cdi_kb.index'`

- [ ] **Step 3: Implement** `src/cdi_kb/index.py`

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `/c/python/python -m pytest tests/test_index.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cdi_kb/index.py tests/test_index.py && git commit -m "feat: layer 2 FTS5 retrieval with title boost"
```

---

### Task 5: Layer 3 — requirement model schema, loader, and the CKD worked entry

**Files:**
- Create: `src/cdi_kb/requirements_model.py`, `data/requirements/chronic-kidney-disease.yaml`
- Test: `tests/test_requirements_model.py`

**Interfaces:**
- Consumes: `config.REQUIREMENTS_DIR`
- Produces (pydantic models — later tasks import these names exactly):
  - `Citation`: `clause_id: str`, `quote: str`
  - `AxisRule`: `axis: Literal["type","stage","agent","onset","site"]`, `level: Literal["required","recommended"]`, `evidence_terms: list[str]` (min 1)
  - `DiagnosisRequirement`: `condition: str`, `synonyms: list[str]` (min 1), `axes: list[AxisRule]` (min 1), `recommendation: str`, `citations: list[Citation]` (min 1)
  - `load_requirements(directory: Path) -> list[DiagnosisRequirement]` — loads every `*.yaml`, raises `ValueError` naming the file on any schema violation

- [ ] **Step 1: Write the failing tests** in `tests/test_requirements_model.py`

```python
import pytest

from cdi_kb import config
from cdi_kb.requirements_model import DiagnosisRequirement, load_requirements


def test_ckd_entry_loads() -> None:
    entries = load_requirements(config.REQUIREMENTS_DIR)
    by_condition = {e.condition: e for e in entries}
    assert "chronic kidney disease" in by_condition
    ckd = by_condition["chronic kidney disease"]
    assert "ckd" in [s.lower() for s in ckd.synonyms]
    assert any(a.axis == "stage" and a.level == "required" for a in ckd.axes)
    assert ckd.citations and ckd.citations[0].clause_id.startswith("CDI-2021/")


def test_invalid_axis_rejected(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "condition: x\nsynonyms: [x]\n"
        "axes: [{axis: colour, level: required, evidence_terms: [y]}]\n"
        "recommendation: r\ncitations: [{clause_id: 'CDI-2021/a/p1', quote: q}]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="bad.yaml"):
        load_requirements(tmp_path)
```

- [ ] **Step 2: Run to verify failure**

Run: `/c/python/python -m pytest tests/test_requirements_model.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cdi_kb.requirements_model'`

- [ ] **Step 3: Implement** `src/cdi_kb/requirements_model.py`

```python
"""Layer 3: the requirement model — what must be documented per diagnosis.

Entries are YAML files under data/requirements/, human-reviewable, each
carrying at least one citation whose quote the verification suite
string-matches against Layer 1 (V2). Never hand-edit a quote: copy it from
`cli.py quote` output so it is verbatim source text.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

Axis = Literal["type", "stage", "agent", "onset", "site"]


class Citation(BaseModel):
    clause_id: str
    quote: str


class AxisRule(BaseModel):
    axis: Axis
    level: Literal["required", "recommended"]
    evidence_terms: list[str] = Field(min_length=1)


class DiagnosisRequirement(BaseModel):
    condition: str
    synonyms: list[str] = Field(min_length=1)
    axes: list[AxisRule] = Field(min_length=1)
    recommendation: str
    citations: list[Citation] = Field(min_length=1)


def load_requirements(directory: Path) -> list[DiagnosisRequirement]:
    entries: list[DiagnosisRequirement] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        try:
            entries.append(DiagnosisRequirement.model_validate(raw))
        except ValidationError as error:
            raise ValueError(f"invalid requirement file {path.name}: {error}") from error
    return entries
```

- [ ] **Step 4: Write the worked entry** `data/requirements/chronic-kidney-disease.yaml`

The `quote` below is verbatim from the booklet's *Documenting for Specificity* chapter (verified during corpus analysis; V2 will re-verify it against the built clause store). The `clause_id` must be the real one from the built store — after Task 3, find it with:
`/c/python/python -c "from cdi_kb import config; from cdi_kb.extract import extract_pages; from cdi_kb.clauses import chunk_booklet; from cdi_kb.normalize import normalize; print([c.clause_id for c in chunk_booklet(extract_pages(config.BOOKLET_PDF, config.RAW_TEXT_DIR)) if 'stage 1 through to 5' in normalize(c.text)])"`

```yaml
condition: chronic kidney disease
synonyms: [CKD, chronic renal failure, chronic kidney failure, chronic renal impairment]
axes:
  - axis: stage
    level: required
    evidence_terms: ["stage 1", "stage 2", "stage 3", "stage 4", "stage 5",
                     "stage i", "stage ii", "stage iii", "stage iv", "stage v",
                     "esrd", "end stage", "end-stage"]
  - axis: onset
    level: recommended
    evidence_terms: ["acute on chronic", "progressive", "new", "known", "long-standing"]
recommendation: >-
  Chronic kidney disease is documented without a stage. Please document the
  CKD stage (1-5, or end-stage) and its basis (eGFR), if known.
citations:
  - clause_id: "CDI-2021/documenting-for-specificity/p3"   # replace with the real id printed above
    quote: >-
      A disease may be described as 1st, 2nd, 3rd or 4th degree; or Stage 1
      through to 5. For example, a second degree burn or chronic kidney
      failure stage 4.
```

- [ ] **Step 5: Run to verify pass**

Run: `/c/python/python -m pytest tests/test_requirements_model.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/cdi_kb/requirements_model.py data/requirements tests/test_requirements_model.py && git commit -m "feat: layer 3 requirement model with CKD worked entry"
```

---

### Task 6: Quote helper CLI + author the remaining 19 requirement entries

**Files:**
- Create: `src/cdi_kb/cli.py` (first two subcommands), `data/requirements/*.yaml` (19 files)
- Test: `tests/test_requirements_complete.py`

**Interfaces:**
- Consumes: everything from Tasks 2–5
- Produces: `build_kb() -> tuple[int, int]` (clause count, indexed count) and `main(argv: list[str] | None = None) -> int` in `cli.py` with subcommands `build-kb` and `quote <search-text>`; 20 total requirement YAMLs. `EXPECTED_CONDITIONS` (the canonical list of 20 condition strings) lives in `requirements_model.py` — later tasks import it.

- [ ] **Step 1: Add `EXPECTED_CONDITIONS` to `requirements_model.py`** (append at module end)

```python
EXPECTED_CONDITIONS: tuple[str, ...] = (
    "sepsis", "pneumonia", "diabetes mellitus", "chronic kidney disease",
    "acute kidney injury", "anemia", "acute respiratory failure", "heart failure",
    "malnutrition", "fracture", "urinary tract infection", "delirium",
    "copd exacerbation", "pressure injury", "stroke", "surgical wound infection",
    "obesity", "myocardial ischemia", "deconditioning", "adverse medication event",
)
```

- [ ] **Step 2: Write `src/cdi_kb/cli.py`** with `build-kb` and `quote`

```python
"""Command-line entry points: python -m cdi_kb.cli <command>."""

import argparse
import sys

from cdi_kb import config
from cdi_kb.clauses import ClauseStore, chunk_booklet
from cdi_kb.extract import extract_pages
from cdi_kb.index import SearchIndex
from cdi_kb.normalize import normalize


def build_kb() -> tuple[int, int]:
    pages = extract_pages(config.BOOKLET_PDF, config.RAW_TEXT_DIR)
    clauses = chunk_booklet(pages)
    store = ClauseStore(config.KB_DB)
    store.rebuild(clauses)
    store.close()
    index = SearchIndex(config.KB_DB)
    index.rebuild(clauses)
    index.close()
    return len(clauses), len(clauses)


def _cmd_quote(search_text: str) -> int:
    """Authoring aid: print clauses containing the text, for copy-pasting verbatim quotes."""
    store = ClauseStore(config.KB_DB)
    needle = normalize(search_text)
    matches = [c for c in store.all() if needle in normalize(c.text)]
    store.close()
    for clause in matches[:10]:
        print(f"--- {clause.clause_id} (page {clause.page}) ---")
        print(clause.text)
        print()
    print(f"{len(matches)} clause(s) matched")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cdi_kb")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build-kb", help="extract, chunk, store, and index the corpus")
    quote = sub.add_parser("quote", help="find clauses containing text (for authoring citations)")
    quote.add_argument("search_text")
    args = parser.parse_args(argv)
    if args.command == "build-kb":
        stored, indexed = build_kb()
        print(f"clauses stored: {stored}, indexed: {indexed}")
        return 0
    if args.command == "quote":
        return _cmd_quote(args.search_text)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Build the KB**

Run: `/c/python/python -m cdi_kb.cli build-kb`
Expected: `clauses stored: <N>, indexed: <N>` with N > 200.

- [ ] **Step 4: Author the 19 remaining YAMLs.** For each row below, create `data/requirements/<slug>.yaml` following the exact CKD file shape from Task 5. Procedure per file — this is the review-against-source step and it is not optional:
  1. Run `/c/python/python -m cdi_kb.cli quote "<probe text>"` using the probe from the table (and variants) to find the governing clause in the *actual booklet text*.
  2. Copy the `clause_id` and a 1–3 sentence **verbatim** quote from the printed clause into `citations`. Never retype or paraphrase — copy from the command output.
  3. If no booklet clause supports a planned axis, **drop that axis or downgrade to `recommended`** and note it in the YAML as a comment — the KB must not claim authority the source doesn't contain.

| condition (exact string) | synonyms | required axes (evidence_terms to include) | quote probe |
|---|---|---|---|
| sepsis | septicemia, septicaemia, urosepsis, septic shock | agent ("due to", organism names: staphylococcus, e.coli, klebsiella, pseudomonas, streptococcus, "culture"); type ("severe sepsis", "septic shock") | "sepsis due to" |
| pneumonia | CAP, HAP, chest infection, LRTI | onset ("community acquired", "hospital acquired", "aspiration"); agent (organism names as sepsis + "due to") | "pneumonia due to" |
| diabetes mellitus | DM, T2DM, T1DM, diabetic | type ("type 1", "type 2", "type i", "type ii"); site→use axis `type` only if booklet lacks complication linkage text — check probe | "diabetes" |
| acute kidney injury | AKI, acute renal failure | onset ("acute on chronic", "acute"); type ("pre-renal", "prerenal", "intrinsic", "post-renal") | "acute on chronic" |
| anemia | anaemia, low hemoglobin, low haemoglobin | type ("iron deficiency", "of chronic disease", "post-hemorrhagic", "post-haemorrhagic", "macrocytic", "microcytic") | "anaemia" |
| acute respiratory failure | respiratory failure, ARF | type ("hypoxic", "hypercapnic", "type 1", "type 2"); onset ("acute", "acute on chronic") | "respiratory" |
| heart failure | HF, CCF, CHF, cardiac failure | type ("systolic", "diastolic", "HFrEF", "HFpEF", "reduced ejection", "preserved ejection"); onset ("acute", "chronic", "acute on chronic") | "acute on chronic" |
| malnutrition | malnourished, protein-energy malnutrition | type ("mild", "moderate", "severe") | "malnutrition" |
| fracture | fractured, # (exclude from synonyms — too noisy; use "fracture" stem only) | site (bone names: femur, radius, humerus, tibia, hip, wrist, metacarpal, skull, vertebra); type ("open", "closed", "pathological", "stress", "displaced") | "fracture" |
| urinary tract infection | UTI, cystitis, pyelonephritis | agent ("due to", "e.coli", "e. coli", organism names); site ("cystitis", "pyelonephritis", "lower", "upper") | "urinary tract infection due" |
| delirium | acute confusional state, acutely confused | onset ("hospital acquired", "new", "acute"); type→drop if unsupported by booklet | "delirium" |
| copd exacerbation | COPD, chronic obstructive pulmonary disease exacerbation, infective exacerbation | type ("infective", "non-infective"); onset ("acute") | "exacerbation" |
| pressure injury | pressure ulcer, bedsore, decubitus | stage ("stage 1".."stage 4", "unstageable"); site (sacrum, heel, buttock, hip); onset ("present on admission", "hospital acquired") | "pressure" |
| stroke | CVA, cerebrovascular accident | type ("ischemic", "ischaemic", "hemorrhagic", "haemorrhagic"); onset ("sequela") | "sequela" |
| surgical wound infection | post-op wound infection, surgical site infection, SSI | onset ("complicating surgery", "post procedural", "complication"); agent (organism names) | "complication" |
| obesity | obese, morbid obesity | type ("morbid", "class"); stage ("BMI") | "obesity" |
| myocardial ischemia | NSTEMI, STEMI, unstable angina, demand ischemia, ACS | type ("NSTEMI", "STEMI", "unstable angina", "demand") | "myocardial" |
| deconditioning | deconditioned, functional decline | type→single required axis `type` with evidence_terms describing functional detail ("mobility", "functional", "adl") — check probe first | "deconditioning" |
| adverse medication event | adverse drug reaction, adverse effect, drug reaction | agent (drug link: "due to", "adverse effect of", "secondary to"); onset ("accidental", "intentional") | "adverse" |

Recommendation text for each: one sentence naming the gap + one **non-leading** ask, modeled on the CKD example ("...is documented without X. Please document X, if known." — never suggest a specific answer value).

- [ ] **Step 5: Write the completeness test** in `tests/test_requirements_complete.py`

```python
from cdi_kb import config
from cdi_kb.requirements_model import EXPECTED_CONDITIONS, load_requirements


def test_all_20_conditions_present_and_valid() -> None:
    entries = load_requirements(config.REQUIREMENTS_DIR)
    conditions = {e.condition for e in entries}
    missing = set(EXPECTED_CONDITIONS) - conditions
    assert not missing, f"missing requirement entries: {sorted(missing)}"
    for entry in entries:
        assert any(a.level == "required" for a in entry.axes), f"{entry.condition}: no required axis"
        assert all(c.quote.strip() for c in entry.citations), f"{entry.condition}: empty quote"
```

- [ ] **Step 6: Run to verify pass**

Run: `/c/python/python -m pytest tests/test_requirements_complete.py tests/test_requirements_model.py -v`
Expected: all passed.

- [ ] **Step 7: Commit**

```bash
git add src/cdi_kb/cli.py src/cdi_kb/requirements_model.py data/requirements tests/test_requirements_complete.py && git commit -m "feat: quote helper CLI and all 20 requirement entries"
```

---

### Task 7: Verification suite V1–V5 — the "complete match" gate

**Files:**
- Create: `src/cdi_kb/verify.py`
- Modify: `src/cdi_kb/cli.py` (add `verify` subcommand)
- Test: `tests/test_kb_verification.py`

**Interfaces:**
- Consumes: all of Layers 1–3
- Produces: `VerificationReport` (dataclass: `passed: bool`, `failures: list[str]`, `stats: dict[str, int]`) and `run_verification() -> VerificationReport`. This is the gate the user asked for: **every layer reviewed against the shared documents, complete match.**

- [ ] **Step 1: Write the failing tests** in `tests/test_kb_verification.py`

```python
"""V1-V5: prove the KB matches the source documents. Requires `build-kb` run first."""

from cdi_kb import config
from cdi_kb.verify import run_verification


def test_kb_verification_all_checks_pass() -> None:
    report = run_verification()
    assert report.passed, "KB verification failures:\n" + "\n".join(report.failures)


def test_stats_are_reported() -> None:
    report = run_verification()
    assert report.stats["clauses"] > 200
    assert report.stats["requirements"] == 20
    assert report.stats["citations_checked"] >= 20
```

- [ ] **Step 2: Run to verify failure**

Run: `/c/python/python -m pytest tests/test_kb_verification.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cdi_kb.verify'`

- [ ] **Step 3: Implement** `src/cdi_kb/verify.py`

```python
"""KB verification: five checks proving every layer matches the source PDFs.

V1  Extraction fidelity: every stored clause text occurs in the raw page text.
V2  Citation integrity: every requirement citation's quote matches its clause
    (find_quote >= threshold) and its clause_id resolves in Layer 1.
V3  Retrieval adequacy: for every requirement, searching the condition +
    required-axis name retrieves the cited clause's section in the top 5.
V4  is enforced structurally at runtime in findings.py (tested in Task 8/9).
V5  Coverage: all EXPECTED_CONDITIONS have an entry with a required axis.
"""

from dataclasses import dataclass, field

from cdi_kb import config
from cdi_kb.clauses import ClauseStore
from cdi_kb.extract import extract_pages
from cdi_kb.index import SearchIndex
from cdi_kb.normalize import find_quote, normalize
from cdi_kb.requirements_model import EXPECTED_CONDITIONS, load_requirements


@dataclass
class VerificationReport:
    passed: bool
    failures: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


def run_verification() -> VerificationReport:
    failures: list[str] = []
    pages = extract_pages(config.BOOKLET_PDF, config.RAW_TEXT_DIR)
    full_source = normalize(" ".join(page.text for page in pages))
    store = ClauseStore(config.KB_DB)
    index = SearchIndex(config.KB_DB)
    clauses = store.all()
    requirements = load_requirements(config.REQUIREMENTS_DIR)

    # V1 — every clause is verbatim source text
    for clause in clauses:
        if normalize(clause.text) not in full_source:
            failures.append(f"V1 {clause.clause_id}: clause text not found in source PDF")

    # V2 — every citation quote matches its clause
    citations_checked = 0
    for req in requirements:
        for citation in req.citations:
            citations_checked += 1
            clause = store.get(citation.clause_id)
            if clause is None:
                failures.append(f"V2 {req.condition}: clause_id {citation.clause_id} does not resolve")
                continue
            match = find_quote(citation.quote, clause.text, config.QUOTE_MATCH_THRESHOLD)
            if not match.found:
                failures.append(
                    f"V2 {req.condition}: quote does not match {citation.clause_id} (score {match.score})"
                )

    # V3 — retrieval finds the cited section
    for req in requirements:
        required_axes = [a.axis for a in req.axes if a.level == "required"]
        query = f"{req.condition} {' '.join(required_axes)}"
        hits = index.search(query, expansions=req.synonyms, limit=5)
        cited_sections = {c.clause_id.rsplit("/", 1)[0] for c in
                          filter(None, (store.get(cit.clause_id) for cit in req.citations))}
        hit_sections = {h.clause_id.rsplit("/", 1)[0] for h in hits}
        if cited_sections and not cited_sections & hit_sections:
            failures.append(f"V3 {req.condition}: cited section not in top-5 for query '{query}'")

    # V5 — coverage
    present = {r.condition for r in requirements}
    for condition in EXPECTED_CONDITIONS:
        if condition not in present:
            failures.append(f"V5 missing requirement entry: {condition}")
    for req in requirements:
        if not any(a.level == "required" for a in req.axes):
            failures.append(f"V5 {req.condition}: no required axis")

    store.close()
    index.close()
    return VerificationReport(
        passed=not failures,
        failures=failures,
        stats={"clauses": len(clauses), "requirements": len(requirements),
               "citations_checked": citations_checked},
    )
```

- [ ] **Step 4: Add the `verify` subcommand to `cli.py`.** In `main()`, register `sub.add_parser("verify", help="run V1-V5 KB verification")` and handle:

```python
    if args.command == "verify":
        from cdi_kb.verify import run_verification  # placed with other imports at module top
        report = run_verification()
        for failure in report.failures:
            print(f"FAIL  {failure}")
        print(f"stats: {report.stats}")
        print("VERIFICATION PASSED" if report.passed else "VERIFICATION FAILED")
        return 0 if report.passed else 1
```

(Move the import to module level with the others — shown inline here only for placement clarity.)

- [ ] **Step 5: Run and fix data until green.** Run: `/c/python/python -m cdi_kb.cli verify` then `/c/python/python -m pytest tests/test_kb_verification.py -v`.
Expected: `VERIFICATION PASSED`, 2 tests passed. **Fix direction:** V2 failures mean a YAML quote was paraphrased or the clause_id is stale — re-run the Task 6 quote procedure for that file; V3 failures mean the query terms don't reach the cited section — first check the citation targets the truly governing section; only then add the condition name to `evidence_terms`-independent synonyms. Never weaken thresholds to pass.

- [ ] **Step 6: Commit**

```bash
git add src/cdi_kb/verify.py src/cdi_kb/cli.py tests/test_kb_verification.py && git commit -m "feat: V1-V5 KB verification suite (complete-match gate)"
```

---

### Task 8: Deterministic audit core — condition detection, axis scan, gap check

**Files:**
- Create: `src/cdi_kb/gapcheck.py`
- Test: `tests/test_gapcheck.py`

**Interfaces:**
- Consumes: `DiagnosisRequirement`, `AxisRule`
- Produces:
  - `ConditionMention` (frozen dataclass): `condition: str`, `matched_text: str`, `start: int`, `end: int`, `negated: bool`
  - `Gap` (frozen dataclass): `condition: str`, `axis: str`, `level: str`, `mention: ConditionMention`
  - `detect_conditions(note_text: str, requirements: list[DiagnosisRequirement]) -> list[ConditionMention]`
  - `scan_axes(note_text: str, requirement: DiagnosisRequirement) -> set[str]` (axes with evidence present)
  - `find_gaps(note_text: str, requirements: list[DiagnosisRequirement]) -> list[Gap]`
- Known demo limitation (document in module docstring, do not silently fix): axis evidence is scanned note-wide, not attributed per condition mention.

- [ ] **Step 1: Write the failing tests** in `tests/test_gapcheck.py`

```python
from cdi_kb.gapcheck import detect_conditions, find_gaps, scan_axes
from cdi_kb.requirements_model import AxisRule, Citation, DiagnosisRequirement

CKD = DiagnosisRequirement(
    condition="chronic kidney disease",
    synonyms=["CKD", "chronic renal failure"],
    axes=[AxisRule(axis="stage", level="required",
                   evidence_terms=["stage 1", "stage 2", "stage 3", "stage 4", "stage 5", "esrd"])],
    recommendation="CKD is documented without a stage. Please document the stage, if known.",
    citations=[Citation(clause_id="CDI-2021/x/p1", quote="q")],
)


def test_detects_condition_via_synonym_case_insensitive() -> None:
    mentions = detect_conditions("Known CKD, on follow-up.", [CKD])
    assert len(mentions) == 1
    assert mentions[0].condition == "chronic kidney disease"
    assert not mentions[0].negated


def test_word_boundary_no_substring_hits() -> None:
    assert detect_conditions("Buckderm cream applied.", [CKD]) == []  # 'ckd' inside a word


def test_negation_window_suppresses() -> None:
    mentions = detect_conditions("No evidence of chronic kidney disease.", [CKD])
    assert len(mentions) == 1 and mentions[0].negated


def test_axis_present_when_evidence_term_found() -> None:
    assert scan_axes("CKD stage 4 secondary to diabetes", CKD) == {"stage"}


def test_gap_raised_when_required_axis_absent() -> None:
    gaps = find_gaps("Patient has CKD, on regular follow-up.", [CKD])
    assert [(g.condition, g.axis, g.level) for g in gaps] == [("chronic kidney disease", "stage", "required")]


def test_no_gap_when_axis_documented_or_condition_negated() -> None:
    assert find_gaps("CKD stage 3b, stable.", [CKD]) == []
    assert find_gaps("Denies chronic kidney disease.", [CKD]) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `/c/python/python -m pytest tests/test_gapcheck.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cdi_kb.gapcheck'`

- [ ] **Step 3: Implement** `src/cdi_kb/gapcheck.py`

```python
"""Deterministic audit core: condition detection, axis evidence scan, gap check.

Demo limitations (accepted, documented): (1) axis evidence is scanned across
the whole note, not attributed to a specific condition mention; (2) negation
is a fixed cue window, not full ConText. Both are called out in the proposal
as the points where the production NLP/LLM stage takes over.
"""

import re
from dataclasses import dataclass

from cdi_kb.requirements_model import DiagnosisRequirement

_NEGATION_CUES = ("no ", "not ", "denies", "denied", "without", "negative for",
                  "ruled out", "no evidence of", "resolved")
_NEGATION_WINDOW_CHARS = 40


@dataclass(frozen=True)
class ConditionMention:
    condition: str
    matched_text: str
    start: int
    end: int
    negated: bool


@dataclass(frozen=True)
class Gap:
    condition: str
    axis: str
    level: str
    mention: ConditionMention


def _term_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", re.IGNORECASE)


def _is_negated(note_text: str, start: int) -> bool:
    window = note_text[max(0, start - _NEGATION_WINDOW_CHARS) : start].lower()
    return any(cue in window for cue in _NEGATION_CUES)


def detect_conditions(note_text: str, requirements: list[DiagnosisRequirement]) -> list[ConditionMention]:
    mentions: list[ConditionMention] = []
    for req in requirements:
        terms = sorted({req.condition, *req.synonyms}, key=len, reverse=True)
        claimed: list[tuple[int, int]] = []
        for term in terms:
            for match in _term_pattern(term).finditer(note_text):
                if any(match.start() < end and match.end() > start for start, end in claimed):
                    continue  # longer term already claimed this span
                claimed.append((match.start(), match.end()))
                mentions.append(ConditionMention(
                    condition=req.condition, matched_text=match.group(0),
                    start=match.start(), end=match.end(),
                    negated=_is_negated(note_text, match.start()),
                ))
    return sorted(mentions, key=lambda m: m.start)


def scan_axes(note_text: str, requirement: DiagnosisRequirement) -> set[str]:
    present: set[str] = set()
    for rule in requirement.axes:
        if any(_term_pattern(term).search(note_text) for term in rule.evidence_terms):
            present.add(rule.axis)
    return present


def find_gaps(note_text: str, requirements: list[DiagnosisRequirement]) -> list[Gap]:
    by_condition = {req.condition: req for req in requirements}
    gaps: list[Gap] = []
    seen: set[tuple[str, str]] = set()
    for mention in detect_conditions(note_text, requirements):
        if mention.negated:
            continue
        req = by_condition[mention.condition]
        present = scan_axes(note_text, req)
        for rule in req.axes:
            key = (mention.condition, rule.axis)
            if rule.axis not in present and key not in seen:
                seen.add(key)
                gaps.append(Gap(condition=mention.condition, axis=rule.axis,
                                level=rule.level, mention=mention))
    return gaps
```

- [ ] **Step 4: Run to verify pass**

Run: `/c/python/python -m pytest tests/test_gapcheck.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cdi_kb/gapcheck.py tests/test_gapcheck.py && git commit -m "feat: deterministic condition/axis/gap detection"
```

---

### Task 9: Findings composition + audit orchestration (runtime citation firewall)

**Files:**
- Create: `src/cdi_kb/findings.py`, `src/cdi_kb/audit.py`
- Test: `tests/test_findings.py`, `tests/test_audit.py`

**Interfaces:**
- Consumes: `Gap`, `find_gaps`, `ClauseStore`, `find_quote`, `load_requirements`
- Produces:
  - `VerifiedCitation` (frozen dataclass): `clause_id: str`, `section_title: str`, `page: int`, `quote: str`
  - `Finding` (frozen dataclass): `finding_type: str` (always `"specificity_gap"` in the demo), `severity: str` (`"required"` → `required`, else `recommended`), `condition: str`, `axis: str`, `evidence_excerpt: str`, `recommendation: str`, `citations: tuple[VerifiedCitation, ...]`, `dedupe_key: str`
  - `compose_finding(gap: Gap, requirement: DiagnosisRequirement, store: ClauseStore) -> Finding | None` — returns `None` (and never a citation-less Finding) when no citation verifies
  - `AuditResult` (dataclass): `findings: list[Finding]`, `dropped_citations: list[str]`
  - `run_audit(note_text: str) -> AuditResult` in `audit.py` (loads requirements + opens store per call)

- [ ] **Step 1: Write the failing tests** in `tests/test_findings.py`

```python
from pathlib import Path

from cdi_kb.clauses import Clause, ClauseStore
from cdi_kb.findings import compose_finding
from cdi_kb.gapcheck import ConditionMention, Gap
from cdi_kb.requirements_model import AxisRule, Citation, DiagnosisRequirement

CLAUSE = Clause("CDI-2021/staging/p1", "Staging", 62,
                "A disease may be described as Stage 1 through to 5.")
MENTION = ConditionMention("chronic kidney disease", "CKD", 12, 15, negated=False)
GAP = Gap("chronic kidney disease", "stage", "required", MENTION)


def _store(tmp_path: Path, clauses: list[Clause]) -> ClauseStore:
    store = ClauseStore(tmp_path / "kb.sqlite")
    store.rebuild(clauses)
    return store


def _req(quote: str) -> DiagnosisRequirement:
    return DiagnosisRequirement(
        condition="chronic kidney disease", synonyms=["CKD"],
        axes=[AxisRule(axis="stage", level="required", evidence_terms=["stage 4"])],
        recommendation="Please document the stage, if known.",
        citations=[Citation(clause_id="CDI-2021/staging/p1", quote=quote)],
    )


def test_verified_citation_produces_finding(tmp_path) -> None:
    finding = compose_finding(GAP, _req("Stage 1 through to 5"), _store(tmp_path, [CLAUSE]))
    assert finding is not None
    assert finding.severity == "required"
    assert finding.citations[0].clause_id == "CDI-2021/staging/p1"
    assert finding.dedupe_key == "chronic kidney disease|stage"


def test_fabricated_quote_yields_no_finding(tmp_path) -> None:
    # The firewall: a quote not in the clause text must kill the finding entirely.
    finding = compose_finding(GAP, _req("clinicians must always record the stage"), _store(tmp_path, [CLAUSE]))
    assert finding is None


def test_unresolvable_clause_id_yields_no_finding(tmp_path) -> None:
    finding = compose_finding(GAP, _req("Stage 1 through to 5"), _store(tmp_path, []))
    assert finding is None
```

- [ ] **Step 2: Write the failing tests** in `tests/test_audit.py` (integration — needs built KB + the 20 YAMLs)

```python
from cdi_kb.audit import run_audit


def test_ckd_without_stage_yields_cited_finding() -> None:
    result = run_audit("Patient admitted with pneumonia due to klebsiella, community acquired. Known CKD.")
    keys = {f.dedupe_key for f in result.findings}
    assert "chronic kidney disease|stage" in keys
    for finding in result.findings:
        assert finding.citations, f"finding without citation escaped: {finding.dedupe_key}"


def test_fully_specified_note_yields_no_ckd_stage_finding() -> None:
    result = run_audit("CKD stage 4 (eGFR 22), stable.")
    assert "chronic kidney disease|stage" not in {f.dedupe_key for f in result.findings}


def test_empty_note() -> None:
    assert run_audit("").findings == []
```

- [ ] **Step 3: Run to verify failure**

Run: `/c/python/python -m pytest tests/test_findings.py tests/test_audit.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement** `src/cdi_kb/findings.py`

```python
"""Finding composition with the runtime citation firewall (proposal 2.2):
a Finding without at least one verified citation is never created."""

from dataclasses import dataclass

from cdi_kb.clauses import ClauseStore
from cdi_kb.config import QUOTE_MATCH_THRESHOLD
from cdi_kb.gapcheck import Gap
from cdi_kb.normalize import find_quote
from cdi_kb.requirements_model import DiagnosisRequirement


@dataclass(frozen=True)
class VerifiedCitation:
    clause_id: str
    section_title: str
    page: int
    quote: str


@dataclass(frozen=True)
class Finding:
    finding_type: str
    severity: str
    condition: str
    axis: str
    evidence_excerpt: str
    recommendation: str
    citations: tuple[VerifiedCitation, ...]
    dedupe_key: str


def compose_finding(gap: Gap, requirement: DiagnosisRequirement, store: ClauseStore) -> Finding | None:
    verified: list[VerifiedCitation] = []
    for citation in requirement.citations:
        clause = store.get(citation.clause_id)
        if clause is None:
            continue
        if find_quote(citation.quote, clause.text, QUOTE_MATCH_THRESHOLD).found:
            verified.append(VerifiedCitation(
                clause_id=clause.clause_id, section_title=clause.section_title,
                page=clause.page, quote=citation.quote,
            ))
    if not verified:
        return None
    return Finding(
        finding_type="specificity_gap",
        severity="required" if gap.level == "required" else "recommended",
        condition=gap.condition,
        axis=gap.axis,
        evidence_excerpt=gap.mention.matched_text,
        recommendation=requirement.recommendation,
        citations=tuple(verified),
        dedupe_key=f"{gap.condition}|{gap.axis}",
    )
```

- [ ] **Step 5: Implement** `src/cdi_kb/audit.py`

```python
"""Audit orchestration: note text -> gaps -> citation-verified findings."""

from dataclasses import dataclass, field

from cdi_kb import config
from cdi_kb.clauses import ClauseStore
from cdi_kb.findings import Finding, compose_finding
from cdi_kb.gapcheck import find_gaps
from cdi_kb.requirements_model import load_requirements


@dataclass
class AuditResult:
    findings: list[Finding] = field(default_factory=list)
    dropped_citations: list[str] = field(default_factory=list)


def run_audit(note_text: str) -> AuditResult:
    if not note_text.strip():
        return AuditResult()
    requirements = load_requirements(config.REQUIREMENTS_DIR)
    by_condition = {req.condition: req for req in requirements}
    store = ClauseStore(config.KB_DB)
    result = AuditResult()
    for gap in find_gaps(note_text, requirements):
        finding = compose_finding(gap, by_condition[gap.condition], store)
        if finding is None:
            result.dropped_citations.append(f"{gap.condition}|{gap.axis}")
        else:
            result.findings.append(finding)
    store.close()
    return result
```

- [ ] **Step 6: Run to verify pass**

Run: `/c/python/python -m pytest tests/test_findings.py tests/test_audit.py -v`
Expected: 6 passed. (`test_audit` failures usually mean a Task 6 YAML gap — e.g., pneumonia axes firing on the sample note text; adjust the note strings in the test only if the finding raised is *correct* per the requirement files.)

- [ ] **Step 7: Commit**

```bash
git add src/cdi_kb/findings.py src/cdi_kb/audit.py tests/test_findings.py tests/test_audit.py && git commit -m "feat: findings composition and audit loop with citation firewall"
```

---

### Task 10: LLM stage — implicit (treated-but-not-named) condition inference

**Files:**
- Create: `src/cdi_kb/llm_infer.py`
- Modify: `src/cdi_kb/audit.py`
- Test: `tests/test_llm_infer.py`

**Interfaces:**
- Consumes: `EXPECTED_CONDITIONS`, `config.ANTHROPIC_MODEL`
- Produces: `infer_implicit_conditions(note_text: str, known_conditions: tuple[str, ...]) -> list[ImplicitFinding]` where `ImplicitFinding` is a pydantic model: `condition: str`, `evidence: str`. `run_audit` gains keyword-only param `use_llm: bool = False`; inferred conditions re-enter the same gap→finding path (so the citation firewall still governs them). Containment: any inferred condition not in `known_conditions` is discarded; the model can only *select*, never invent.

- [ ] **Step 1: Write the tests** in `tests/test_llm_infer.py`

```python
import pytest

from cdi_kb.llm_infer import ImplicitFinding, filter_to_known


def test_filter_discards_unknown_conditions() -> None:
    raw = [ImplicitFinding(condition="sepsis", evidence="on norepinephrine, lactate 4"),
           ImplicitFinding(condition="dragon pox", evidence="scales noted")]
    kept = filter_to_known(raw, ("sepsis", "pneumonia"))
    assert [f.condition for f in kept] == ["sepsis"]


@pytest.mark.live
def test_live_inference_names_respiratory_failure() -> None:
    from cdi_kb.llm_infer import infer_implicit_conditions
    from cdi_kb.requirements_model import EXPECTED_CONDITIONS

    note = "Sats 82% on air, placed on high-flow oxygen then BiPAP overnight. ABG: pO2 54."
    inferred = infer_implicit_conditions(note, EXPECTED_CONDITIONS)
    assert "acute respiratory failure" in [f.condition for f in inferred]
```

- [ ] **Step 2: Run to verify failure**

Run: `/c/python/python -m pytest tests/test_llm_infer.py -v`
Expected: FAIL (`ModuleNotFoundError`); note the live test is deselected by default (`-m 'not live'`).

- [ ] **Step 3: Implement** `src/cdi_kb/llm_infer.py`

```python
"""Optional LLM stage: infer conditions that are treated but never named
(e.g. oxygen support without 'respiratory failure' — proposal top-20 rows
1, 7, 9, 12, 19). The model selects only from the known condition list;
anything else is discarded. Citations still come exclusively from the
requirement model + clause store, so this stage cannot fabricate authority.
"""

import anthropic
from pydantic import BaseModel

from cdi_kb.config import ANTHROPIC_MODEL


class ImplicitFinding(BaseModel):
    condition: str
    evidence: str


class ImplicitFindings(BaseModel):
    findings: list[ImplicitFinding]


_SYSTEM = (
    "You are a clinical documentation integrity checker. Given a clinical note, "
    "identify conditions from the ALLOWED LIST ONLY that are clinically evident "
    "(e.g. being treated) but never named in the note. Return the exact condition "
    "string from the list and the note evidence. If none, return an empty list. "
    "Never return a condition that is already explicitly named in the note."
)


def filter_to_known(findings: list[ImplicitFinding], known: tuple[str, ...]) -> list[ImplicitFinding]:
    allowed = set(known)
    return [f for f in findings if f.condition in allowed]


def infer_implicit_conditions(note_text: str, known_conditions: tuple[str, ...]) -> list[ImplicitFinding]:
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=ANTHROPIC_MODEL,
        max_tokens=2000,
        system=_SYSTEM,
        messages=[{
            "role": "user",
            "content": f"ALLOWED LIST: {list(known_conditions)}\n\nNOTE:\n{note_text}",
        }],
        output_format=ImplicitFindings,
    )
    return filter_to_known(response.parsed_output.findings, known_conditions)
```

- [ ] **Step 4: Wire into `audit.py`.** Change the `run_audit` signature to `def run_audit(note_text: str, *, use_llm: bool = False) -> AuditResult:` and, after the deterministic gap loop, add:

```python
    if use_llm:
        from cdi_kb.llm_infer import infer_implicit_conditions  # module-level import in real code
        named = {gap_key.split("|")[0] for gap_key in
                 {f.dedupe_key for f in result.findings} | set(result.dropped_citations)}
        for implicit in infer_implicit_conditions(note_text, tuple(by_condition)):
            req = by_condition[implicit.condition]
            if implicit.condition in named:
                continue
            synthetic_note = f"{note_text}\n[assessment: {implicit.condition}]"
            for gap in find_gaps(synthetic_note, [req]):
                finding = compose_finding(gap, req, store)
                if finding is not None:
                    result.findings.append(finding)
```

(Put the import at module top with the others; `anthropic` is imported lazily inside `llm_infer` usage only in the sense that the module is only imported when `use_llm=True` — keep `audit.py` importable offline by placing `from cdi_kb.llm_infer import infer_implicit_conditions` inside the `if use_llm:` block with a `# inline import: keeps offline path free of the anthropic dependency` justification comment.) Note `store.close()` must move after this block.

- [ ] **Step 5: Run offline tests, then live test**

Run: `/c/python/python -m pytest tests/test_llm_infer.py tests/test_audit.py -v`
Expected: offline tests pass, live deselected.
Run (requires credentials): `/c/python/python -m pytest tests/test_llm_infer.py -m live -v`
Expected: 1 passed. If credentials are unavailable, record that the live test is pending and continue — it gates the demo run (Task 14), not the merge.

- [ ] **Step 6: Commit**

```bash
git add src/cdi_kb/llm_infer.py src/cdi_kb/audit.py tests/test_llm_infer.py && git commit -m "feat: LLM implicit-condition inference behind citation firewall"
```

---

### Task 11: CLI completion — `audit` and `demo` subcommands

**Files:**
- Modify: `src/cdi_kb/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `python -m cdi_kb.cli audit <note.txt> [--llm] [--json]` printing findings (human or JSON), exit 0; `python -m cdi_kb.cli demo [--port 8000]` launching the web UI (Task 13's `webapp:app` via `uvicorn.run`).

- [ ] **Step 1: Write the failing tests** in `tests/test_cli.py`

```python
import json

from cdi_kb.cli import main


def test_audit_command_json_output(tmp_path, capsys) -> None:
    note = tmp_path / "note.txt"
    note.write_text("Known CKD, on regular follow-up.", encoding="utf-8")
    exit_code = main(["audit", str(note), "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(f["dedupe_key"] == "chronic kidney disease|stage" for f in payload["findings"])


def test_audit_command_human_output(tmp_path, capsys) -> None:
    note = tmp_path / "note.txt"
    note.write_text("Known CKD.", encoding="utf-8")
    assert main(["audit", str(note)]) == 0
    out = capsys.readouterr().out
    assert "chronic kidney disease" in out and "CDI-2021/" in out
```

- [ ] **Step 2: Run to verify failure**

Run: `/c/python/python -m pytest tests/test_cli.py -v`
Expected: FAIL (argparse: invalid choice 'audit').

- [ ] **Step 3: Implement.** Add to `cli.py` imports: `import dataclasses`, `import json`, `from pathlib import Path`, `from cdi_kb.audit import run_audit`. Register subcommands in `main()`:

```python
    audit = sub.add_parser("audit", help="audit a note file against the KB")
    audit.add_argument("note_file", type=Path)
    audit.add_argument("--llm", action="store_true", help="enable implicit-condition inference")
    audit.add_argument("--json", action="store_true", dest="as_json")
    demo = sub.add_parser("demo", help="serve the paste-a-note web demo")
    demo.add_argument("--port", type=int, default=8000)
```

and handlers:

```python
    if args.command == "audit":
        result = run_audit(args.note_file.read_text(encoding="utf-8"), use_llm=args.llm)
        if args.as_json:
            print(json.dumps(dataclasses.asdict(result), indent=2))
        else:
            for finding in result.findings:
                print(f"[{finding.severity}] {finding.condition} — missing {finding.axis}")
                print(f"  {finding.recommendation}")
                for cite in finding.citations:
                    print(f"  source: {cite.clause_id} (p.{cite.page}) — \"{cite.quote[:90]}...\"")
            print(f"{len(result.findings)} finding(s)")
        return 0
    if args.command == "demo":
        import uvicorn  # inline import: server dependency only needed for demo command
        uvicorn.run("cdi_kb.webapp:app", port=args.port)
        return 0
```

- [ ] **Step 4: Run to verify pass**

Run: `/c/python/python -m pytest tests/test_cli.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cdi_kb/cli.py tests/test_cli.py && git commit -m "feat: audit and demo CLI commands"
```

---

### Task 12: Evaluation fixtures — 40 notes with expected findings

**Files:**
- Create: `data/eval/notes/` (40 files), `data/eval/expected.yaml`, `tests/test_eval_suite.py`

**Interfaces:**
- Consumes: `run_audit`, `EXPECTED_CONDITIONS`
- Produces: per diagnosis `<slug>-gap.txt` (mentions the condition via a synonym, omits every required axis's evidence terms, ~3–6 realistic sentences) and `<slug>-control.txt` (same condition with all required axes documented). `expected.yaml` maps note filename → list of expected `dedupe_key`s (gap notes) or explicitly-absent keys (controls).

- [ ] **Step 1: Author the fixtures.** Two complete examples define the pattern; author the remaining 38 the same way, checking each note's terms against that diagnosis's YAML (`evidence_terms` must NOT appear in gap notes, MUST appear in controls).

`data/eval/notes/chronic-kidney-disease-gap.txt`:

```
62M admitted with fluid overload. Background: hypertension, CKD followed by
nephrology, ex-smoker. On furosemide. Creatinine 210 on admission bloods.
Plan: daily weights, renal profile, medication review.
```

`data/eval/notes/chronic-kidney-disease-control.txt`:

```
62M admitted with fluid overload. Background: hypertension, CKD stage 4
(eGFR 22), followed by nephrology, ex-smoker. On furosemide.
Plan: daily weights, renal profile, medication review.
```

`data/eval/expected.yaml` (structure — one entry per note file; shown truncated, must cover all 40):

```yaml
chronic-kidney-disease-gap.txt:
  must_find: ["chronic kidney disease|stage"]
chronic-kidney-disease-control.txt:
  must_not_find: ["chronic kidney disease|stage"]
# ... one entry per remaining note file
```

Rules for authoring: notes are synthetic (no real patient data); gap notes may legitimately trigger findings for *other* conditions they mention — `must_find` lists only the target key, and controls assert only `must_not_find` for their target key.

- [ ] **Step 2: Write the eval test** in `tests/test_eval_suite.py`

```python
import yaml

from cdi_kb import config
from cdi_kb.audit import run_audit
from cdi_kb.requirements_model import EXPECTED_CONDITIONS


def _expected() -> dict:
    return yaml.safe_load((config.EVAL_DIR / "expected.yaml").read_text(encoding="utf-8"))


def test_every_diagnosis_has_gap_and_control_note() -> None:
    names = {p.name for p in (config.EVAL_DIR / "notes").glob("*.txt")}
    assert len(names) == 40
    assert set(_expected()) == names


def test_gap_notes_raise_expected_findings_and_controls_do_not() -> None:
    failures: list[str] = []
    for name, spec in _expected().items():
        keys = {f.dedupe_key for f in
                run_audit((config.EVAL_DIR / "notes" / name).read_text(encoding="utf-8")).findings}
        for key in spec.get("must_find", []):
            if key not in keys:
                failures.append(f"{name}: expected {key}, got {sorted(keys)}")
        for key in spec.get("must_not_find", []):
            if key in keys:
                failures.append(f"{name}: false positive {key}")
    assert not failures, "\n".join(failures)
```

- [ ] **Step 3: Run and iterate to green**

Run: `/c/python/python -m pytest tests/test_eval_suite.py -v`
Expected: 2 passed. Failures are the *point* of this task — each one is either a bad fixture (fix the note/expected.yaml) or a real detection bug (fix `gapcheck.py`/the YAML `evidence_terms`, then re-run the **whole** suite including Task 7's verification).

- [ ] **Step 4: Commit**

```bash
git add data/eval tests/test_eval_suite.py && git commit -m "test: 40-note evaluation suite for all 20 diagnoses"
```

---

### Task 13: Paste-a-note web demo (FastAPI)

**Files:**
- Create: `src/cdi_kb/webapp.py`
- Test: `tests/test_webapp.py`

**Interfaces:**
- Consumes: `run_audit`, `SearchIndex`, `config`
- Produces: FastAPI `app` with `GET /` (single-page UI), `POST /api/audit` (body `{"note_text": str, "use_llm": bool}` → `{"findings": [...], "dropped_citations": [...]}`), `GET /api/search?q=` (Layer 2 browse → `{"hits": [...]}`).

- [ ] **Step 1: Write the failing tests** in `tests/test_webapp.py`

```python
from fastapi.testclient import TestClient

from cdi_kb.webapp import app

client = TestClient(app)


def test_index_serves_ui() -> None:
    response = client.get("/")
    assert response.status_code == 200 and "CDI Audit Demo" in response.text


def test_audit_endpoint_returns_cited_findings() -> None:
    response = client.post("/api/audit", json={"note_text": "Known CKD, stable.", "use_llm": False})
    assert response.status_code == 200
    findings = response.json()["findings"]
    assert any(f["dedupe_key"] == "chronic kidney disease|stage" for f in findings)
    assert all(f["citations"] for f in findings)


def test_search_endpoint() -> None:
    response = client.get("/api/search", params={"q": "specificity stage"})
    assert response.status_code == 200 and isinstance(response.json()["hits"], list)
```

- [ ] **Step 2: Run to verify failure**

Run: `/c/python/python -m pytest tests/test_webapp.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cdi_kb.webapp'`

- [ ] **Step 3: Implement** `src/cdi_kb/webapp.py`

```python
"""Paste-a-note demo UI. Single page, no external assets."""

import dataclasses

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from cdi_kb import config
from cdi_kb.audit import run_audit
from cdi_kb.index import SearchIndex

app = FastAPI(title="CDI Audit Demo")


class AuditRequest(BaseModel):
    note_text: str
    use_llm: bool = False


@app.post("/api/audit")
def api_audit(request: AuditRequest) -> dict:
    result = run_audit(request.note_text, use_llm=request.use_llm)
    return {"findings": [dataclasses.asdict(f) for f in result.findings],
            "dropped_citations": result.dropped_citations}


@app.get("/api/search")
def api_search(q: str) -> dict:
    index = SearchIndex(config.KB_DB)
    hits = index.search(q, limit=10)
    index.close()
    return {"hits": [dataclasses.asdict(h) for h in hits]}


_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>CDI Audit Demo</title>
<style>
 body{font-family:system-ui;margin:2rem;max-width:60rem}
 textarea{width:100%;height:12rem;font-size:1rem}
 .finding{border-left:4px solid #b91c1c;background:#fef2f2;margin:.6rem 0;padding:.6rem .8rem;border-radius:4px}
 .finding.recommended{border-color:#b45309;background:#fffbeb}
 .cite{color:#555;font-size:.85rem;margin-top:.3rem}
 button{padding:.5rem 1.2rem;font-size:1rem;margin-top:.5rem}
</style></head><body>
<h1>CDI Audit Demo</h1>
<p>Paste a clinical note. Findings cite the CDI booklet verbatim — no citation, no finding.</p>
<textarea id="note" placeholder="e.g. 62M admitted with fluid overload. Background: CKD..."></textarea><br>
<label><input type="checkbox" id="llm"> infer treated-but-unnamed conditions (LLM)</label><br>
<button onclick="audit()">Audit note</button>
<div id="out"></div>
<script>
async function audit(){
  const r = await fetch('/api/audit',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({note_text:document.getElementById('note').value,
                         use_llm:document.getElementById('llm').checked})});
  const d = await r.json();
  const out = document.getElementById('out');
  out.innerHTML = '<h2>'+d.findings.length+' finding(s)</h2>';
  for(const f of d.findings){
    const div = document.createElement('div');
    div.className = 'finding '+f.severity;
    div.innerHTML = '<strong>'+f.condition+'</strong> — missing <em>'+f.axis+'</em> ('+f.severity+')'
      +'<div>'+f.recommendation+'</div>'
      +f.citations.map(c=>'<div class="cite">source: '+c.clause_id+' (p.'+c.page+') — “'+c.quote+'”</div>').join('');
    out.appendChild(div);
  }
}
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _PAGE
```

- [ ] **Step 4: Run to verify pass**

Run: `/c/python/python -m pytest tests/test_webapp.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cdi_kb/webapp.py tests/test_webapp.py && git commit -m "feat: paste-a-note FastAPI demo UI"
```

---

### Task 14: Full pipeline run, demo runbook, and evidence capture

**Files:**
- Create: `README-DEMO.md`

- [ ] **Step 1: Clean rebuild + full offline suite**

```bash
cd /d/CDI && rm -rf var && /c/python/python -m cdi_kb.cli build-kb && /c/python/python -m cdi_kb.cli verify && /c/python/python -m pytest -v
```

Expected: `VERIFICATION PASSED`; every test green. Paste the verify stats output into README-DEMO.md (step 3).

- [ ] **Step 2: Live LLM check (needs credentials)**

```bash
/c/python/python -m pytest -m live -v && /c/python/python -m cdi_kb.cli audit data/eval/notes/chronic-kidney-disease-gap.txt --llm
```

Expected: live test passes; audit prints the CKD stage finding (plus any LLM-inferred ones, each with citations).

- [ ] **Step 3: Write `README-DEMO.md`** — exact content skeleton (fill the two bracketed evidence blocks from real output; brackets must not survive into the committed file):

```markdown
# CDI Audit KB — Demo Runbook

## One-time setup
    /c/python/python -m pip install -e ".[dev]"
    /c/python/python -m cdi_kb.cli build-kb

## Prove the KB matches the source documents
    /c/python/python -m cdi_kb.cli verify
Latest run: [paste stats + VERIFICATION PASSED line]

## Run the demo
    /c/python/python -m cdi_kb.cli demo --port 8000
Open http://localhost:8000 — paste any note from data/eval/notes/.

## CLI audit
    /c/python/python -m cdi_kb.cli audit data/eval/notes/sepsis-gap.txt

## Test suites
    /c/python/python -m pytest            # offline suite (KB verification V1-V5 + 40-note eval)
    /c/python/python -m pytest -m live    # LLM inference tests (needs ANTHROPIC credentials)
Latest offline run: [paste pytest summary line]

## What this demo proves / does not prove
Proves: 3-layer KB with citation-verified findings for 20 diagnoses; every
finding traceable to verbatim booklet text; deterministic core; LLM inference
contained behind the citation firewall.
Does not include (per proposal): CHI flowchart linearization, dense/hybrid
retrieval + reranking, the browser extension, de-identification, Arabic notes.
```

- [ ] **Step 4: Final commit**

```bash
git add README-DEMO.md && git commit -m "docs: demo runbook with verification evidence"
```

---

## Self-review notes (performed at plan time)

- **Spec coverage:** Layer 1 → Tasks 2–3; Layer 2 → Task 4; Layer 3 → Tasks 5–6; audit loop → Tasks 8–10; demo UI → Task 13; CLI → Tasks 6/11; "all layers reviewed against the shared documents, complete match" → Task 7 (V1 extraction fidelity, V2 citation match, V3 retrieval adequacy, V5 coverage) with V4 enforced structurally in Task 9's firewall tests; testing → every task + Task 12's 40-note eval.
- **Type consistency check:** `find_quote → QuoteMatch` (Tasks 1/7/9), `Clause`/`ClauseStore.get → Clause | None` (Tasks 3/7/9), `DiagnosisRequirement` field names (Tasks 5/6/8/9), `Gap.mention: ConditionMention` (Tasks 8/9), `Finding.dedupe_key = "<condition>|<axis>"` (Tasks 9/11/12/13) — all verified consistent.
- **Honest scope notes:** dense/hybrid retrieval deliberately deferred (FTS5-only behind the `SearchIndex.search` seam); axis scan is note-global, not per-mention (documented in `gapcheck.py`); CHI flowchart PDFs excluded from the demo KB (citations are booklet-only). All three are stated in README-DEMO.md so the demo never overclaims.
