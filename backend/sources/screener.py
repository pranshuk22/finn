"""Screener.in: standardised financial tables, company blurb, transcript and annual report links."""

import re
import time
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

from backend.config import USER_AGENT

BASE = "https://www.screener.in"
STATEMENTS = ["quarters", "profit-loss", "balance-sheet", "cash-flow", "ratios"]


class NotFound(Exception):
    pass


def fetch(ticker: str, client: httpx.Client | None = None) -> dict:
    """Parsed company page. Consolidated first; standalone if consolidated has no numbers or stopped earlier.

    JYOTHYLAB's consolidated quarters end at Mar 2025 while its standalone ones run to Jun 2026, because it
    stopped filing consolidated results. Consolidated alone left its trajectory and margins 15 months stale.
    """
    own = client is None
    client = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)
    try:
        found = None
        for mode in ("consolidated", "standalone"):
            path = f"/company/{ticker}/consolidated/" if mode == "consolidated" else f"/company/{ticker}/"
            r = client.get(BASE + path)
            if r.status_code == 404:
                raise NotFound(ticker)
            r.raise_for_status()
            page = parse(r.text)
            page["statement_mode"], page["url"] = mode, BASE + path
            if page["tables"].get("quarters"):
                if found is None or _last_quarter(page) > _last_quarter(found):
                    found = page
                if mode == "consolidated" and (date.today() - _last_quarter(page)).days <= 200:
                    return page  # current, so standalone is not needed
            time.sleep(1)
        return found or page
    finally:
        if own:
            client.close()


def _last_quarter(page: dict) -> date:
    ends = [datetime.strptime(q["period"], "%b %Y").date() for q in page["tables"]["quarters"] if q.get("period")]
    return max(ends, default=date.min)


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
            for period, td in zip(headers, tds[1:], strict=False):
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

    ratios = {}
    for li in soup.select("#top-ratios li"):
        name = li.select_one(".name")
        nums = [_num(n.get_text(strip=True)) for n in li.select(".number")]
        if name and nums:
            ratios[_clean_label(name.get_text(" ", strip=True))] = nums[0] if len(nums) == 1 else nums

    return {
        "name": name_el.get_text(strip=True) if name_el else None,
        "ratios": ratios,
        "about": about_el.get_text(" ", strip=True) if about_el else None,
        "tables": tables,
        "transcripts": transcripts,
        "annual_reports": annual_reports,
    }
