"""Every number FINN shows is computed here, in Python. Models never do arithmetic."""

import json
import sqlite3
from datetime import date

from backend.config import FINANCIALS


def pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return round(100 * (a - b) / abs(b), 1)


def cagr(end: float | None, start: float | None, years: int) -> float | None:
    if not end or not start or start <= 0 or end <= 0 or years <= 0:
        return None
    return round(100 * ((end / start) ** (1 / years) - 1), 1)


# ---------- results ----------


def _quarter_back(d: date, n: int) -> str:
    m = d.month - 3 * n
    y = d.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    last = {3: 31, 6: 30, 9: 30, 12: 31}[m]
    return date(y, m, last).isoformat()


def _screener_quarter(c: sqlite3.Connection, ticker: str, period_end: str, items: list[str]) -> float | None:
    per = date.fromisoformat(period_end).strftime("%b %Y")
    for it in items:
        r = c.execute(
            "SELECT value FROM financials WHERE ticker=? AND statement='quarters' AND period=? AND line_item=?",
            (ticker, per, it),
        ).fetchone()
        if r and r["value"] is not None:
            return r["value"]
    return None


def results_card(c: sqlite3.Connection, ticker: str, period_end: str | None = None) -> dict | None:
    """Headline numbers for one quarter with QoQ and YoY, from the exchange iXBRL filings."""
    q = (
        "SELECT * FROM results WHERE ticker=? "
        + ("AND period_end=? " if period_end else "")
        + "ORDER BY period_end DESC LIMIT 1"
    )
    cur = c.execute(q, (ticker, period_end) if period_end else (ticker,)).fetchone()
    if not cur:
        return None
    d = date.fromisoformat(cur["period_end"])
    prev = c.execute("SELECT * FROM results WHERE ticker=? AND period_end=?", (ticker, _quarter_back(d, 1))).fetchone()
    yago = c.execute("SELECT * FROM results WHERE ticker=? AND period_end=?", (ticker, _quarter_back(d, 4))).fetchone()
    is_bank = bool(cur["is_bank"]) or ticker in FINANCIALS

    def ebitda(r):
        if r is None or None in (r["pbt"], r["finance_costs"], r["depreciation"], r["other_income"]):
            return None
        return round(r["pbt"] + r["finance_costs"] + r["depreciation"] - r["other_income"], 2)

    if is_bank:
        lines = [
            ("Revenue", "revenue"),
            ("Pre-provision profit", "ppop"),
            ("Provisions", "provisions"),
            ("PBT", "pbt"),
            ("PAT", "pat"),
        ]
    else:
        lines = [("Revenue", "revenue"), ("EBITDA", None), ("PBT", "pbt"), ("PAT", "pat")]

    screener_items = {"revenue": ["Sales", "Revenue"], "pbt": ["Profit before tax"], "pat": ["Net Profit"]}
    rows = []
    for label, key in lines:
        get = (lambda r: ebitda(r)) if key is None else (lambda r, k=key: r[k] if r is not None else None)
        now, q1, y1 = get(cur), get(prev), get(yago)
        if now is None and key in ("ppop", "provisions"):
            continue
        check = None
        if key in screener_items:
            s = _screener_quarter(c, ticker, cur["period_end"], screener_items[key])
            diff = pct(now, s)
            if diff is not None and abs(diff) > 1:
                check = {"screener": s, "diff_pct": diff}
        rows.append(
            {
                "label": label,
                "value": now,
                "prev": q1,
                "year_ago": y1,
                "qoq": pct(now, q1),
                "yoy": pct(now, y1),
                "derived": key is None,
                "check": check,
            }
        )
    margin = None
    if not is_bank and rows[0]["value"] and rows[1]["value"] is not None:
        margin = round(100 * rows[1]["value"] / rows[0]["value"], 1)
    return {
        "ticker": ticker,
        "period_end": cur["period_end"],
        "quarter": quarter_label(cur["period_end"]),
        "consolidated": bool(cur["consolidated"]),
        "is_bank": is_bank,
        "unit": "Rs crore",
        "rows": rows,
        "ebitda_margin": margin,
        "source_url": cur["source_url"],
        "broadcast_at": cur["broadcast_at"],
        "has_prev": prev is not None,
        "has_year_ago": yago is not None,
    }


def quarter_label(period_end: str) -> str:
    """2026-09-30 -> Q2 FY27 (Indian financial year starts in April)."""
    d = date.fromisoformat(period_end)
    q = {6: 1, 9: 2, 12: 3, 3: 4}[d.month]
    fy = d.year + 1 if d.month > 3 else d.year
    return f"Q{q} FY{fy % 100:02d}"


