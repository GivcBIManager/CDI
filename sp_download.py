#!/usr/bin/env python3
"""
Enumerate and download EVERY file in a SharePoint document library, bypassing
the paginated list view entirely.

Why this exists: a SharePoint list view shows ~30 items per page. Scraping the
rendered HTML gets you page 1. The REST API returns the whole folder in one
call, plus subfolders if you recurse.

Usage:
    python sp_download.py <site> <folder> [<folder> ...] [-o OUTDIR] [--ext pdf xlsx]

Example (CHI):
    python sp_download.py https://www.chi.gov.sa \
        /Rules/Documents \
        /knowledge-center/DocLib1 \
        -o kb_raw --ext pdf xlsx xls docx

Finding the folder path: open any document from the library, look at its URL.
    https://www.chi.gov.sa/Rules/Documents/<arabic-filename>.pdf
                          ^^^^^^^^^^^^^^^^ that's the server-relative folder

Install:
    pip install requests
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json;odata=nometadata",
    "Accept-Language": "ar,en;q=0.8",
}
CHUNK = 1 << 16


def safe_filename(name: str) -> str:
    name = unquote(name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return (name or "document")[:180]


def sp_get(session, site, endpoint, timeout=60):
    """Call a SharePoint _api endpoint, return parsed JSON or None."""
    url = urljoin(site.rstrip("/") + "/", "_api/" + endpoint.lstrip("/"))
    try:
        r = session.get(url, timeout=timeout)
        if r.status_code != 200:
            print(f"  ! {r.status_code} from {endpoint[:80]}", file=sys.stderr)
            return None
        return r.json()
    except (requests.RequestException, json.JSONDecodeError) as e:
        print(f"  ! {endpoint[:80]}: {e}", file=sys.stderr)
        return None


def list_files(session, site, folder, exts, recurse=True, depth=0):
    """Recursively enumerate files in a server-relative SharePoint folder."""
    enc = quote(folder, safe="")
    indent = "  " * (depth + 1)
    print(f"{indent}[folder] {unquote(folder)}")

    out = []
    data = sp_get(session, site,
                  f"web/GetFolderByServerRelativeUrl('{enc}')/Files?$top=5000")
    if data is None:
        return out

    items = data.get("value", data.get("d", {}).get("results", []))
    for f in items:
        name = f.get("Name", "")
        if not name:
            continue
        ext = Path(name).suffix.lstrip(".").lower()
        if exts and ext not in exts:
            continue
        out.append({
            "name": name,
            "url": urljoin(site.rstrip("/") + "/", f.get("ServerRelativeUrl", "").lstrip("/")),
            "size": f.get("Length", ""),
            "modified": f.get("TimeLastModified", ""),
            "folder": folder,
        })
    print(f"{indent}  {len(out)} matching file(s) so far")

    if recurse:
        sub = sp_get(session, site,
                     f"web/GetFolderByServerRelativeUrl('{enc}')/Folders?$top=5000")
        if sub:
            subs = sub.get("value", sub.get("d", {}).get("results", []))
            for s in subs:
                sname = s.get("Name", "")
                if sname.lower() in ("forms", "_catalogs", "attachments"):
                    continue  # SharePoint plumbing, not content
                srel = s.get("ServerRelativeUrl")
                if srel:
                    out.extend(list_files(session, site, srel, exts, recurse, depth + 1))
    return out


def download(session, item, outdir: Path, delay: float):
    dest = outdir / safe_filename(item["name"])
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  = skip: {dest.name}")
        return dest, "skipped"
    try:
        with session.get(item["url"], stream=True, timeout=180) as r:
            r.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(CHUNK):
                    if chunk:
                        fh.write(chunk)
            tmp.rename(dest)
    except requests.RequestException as e:
        print(f"  ! {dest.name}: {e}", file=sys.stderr)
        return None, f"error: {e}"
    print(f"  + {dest.name} ({dest.stat().st_size / 1024:.0f} KB)")
    time.sleep(delay)
    return dest, "downloaded"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(CHUNK), b""):
            h.update(c)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("site", help="Site root, e.g. https://www.chi.gov.sa")
    ap.add_argument("folders", nargs="+",
                    help="Server-relative folder paths, e.g. /Rules/Documents")
    ap.add_argument("-o", "--outdir", default="sp_docs")
    ap.add_argument("--ext", nargs="+", default=["pdf"],
                    help="Extensions to keep; use --ext '' for everything")
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--no-recurse", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    exts = {e.lstrip(".").lower() for e in args.ext if e}
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    all_items, seen = [], set()
    for folder in args.folders:
        for it in list_files(session, args.site, folder, exts, not args.no_recurse):
            if it["url"] not in seen:
                seen.add(it["url"])
                all_items.append(it)

    print(f"\n{'=' * 60}\n{len(all_items)} unique file(s)\n{'=' * 60}")
    if not all_items:
        print("Nothing found. The REST API may be disabled -- see notes at the "
              "bottom of this file for the Playwright pagination fallback.")
        return
    if args.dry_run:
        for it in all_items:
            kb = int(it["size"]) / 1024 if str(it["size"]).isdigit() else 0
            print(f"  {safe_filename(it['name'])}  ({kb:.0f} KB)")
        return

    rows = []
    for it in all_items:
        path, status = download(session, it, outdir, args.delay)
        rows.append({
            "filename": safe_filename(it["name"]),
            "url": it["url"],
            "library_folder": it["folder"],
            "sp_modified": it["modified"],
            "status": status,
            "bytes": path.stat().st_size if path and path.exists() else "",
            "sha256": sha256(path) if path and path.exists() else "",
            "retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    manifest = outdir / "manifest.csv"
    with open(manifest, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    ok = sum(1 for r in rows if r["status"] == "downloaded")
    print(f"\nDone. {ok} downloaded, {len(rows) - ok} skipped/failed.")
    print(f"Manifest: {manifest}")
    print("Note: sp_modified is SharePoint's own last-modified timestamp -- "
          "useful as a version signal for guideline re-ingestion.")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# FALLBACK: if the REST API is blocked (403 / 404 on every call), drive the
# paginated list view with a real browser instead.
#
#   pip install playwright && playwright install chromium
#
#   from playwright.sync_api import sync_playwright
#
#   links = set()
#   with sync_playwright() as p:
#       page = p.chromium.launch(headless=False).new_page()
#       page.goto(LIST_VIEW_URL, wait_until="networkidle")
#       while True:
#           for a in page.query_selector_all("a[href$='.pdf'], a[href$='.xlsx']"):
#               links.add(a.get_attribute("href"))
#           nxt = page.query_selector("a[title='Next'], a.ms-commandLink[id$='next'], "
#                                     "img[alt='Next']")
#           if not nxt:
#               break
#           nxt.click()
#           page.wait_for_load_state("networkidle")
#   # then feed `links` into the download() function above
#
# Run headless=False the first time so you can watch which control actually
# advances the page -- SharePoint's "next" element varies by version and theme.
#
# Also try appending to the list view URL, which often defeats paging outright:
#     ?RootFolder=/Rules/Documents&View={...}&PageFirstRow=1&RowLimit=0
# ---------------------------------------------------------------------------
