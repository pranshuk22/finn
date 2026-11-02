"""NSE: corporate announcements and integrated-filing results (iXBRL).

NSE's API needs the cookies set by its homepage, even though the homepage itself
answers 403 to scripts (EVIDENCE E1).
"""

import csv
import io
import re
import time
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

from backend.config import USER_AGENT

BASE = "https://www.nseindia.com"
PAUSE_S = 0.8  # 18 sequential calls at this pace had zero failures (EVIDENCE E2)


class NSE:
    def __init__(self) -> None:
        self.client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html"},
            timeout=30,
            follow_redirects=True,
        )
        self._warm()

    def _warm(self) -> None:
        self.client.get(BASE + "/")

    def _get_json(self, path: str, params: dict):
        for attempt in range(3):
            r = self.client.get(BASE + path, params=params)
            if r.status_code == 200:
                try:
                    return r.json()
                except ValueError:
                    pass
            time.sleep(2 * (attempt + 1))
            self._warm()
        r.raise_for_status()
        raise RuntimeError(f"NSE returned non-JSON for {path} {params}")

    def announcements(self, symbol: str, start: date, end: date) -> list[dict]:
        data = self._get_json(
            "/api/corporate-announcements",
            {
                "index": "equities",
                "symbol": symbol,
                "from_date": start.strftime("%d-%m-%Y"),
                "to_date": end.strftime("%d-%m-%Y"),
            },
        )
        time.sleep(PAUSE_S)
        return [_clean_announcement(a) for a in data]

    def integrated_financials(self, symbol: str) -> list[dict]:
        """Rows for quarterly results filed under SEBI's integrated filing format.

        The older corporates-financial-results endpoint stops at Dec 2024 (EVIDENCE E6).
        """
        data = self._get_json(
            "/api/integrated-filing-results",
            {"index": "equities", "symbol": symbol, "type": "Integrated Filing- Financials"},
        )
        time.sleep(PAUSE_S)
        return data.get("data", []) if isinstance(data, dict) else []

    def equity_list(self) -> list[dict]:
        """Every equity listed on NSE with its company name, from NSE's own published list (about 2,600 rows)."""
        r = self.client.get("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv")
        r.raise_for_status()
        rows = list(csv.DictReader(io.StringIO(r.text)))
        return [{"ticker": x["SYMBOL"].strip(), "name": x["NAME OF COMPANY"].strip()} for x in rows if x.get("SYMBOL")]

    def fetch_text(self, url: str) -> str:
        r = self.client.get(url)
        r.raise_for_status()
        return r.text


def _clean_announcement(a: dict) -> dict:
    dt = datetime.strptime(a["an_dt"], "%d-%b-%Y %H:%M:%S")
    return {
        "id": str(a["seq_id"]),
        "ticker": a["symbol"],
        "an_dt": dt.isoformat(),
        "nse_label": (a.get("desc") or "").strip(),
        # NSE escapes apostrophes as '' in this field
        "text": (a.get("attchmntText") or "").replace("''", "'").strip(),
        "pdf_url": a.get("attchmntFile") or None,
    }


# ---------- results from iXBRL ----------

_UNIT_TO_CRORE = {
    "actual": 1e-7,
    "actuals": 1e-7,
    "rupees": 1e-7,
    "thousands": 1e-4,
    "lakhs": 1e-2,
    "lakh": 1e-2,
    "millions": 1e-1,
    "million": 1e-1,
    "crores": 1.0,
    "crore": 1.0,
}

# Row labels in the P&L table of the integrated filing. First match wins.
# "Profit before tax" also appears in the segment table, so we only read the P&L table.
# Three layouts seen live: companies (TCS, RELIANCE), NBFCs (BAJFINANCE), banks (HDFCBANK).
_ROWS = {
    "revenue": ["total revenue from operations", "revenue from operations", "total interest earned"],
    "total_income": ["total income"],
    "other_income": ["other income"],
    "finance_costs": ["finance costs", "interest expended"],
    "depreciation": ["depreciation, depletion and amortisation expense", "depreciation and amortisation expense"],
    "ppop": ["operating profit before provision and contingencies"],
    "provisions": ["provisions other than tax and contingencies"],
    "pbt": ["total profit before tax", "total profit (loss) from ordinary activities before tax"],
    "pat": ["total profit (loss) for period", "net profit (loss) for the period"],
}


