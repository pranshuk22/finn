"""Screener.in: standardised financial tables, company blurb, transcript and annual report links."""

import re
import time

import httpx
from bs4 import BeautifulSoup

from backend.config import USER_AGENT

BASE = "https://www.screener.in"
STATEMENTS = ["quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios"]


class NotFound(Exception):
    pass


def fetch(ticker: str, client: httpx.Client | None = None) -> dict:
    """Parsed company page. Consolidated first, standalone if consolidated has no numbers."""
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)
    try:
        for mode in ("consolidated", "standalone"):
            path = f"/company/{ticker}/consolidated/" if mode == "consolidated" else f"/company/{ticker}/"
            r = client.get(BASE + path)
            if r.status_code == 404:
                raise NotFound(ticker)
            r.raise_for_status()
            page = parse(r.text)
            if page["tables"].get("quarters"):
                page["statement_mode"] = mode
                page["url"] = BASE + path
                return page
            time.sleep(1)
        page["statement_mode"] = "standalone"
        page["url"] = BASE + path
        return page
    finally:
        if own:
            client.close()


def _num(s: str) -> float | None:
    s = s.replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _clean_label(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ").replace("+", "")).strip()


def parse(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    name_el = soup.select_one("h1")
    about_el = soup.select_one(".company-profile .about")

    tables: dict[str, list[dict]] = {}
    for sid in STATEMENTS:
        sec = soup.find("section", id=sid)
        table = sec.find("table", class_="data-table") if sec else None
        if not table:
            continue
        headers = [_clean_label(th.get_text(" ", strip=True)) for th in table.select("thead th")][1:]
        rows = []
        for tr in table.select("tbody tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            label = _clean_label(tds[0].get_text(" ", strip=True))
            for period, td in zip(headers, tds[1:]):
                rows.append({"period": period, "line_item": label, "value": _num(td.get_text(strip=True))})
        tables[sid] = rows

    transcripts = []
    for li in soup.select("#documents .concalls li, .documents .concalls li"):
        date_el = li.find("div", class_="ink-600") or li.find("div")
        period = _clean_label(date_el.get_text(" ", strip=True)) if date_el else ""
        for a in li.find_all("a"):
            if a.get_text(strip=True) == "Transcript" and a.get("href"):
                transcripts.append({"period": period, "url": a["href"]})

    annual_reports = []
    for a in soup.select("#documents .annual-reports a, .documents .annual-reports a"):
        m = re.search(r"(\d{4})", a.get_text(" ", strip=True))
        if m and a.get("href"):
            annual_reports.append({"period": m.group(1), "url": a["href"]})

    return {
        "name": name_el.get_text(strip=True) if name_el else None,
        "about": about_el.get_text(" ", strip=True) if about_el else None,
        "tables": tables,
        "transcripts": transcripts,
        "annual_reports": annual_reports,
    }