def results_headline(card: dict) -> str:
    """One line like 'Revenue +6.2% YoY, PAT -3.1% YoY'. Plain arithmetic, no adjectives."""
    parts = []
    for r in card["rows"]:
        if r["label"] in ("Revenue", "PAT") and r["yoy"] is not None:
            parts.append(f"{r['label']} {r['yoy']:+.1f}% YoY")
    if not parts:
        for r in card["rows"]:
            if r["label"] in ("Revenue", "PAT") and r["qoq"] is not None:
                parts.append(f"{r['label']} {r['qoq']:+.1f}% QoQ")
    return ", ".join(parts) or f"{card['quarter']} results filed"


# ---------- EOD alerts ----------


def eod_scan(
    c: sqlite3.Connection, tickers: list[str], price_pct: float, vol_mult: float, days: int, lookback: int = 20
) -> list[dict]:
    """Days in the last `days` trading sessions where a ticker crossed either threshold.

    Volume multiple = that day's volume / mean of the previous `lookback` sessions.
    """
    hits = []
    for t in tickers:
        rows = c.execute("SELECT date, close, volume FROM eod WHERE ticker=? ORDER BY date", (t,)).fetchall()
        start = max(lookback + 1, len(rows) - days)
        for i in range(start, len(rows)):
            prev_close = rows[i - 1]["close"]
            move = 100 * (rows[i]["close"] / prev_close - 1) if prev_close else None
            window = [r["volume"] for r in rows[i - lookback : i]]
            avg = sum(window) / len(window) if window else None
            mult = rows[i]["volume"] / avg if avg else None
            reasons = []
            if move is not None and abs(move) >= price_pct:
                reasons.append("price")
            if mult is not None and mult >= vol_mult:
                reasons.append("volume")
            if reasons:
                hits.append(
                    {
                        "ticker": t,
                        "date": rows[i]["date"],
                        "close": round(rows[i]["close"], 2),
                        "move_pct": round(move, 2) if move is not None else None,
                        "vol_mult": round(mult, 2) if mult is not None else None,
                        "reasons": reasons,
                    }
                )
    hits.sort(key=lambda h: (h["date"], abs(h["move_pct"] or 0)), reverse=True)
    return hits


def sparkline(c: sqlite3.Connection, ticker: str, n: int = 30) -> list[float]:
    rows = c.execute("SELECT close FROM eod WHERE ticker=? ORDER BY date DESC LIMIT ?", (ticker, n)).fetchall()
    return [round(r["close"], 2) for r in reversed(rows)]


# ---------- research sections from Screener tables ----------


def _series(c: sqlite3.Connection, ticker: str, statement: str, items: list[str]) -> tuple[str | None, list[dict]]:
    for it in items:
        rows = c.execute(
            "SELECT period, value FROM financials WHERE ticker=? AND statement=? AND line_item=?",
            (ticker, statement, it),
        ).fetchall()
        if rows:
            return it, _order([{"period": r["period"], "value": r["value"]} for r in rows])
    return None, []


def _order(rows: list[dict]) -> list[dict]:
    def key(r):
        p = r["period"]
        if p == "TTM":
            return (9999, 99)
        try:
            mon, yr = p.split()
            return (
                int(yr),
                ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"].index(mon),
            )
        except ValueError:
            return (0, 0)

    return sorted(rows, key=key)


def _annual(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["period"] != "TTM" and r["value"] is not None]


def snapshot(c: sqlite3.Connection, ticker: str) -> dict | None:
    co = c.execute("SELECT * FROM companies WHERE ticker=?", (ticker,)).fetchone()
    if not co:
        return None
    is_fin = ticker in FINANCIALS or bool(_series(c, ticker, "profit-loss", ["Financing Profit"])[1])
    _, sales = _series(c, ticker, "profit-loss", ["Sales", "Revenue"])
    _, np_ = _series(c, ticker, "profit-loss", ["Net Profit"])
    _, opm = _series(c, ticker, "profit-loss", ["OPM %", "Financing Margin %"])
    ttm = lambda s: next((r["value"] for r in s if r["period"] == "TTM"), None)  # noqa: E731
    ratios = json.loads(co["ratios"] or "{}")
    return {
        "ticker": ticker,
        "name": co["name"],
        "about": co["about"],
        "statement_mode": co["statement_mode"],
        "is_financial": is_fin,
        "ratios": ratios,
        "ttm": {
            "revenue": ttm(sales),
            "net_profit": ttm(np_),
            "margin_label": "Financing margin" if is_fin else "Operating margin",
            "margin_pct": _annual(opm)[-1]["value"] if _annual(opm) else None,
        },
        "source": "Screener standardised financials",
    }