def _num(s: str) -> float | None:
    s = s.strip()
    if not s or not re.search(r"\d", s):
        return None
    neg = s.startswith("(") and s.endswith(")")
    v = float(re.sub(r"[^\d.]", "", s))
    return -v if neg else v


def _date(s: str) -> str | None:
    for fmt in ("%d-%m-%Y", "%d-%b-%Y"):  # newer filings use 30-09-2026, older ones 30-Jun-2025
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _factor(tables) -> tuple[float, str]:
    """Multiplier from the filing's own unit to Rs crore, and the unit as written."""
    unit = None
    currency_note = None
    for t in tables:
        for tr in t.find_all("tr"):
            cells = [_norm(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
            if len(cells) >= 2 and cells[0].startswith("level of rounding"):
                unit = cells[1]
            elif len(cells) >= 2 and cells[0].startswith("description of presentation currency"):
                currency_note = cells[1]
        if unit:
            break
    if unit is None and currency_note:
        # Older filings (seen for TITAN and HAL, Jun 2025) say "INR (in Actuals)" instead of a rounding row.
        m = re.search(r"\(in (\w+)\)", currency_note)
        unit = m.group(1) if m else None
    if unit not in _UNIT_TO_CRORE:
        raise ValueError(f"unknown rounding unit: {unit!r}")
    return _UNIT_TO_CRORE[unit], unit


def parse_results_ixbrl(html: str) -> dict:
    """Headline P&L numbers for the current quarter, converted to Rs crore.

    Verified on TCS Sep 2026: revenue 73,188, PBT 18,638, PAT 13,934 crore,
    all equal to Screener's quarterly table (EVIDENCE E6).
    """
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    factor, unit = _factor(tables)

    pl = None
    for t in tables:
        text = _norm(t.get_text(" "))
        has_cost = "total expenses" in text or "total expenditure" in text
        if has_cost and ("revenue from operations" in text or "interest earned" in text):
            pl = t
            break
    if pl is None:
        raise ValueError("P&L table not found")

    out: dict = {"unit_in_filing": unit, "is_bank": "interest earned" in _norm(pl.get_text(" "))}
    period_end = period_start = None
    for tr in pl.find_all("tr"):
        cells = [_norm(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        # rows look like [index, label, current quarter, year to date]
        labelled = [(i, c) for i, c in enumerate(cells) if re.search(r"[a-z]{3}", c)]
        if not labelled:
            continue
        i, label = labelled[0]
        values = cells[i + 1 :]
        if not values:
            continue
        if label.startswith("date of end of reporting period"):
            period_end = _date(values[0])
            continue
        if label.startswith("date of start of reporting period"):
            period_start = _date(values[0])
            continue
        for key, names in _ROWS.items():
            if key in out:
                continue
            if label in names:
                v = _num(values[0])
                if v is not None:
                    out[key] = round(v * factor, 2)
    out["period_end"] = period_end
    # Months covered by the first column. Normally 3, but some filings (COFORGE Q2 FY27) carry only six-month
    # figures in both columns; the caller then derives the quarter from earlier quarters.
    out["months"] = _months(period_start, period_end)
    out["segments"] = _segments(soup, tables, factor)
    return out


# Rows of a bank's standalone results filing. The consolidated filing leaves the NPA ratios at 0 (HDFCBANK and
# ICICIBANK, Sep 2026), since asset quality is reported for the bank itself.
_BANK_ROWS = {
    "interest_earned": ["total interest earned"],
    "interest_expended": ["interest expenses", "interest expended"],
    "provisions": ["provisions other than tax and contingencies"],
    "gross_npa": ["amount of gross non-performing assets", "gross npa"],
    "gnpa_pct": ["% of gross npas", "% of gross npa"],
    "nnpa_pct": ["% of net npas", "% of net npa"],
    "cet1_pct": ["cet 1 ratio"],
    "advances": ["advances"],
    "total_assets": ["total assets"],
}
_BANK_PCT = {"gnpa_pct", "nnpa_pct", "cet1_pct"}


def parse_bank_kpis(html: str) -> dict:
    """Asset quality and interest income for the quarter, from a bank's standalone integrated filing.

    Checked on HDFCBANK Sep 2026: gross NPA 1.11%, net NPA 0.37%, CET1 18.87%, interest earned 83,426.60 crore and
    interest expended 48,807.42 crore. Ratios are kept as filed; amounts are converted to Rs crore. The balance
    sheet (advances, total assets) is only in the half-year filings.
    """
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    factor, _ = _factor(tables)
    out: dict = {}
    for tr in soup.find_all("tr"):
        cells = [_norm(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        labelled = [(i, c) for i, c in enumerate(cells) if re.search(r"[a-z]{3}", c)]
        if not labelled:
            continue
        i, label = labelled[0]
        values = cells[i + 1 :]
        if label.startswith("date of end of reporting period") and "period_end" not in out and values:
            out["period_end"] = _date(values[0])
            continue
        for key, names in _BANK_ROWS.items():
            if key in out or label not in names or not values:
                continue
            v = _num(values[0])
            if v is not None:
                out[key] = v if key in _BANK_PCT else round(v * factor, 2)
    # a 0 ratio is the consolidated filing's placeholder, not a bank with no bad loans
    for k in _BANK_PCT:
        if out.get(k) == 0:
            out.pop(k)
    return out


def _months(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return (b.year - a.year) * 12 + b.month - a.month + 1


def _segments(soup, tables, factor: float) -> dict | None:
    """The segment table of the same filing: revenue and profit before interest and tax per segment, this quarter.

    Single-segment companies say so in the filing's general table ("Segment Reporting: Single segment") and
    leave the segment table empty. Checked on Sep 2026 filings: for LT, segment revenue less inter-segment revenue
    equals revenue from operations in the P&L (78,749.94 crore). RELIANCE's segment table totals 3,62,268 crore
    against 3,32,861 in its P&L, so a segment's share is always taken of segment revenue, never of headline revenue.
    """
    general = {}
    for t in tables[:3]:
        for tr in t.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) >= 2:
                general[_norm(cells[0])] = cells[1]
    if _norm(general.get("segment reporting", "")) == "single segment":
        return {"single": general.get("description of single segment") or None, "items": []}

    table = next(
        (
            t
            for t in tables
            if "segment revenue" in _norm(t.get_text(" ")) and "segment result" in _norm(t.get_text(" "))
        ),
        None,
    )
    if table is None:
        return None
    part, revenue, result = None, {}, {}
    for tr in table.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        head = _norm(cells[1])
        if head.startswith("segment revenue"):
            part = revenue
        elif head.startswith("segment result"):
            part = result
        elif head.startswith("(segment asset") or head.startswith("segment asset"):
            break
        # segment rows are numbered; totals, "Add:" and "Less:" adjustments are not segments
        elif (
            part is not None
            and cells[0].strip().isdigit()
            and len(cells) >= 3
            and not re.match(r"(add|less)\s*:", head)
        ):
            v = _num(cells[2])
            if v is not None:
                # the app and repo never show en or em dashes (filings use them in names like "Energy \u2013 Green")
                part[re.sub(r"\s*[\u2013\u2014]\s*", " - ", cells[1].strip())] = round(v * factor, 2)
    if not revenue:
        return None
    return {"single": None, "items": [{"name": n, "revenue": v, "result": result.get(n)} for n, v in revenue.items()]}
