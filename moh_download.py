#!/usr/bin/env python3
"""
Download every PDF listed in a  name<TAB>url  TSV into one folder, with a
provenance manifest (URL, size, SHA-256, retrieval time).

Built for links.tsv (MOH KSA clinical protocols) so they can be added to the
CDI KB reference list alongside CHI_Guidelines/.

Usage:
    python moh_download.py links.tsv -o MOH_Protocols [--delay 1.0] [--dry-run]

Notes:
    - Files are named from column 1 of the TSV (human-readable), not from the
      URL basename (Protocol-002.pdf ...). The URL basename is kept in the
      manifest so provenance is never lost.
    - Skips files already present and valid, so it is safe to re-run / resume.
    - Verifies the response is a real PDF (magic bytes). Government portals
      sometimes return an HTML "not found" page with HTTP 200; those are
      recorded as errors, not saved as .pdf.
    - Single-threaded with a delay and 3 retries: public documents on a
      government portal — be polite.
"""

import argparse
import csv
import hashlib
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*;q=0.8",
    "Accept-Language": "en,ar;q=0.8",
}
CHUNK = 1 << 16
RETRIES = 3


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\|?*\x00-\x1f]', "_", name).strip(" .")
    return (name or "document")[:180]


def read_tsv(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.rstrip("\r\n").split("\t")
        if len(parts) != 2 or not parts[1].startswith(("http://", "https://")):
            print(f"  ! line {lineno}: expected 'name<TAB>url', got: {line[:80]!r}", file=sys.stderr)
            continue
        rows.append((parts[0].strip(), parts[1].strip()))
    return rows


def is_pdf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def download(session: requests.Session, url: str, dest: Path, delay: float, timeout: int = 180) -> str:
    if dest.exists() and dest.stat().st_size > 0 and is_pdf(dest):
        print(f"  = skip (exists): {dest.name}")
        return "skipped"

    tmp = dest.with_suffix(dest.suffix + ".part")
    last_err = ""
    for attempt in range(1, RETRIES + 1):
        try:
            with session.get(url, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(CHUNK):
                        if chunk:
                            f.write(chunk)
            if not is_pdf(tmp):
                ctype = r.headers.get("Content-Type", "?")
                tmp.unlink(missing_ok=True)
                last_err = f"error: not a PDF (Content-Type={ctype})"
                break  # a wrong document type will not fix itself on retry
            tmp.replace(dest)
            print(f"  + {dest.name} ({dest.stat().st_size / 1024:.0f} KB)")
            time.sleep(delay)
            return "downloaded"
        except requests.RequestException as e:
            last_err = f"error: {e}"
            tmp.unlink(missing_ok=True)
            if attempt < RETRIES:
                time.sleep(delay * 2 * attempt)
    print(f"  ! {dest.name}: {last_err}", file=sys.stderr)
    return last_err


def main() -> int:
    ap = argparse.ArgumentParser(description="Download PDFs listed in a name<TAB>url TSV.")
    ap.add_argument("tsv", type=Path, help="TSV with two columns: name, url")
    ap.add_argument("-o", "--outdir", default="MOH_Protocols", help="Output directory.")
    ap.add_argument("--delay", type=float, default=1.0, help="Seconds between requests.")
    ap.add_argument("--dry-run", action="store_true", help="List, don't download.")
    args = ap.parse_args()

    rows = read_tsv(args.tsv)
    print(f"{len(rows)} link(s) in {args.tsv}")
    if args.dry_run:
        for name, url in rows:
            print(f"  {safe_filename(name)}.pdf  <- {url}")
        return 0

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)

    manifest_rows = []
    for name, url in rows:
        dest = outdir / f"{safe_filename(name)}.pdf"
        status = download(session, url, dest, args.delay)
        ok = dest.exists() and status in ("downloaded", "skipped")
        manifest_rows.append({
            "filename": dest.name,
            "name": name,
            "url": url,
            "url_basename": unquote(Path(urlparse(url).path).name),
            "status": status,
            "bytes": dest.stat().st_size if ok else "",
            "sha256": sha256(dest) if ok else "",
            "retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })

    manifest = outdir / "manifest.csv"
    with open(manifest, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
        w.writeheader()
        w.writerows(manifest_rows)

    n_dl = sum(r["status"] == "downloaded" for r in manifest_rows)
    n_skip = sum(r["status"] == "skipped" for r in manifest_rows)
    failed = [r for r in manifest_rows if r["status"].startswith("error")]
    print(f"\nDone. {n_dl} downloaded, {n_skip} already present, {len(failed)} failed.")
    for r in failed:
        print(f"  FAILED {r['filename']}: {r['status']}  <- {r['url']}")
    print(f"Manifest: {manifest}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
