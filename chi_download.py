#!/usr/bin/env python3
"""
Download document attachments (PDF / Excel / Word) linked from a CHI
(Council of Health Insurance, KSA) page.

Usage:
    python chi_download.py <url> [<url> ...] [-o OUTDIR] [--ext pdf xlsx]
                           [--delay 2.0] [--depth 1] [--dry-run]

Examples:
    # Just the Daman Drug Formulary page
    python chi_download.py https://www.chi.gov.sa/Rules/Pages/DamanDrugFormulary.aspx

    # Formulary + laws/regulations + IDF pages, PDFs and Excel, into ./kb_raw
    python chi_download.py \
        https://www.chi.gov.sa/Rules/Pages/DamanDrugFormulary.aspx \
        https://www.chi.gov.sa/knowledge-center/Pages/laws-regulations.aspx \
        https://www.chi.gov.sa/aboutchi/CCHIprograms/Pages/IDF.aspx \
        -o kb_raw --ext pdf xlsx xls docx --depth 1

    # See what it would grab without downloading
    python chi_download.py <url> --dry-run

Install:
    pip install requests beautifulsoup4

Notes:
    - Runs single-threaded with a delay between requests on purpose. These are
      public regulatory documents on a government portal; don't hammer it.
    - Skips files already present, so it's safe to re-run / resume.
    - Writes manifest.csv with source page, URL, filename, size and SHA-256 so
      you can prove document provenance later. For a clinical KB this matters
      more than it sounds -- you will need to answer "which version of the
      guideline was this finding based on?"
    - If it finds nothing, the page is likely rendering links via JavaScript.
      See the Playwright fallback note at the bottom of this file.
"""

import argparse
import csv
import hashlib
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en;q=0.8",
}

DEFAULT_EXTS = ["pdf"]
CHUNK = 1 << 16


def safe_filename(url: str, fallback: str = "document") -> str:
    """Turn a URL-encoded (often Arabic) path into a usable filename."""
    name = unquote(Path(urlparse(url).path).name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not name:
        name = fallback
    return name[:180]


def collect_links(session, page_url, exts, timeout=30):
    """Return (doc_links, page_links) found on page_url."""
    try:
        r = session.get(page_url, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  ! failed to load page: {e}", file=sys.stderr)
        return [], []

    soup = BeautifulSoup(r.text, "html.parser")
    base = r.url
    ext_pattern = re.compile(r"\.(" + "|".join(map(re.escape, exts)) + r")(\?|$)", re.I)
    host = urlparse(base).netloc

    docs, pages = [], []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "javascript:", "#")):
            continue
        full = urljoin(base, href)
        if urlparse(full).scheme not in ("http", "https"):
            continue
        if ext_pattern.search(unquote(urlparse(full).path)):
            label = " ".join(a.get_text(" ", strip=True).split())[:200]
            docs.append((full, label))
        elif urlparse(full).netloc == host and full.lower().endswith(".aspx"):
            pages.append(full)

    # de-dupe, preserve order
    seen = set()
    docs = [(u, t) for u, t in docs if not (u in seen or seen.add(u))]
    seen = set()
    pages = [u for u in pages if not (u in seen or seen.add(u))]
    return docs, pages


def download(session, url, outdir: Path, delay: float, timeout=120):
    fname = safe_filename(url)
    dest = outdir / fname
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  = skip (exists): {fname}")
        return dest, "skipped"

    try:
        with session.get(url, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(CHUNK):
                    if chunk:
                        f.write(chunk)
            tmp.rename(dest)
    except requests.RequestException as e:
        print(f"  ! {fname}: {e}", file=sys.stderr)
        return None, f"error: {e}"

    print(f"  + {fname} ({dest.stat().st_size / 1024:.0f} KB)")
    time.sleep(delay)
    return dest, "downloaded"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="Download documents linked from CHI pages.")
    ap.add_argument("urls", nargs="+", help="One or more page URLs to scrape.")
    ap.add_argument("-o", "--outdir", default="chi_docs", help="Output directory.")
    ap.add_argument("--ext", nargs="+", default=DEFAULT_EXTS,
                    help="Extensions to grab, e.g. --ext pdf xlsx docx")
    ap.add_argument("--delay", type=float, default=2.0,
                    help="Seconds between requests (default 2.0). Be polite.")
    ap.add_argument("--depth", type=int, default=0,
                    help="Follow same-site .aspx links this many levels deep (default 0).")
    ap.add_argument("--dry-run", action="store_true", help="List, don't download.")
    args = ap.parse_args()

    exts = [e.lstrip(".").lower() for e in args.ext]
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    visited, queue = set(), [(u, 0) for u in args.urls]
    found = {}  # url -> (label, source_page)

    while queue:
        page, depth = queue.pop(0)
        if page in visited:
            continue
        visited.add(page)
        print(f"\n[scan d{depth}] {unquote(page)}")

        docs, pages = collect_links(session, page, exts)
        for u, label in docs:
            found.setdefault(u, (label, page))
        print(f"  found {len(docs)} document link(s)")

        if depth < args.depth:
            queue.extend((p, depth + 1) for p in pages if p not in visited)
        time.sleep(args.delay)

    print(f"\n{'=' * 60}\n{len(found)} unique document(s)\n{'=' * 60}")

    if args.dry_run:
        for u, (label, src) in found.items():
            print(f"  {safe_filename(u)}   <- {label or '(no link text)'}")
        return

    rows = []
    for u, (label, src) in found.items():
        path, status = download(session, u, outdir, args.delay)
        rows.append({
            "filename": safe_filename(u),
            "link_text": label,
            "url": u,
            "source_page": src,
            "status": status,
            "bytes": path.stat().st_size if path and path.exists() else "",
            "sha256": sha256(path) if path and path.exists() else "",
            "retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    manifest = outdir / "manifest.csv"
    with open(manifest, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["filename"])
        w.writeheader()
        w.writerows(rows)

    ok = sum(1 for r in rows if r["status"] == "downloaded")
    print(f"\nDone. {ok} downloaded, {len(rows) - ok} skipped/failed.")
    print(f"Manifest: {manifest}")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# If this returns 0 links, the page builds its document list client-side
# (common on SharePoint). Fallback with Playwright:
#
#   pip install playwright && playwright install chromium
#
#   from playwright.sync_api import sync_playwright
#   with sync_playwright() as p:
#       b = p.chromium.launch()
#       pg = b.new_page()
#       pg.goto(URL, wait_until="networkidle")
#       html = pg.content()          # feed this into BeautifulSoup as above
#       b.close()
#
# Simplest alternative for a one-off: open the page, Ctrl+S, and pull the
# links out of the saved HTML -- for a handful of regulatory documents that
# is often faster than debugging a SharePoint renderer.
# ---------------------------------------------------------------------------
