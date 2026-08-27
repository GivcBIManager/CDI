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
