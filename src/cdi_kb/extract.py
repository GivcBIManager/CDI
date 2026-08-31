"""PDF text extraction with a settings-keyed JSON page cache under var/raw_text/."""

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pdfplumber

# pdfplumber infers word boundaries from character x-positions. Its default
# x_tolerance of 3 points is too coarse for the two journal-typeset CHI
# guidelines (the AHA/ACC/HFSA heart failure guideline and the KDIGO CKD
# guideline): words ran together into single tokens, e.g.
# "TheclassificationforbaselineandsubsequentLVEFisshown". FTS5 then indexed each
# run as ONE term matching no condition or axis word, so 48% of the KB's clauses
# were affected and six requirement axes could not reach their own governing
# clause through retrieval.
#
# x_tolerance_ratio scales the tolerance with font size rather than fixing it in
# points, which is what these mixed-size layouts need. Measured across all 11
# sources at 0.1 / 0.15 / 0.2 and against a fixed x_tolerance of 1 / 1.5 / 2:
#
#   * 0.15 removes essentially all fusion in CHI-HF (1004 -> 1 runs on a 1-in-5
#     page sample) and is tied best on CHI-CKD (618 -> 17).
#   * 0.1 over-splits ("T A B L E" for "TABLE").
#   * The nine already-clean sources extract BYTE-IDENTICALLY under the old and
#     new settings, so this is a no-op for everything that was already correct.
#     test_already_clean_sources_are_unchanged_by_the_tolerance_setting pins that.
#
# Residual, accepted: these journals set their running headers with wide letter
# spacing ("J A C C V O L . 7 9"), which now extracts as separate characters
# rather than as a different flavour of garbage. It is page furniture, not body
# prose, and was unusable under either setting.
TEXT_EXTRACTION_KWARGS: dict[str, float] = {"x_tolerance_ratio": 0.15}


@dataclass(frozen=True)
class PageText:
    page_number: int  # 1-based physical page index
    text: str


def _settings_fingerprint() -> str:
    """Short stable hash of the extraction settings, used in the cache filename.

    The cache was keyed on the PDF stem alone. Changing the tolerance would then
    have silently kept serving the fused text forever -- and var/ is gitignored,
    so there would have been no stale file in the tree for anyone to notice.
    """
    payload = json.dumps(TEXT_EXTRACTION_KWARGS, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


def cache_path(pdf_path: Path, cache_dir: Path) -> Path:
    """Where a PDF's extracted pages are cached.

    Public because callers that pre-seed a cache (the verification tests build a
    synthetic corpus without ever writing a PDF) must agree with extract_pages on
    the filename. Hardcoding the fingerprint in a test would silently break the
    next time the extraction settings change."""
    return cache_dir / f"{pdf_path.stem}.{_settings_fingerprint()}.json"


def extract_pages(pdf_path: Path, cache_dir: Path) -> list[PageText]:
    cache_file = cache_path(pdf_path, cache_dir)
    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        return [PageText(**page) for page in cached]
    pages: list[PageText] = []
    with pdfplumber.open(pdf_path) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            pages.append(PageText(
                page_number=number,
                text=page.extract_text(**TEXT_EXTRACTION_KWARGS) or "",
            ))
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps([asdict(p) for p in pages]), encoding="utf-8")
    return pages