def trajectory(c: sqlite3.Connection, ticker: str) -> dict:
    out = {"annual": {}, "quarterly": {}, "growth": {}}
    for label, items in [
        ("Revenue", ["Sales", "Revenue"]),
        ("Operating profit", ["Operating Profit", "Financing Profit"]),
        ("Margin %", ["OPM %", "Financing Margin %"]),
        ("Net profit", ["Net Profit"]),
    ]:
        _, s = _series(c, ticker, "profit-loss", items)
        a = _annual(s)[-6:]
        out["annual"][label] = a
        if label != "Margin %" and len(a) >= 2:
            out["growth"][label] = {
                "cagr_3y": cagr(a[-1]["value"], a[-4]["value"], 3) if len(a) >= 4 else None,
                "cagr_5y": cagr(a[-1]["value"], a[-6]["value"], 5) if len(a) >= 6 else None,
                "last_year": pct(a[-1]["value"], a[-2]["value"]),
            }
        _, qs = _series(c, ticker, "quarters", items)
        out["quarterly"][label] = [r for r in qs if r["value"] is not None][-8:]
    if out["annual"].get("Margin %"):
        m = out["annual"]["Margin %"]
        out["growth"]["Margin %"] = {"change_pts_5y": round(m[-1]["value"] - m[0]["value"], 1) if len(m) >= 2 else None}
    return out


def cash_quality(c: sqlite3.Connection, ticker: str) -> dict:
    _, cfo = _series(c, ticker, "cash-flow", ["Cash from Operating Activity"])
    _, fcf = _series(c, ticker, "cash-flow", ["Free Cash Flow"])
    _, op = _series(c, ticker, "profit-loss", ["Operating Profit"])
    _, npf = _series(c, ticker, "profit-loss", ["Net Profit"])
    cfo, fcf, op, npf = _annual(cfo), _annual(fcf), _annual(op), _annual(npf)
    by = lambda s: {r["period"]: r["value"] for r in s}  # noqa: E731
    cfo_m, op_m, np_m = by(cfo), by(op), by(npf)

    years = [r["period"] for r in cfo][-5:]
    rows = []
    for y in years:
        rows.append(
            {
                "period": y,
                "cfo": cfo_m.get(y),
                "fcf": by(fcf).get(y),
                "cfo_to_ebitda": round(100 * cfo_m[y] / op_m[y], 0) if op_m.get(y) else None,
                "cfo_to_pat": round(100 * cfo_m[y] / np_m[y], 0) if np_m.get(y) else None,
            }
        )
    last3 = years[-3:]
    cum = None
    if last3 and all(op_m.get(y) for y in last3):
        cum = round(100 * sum(cfo_m[y] for y in last3) / sum(op_m[y] for y in last3), 0)

    wc = {}
    for item in [
        "Debtor Days",
        "Inventory Days",
        "Days Payable",
        "Cash Conversion Cycle",
        "Working Capital Days",
        "ROCE %",
        "ROE %",
    ]:
        _, s = _series(c, ticker, "ratios", [item])
        s = _annual(s)[-5:]
        if s:
            wc[item] = s

    _, debt = _series(c, ticker, "balance-sheet", ["Borrowings", "Borrowing"])
    _, eq = _series(c, ticker, "balance-sheet", ["Equity Capital"])
    _, res = _series(c, ticker, "balance-sheet", ["Reserves"])
    debt, eq_m, res_m = _annual(debt), by(_annual(eq)), by(_annual(res))
    de = []
    for r in debt[-5:]:
        e = (eq_m.get(r["period"]) or 0) + (res_m.get(r["period"]) or 0)
        de.append(
            {
                "period": r["period"],
                "debt": r["value"],
                "equity": e,
                "debt_to_equity": round(r["value"] / e, 2) if e else None,
            }
        )
    return {
        "years": rows,
        "cfo_to_ebitda_3y": cum,
        "working_capital": wc,
        "leverage": de,
        "is_financial": ticker in FINANCIALS,
    }


def scale(c: sqlite3.Connection, ticker: str, amount_cr: float) -> dict:
    """An amount from a filing as a share of annual revenue, so 'Rs 500 crore' means something."""
    _, sales = _series(c, ticker, "profit-loss", ["Sales", "Revenue"])
    ttm = next((r["value"] for r in sales if r["period"] == "TTM"), None)
    if ttm is None and _annual(sales):
        ttm = _annual(sales)[-1]["value"]
    return {
        "amount_cr": amount_cr,
        "annual_revenue_cr": ttm,
        "pct_of_revenue": round(100 * amount_cr / ttm, 2) if ttm else None,
    }
