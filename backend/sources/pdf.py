"""Download PDFs (transcripts, annual reports, filings) and extract text page by page."""

import hashlib

import httpx
import pymupdf

from backend.config import CACHE_DIR, USER_AGENT


def _referer(url: str) -> str | None:
    # BSE serves transcript PDFs only with a BSE referer (EVIDENCE E8)
    if "bseindia.com" in url:
        return "https://www.bseindia.com/"
    if "nseindia.com" in url:
        return "https://www.nseindia.com/"
    return None


def download(url: str, client: httpx.Client | None = None) -> bytes:
    path = CACHE_DIR / "pdf" / (hashlib.sha1(url.encode()).hexdigest() + ".pdf")
    if path.exists():
        return path.read_bytes()
    headers = {"User-Agent": USER_AGENT}
    if ref := _referer(url):
        headers["Referer"] = ref
    own = client is None
    client = client or httpx.Client(timeout=60, follow_redirects=True)
    try:
        r = client.get(url, headers=headers)
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            raise ValueError(f"not a PDF: {url} ({r.headers.get('content-type')})")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(r.content)
        return r.content
    finally:
        if own:
            client.close()


def pages(data: bytes, max_pages: int | None = None) -> list[str]:
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        n = len(doc) if max_pages is None else min(len(doc), max_pages)
        return [doc[i].get_text() for i in range(n)]
