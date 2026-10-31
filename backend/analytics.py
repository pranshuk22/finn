"""Every number FINN shows is computed here, in Python. Models never do arithmetic."""

import json
import sqlite3
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

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

    # Margin = profit / revenue (reference glossary). Changes in basis points, so 15.6% vs 17.0% reads as -140 bps.
    def share(num, den):
        return round(100 * num / den, 1) if num is not None and den else None

    by = {r["label"]: r for r in rows}
    margins = []
    for label, src in (("EBITDA margin", "EBITDA"), ("PAT margin", "PAT")):
        if src not in by or "Revenue" not in by:
            continue
        n, q1, y1 = (share(by[src][k], by["Revenue"][k]) for k in ("value", "prev", "year_ago"))
        margins.append(
            {
                "label": label,
                "now": n,
                "prev": q1,
                "year_ago": y1,
                "qoq_bps": round(100 * (n - q1)) if n is not None and q1 is not None else None,
                "yoy_bps": round(100 * (n - y1)) if n is not None and y1 is not None else None,
            }
        )
    # Profit that leans on interest and investment income is lower quality than profit from operations.
    other_income_share = (
        round(100 * cur["other_income"] / cur["pbt"], 1)
        if not is_bank and cur["other_income"] is not None and cur["pbt"] and cur["pbt"] > 0
        else None
    )
    # Up to five quarters ending with this one, for the small trend under each figure on the card.
    hist_rows = c.execute(
        "SELECT * FROM results WHERE ticker=? AND period_end<=? ORDER BY period_end DESC LIMIT 5",
        (ticker, cur["period_end"]),
    ).fetchall()[::-1]
    history = [
        {
            "quarter": quarter_label(r["period_end"]),
            **{
                label: (ebitda(r) if key is None else r[key])
                for label, key in lines
                if not (key in ("ppop", "provisions") and r[key] is None)
            },
        }
        for r in hist_rows
    ]
    # A figure more than 10% away from Screener's for the same quarter is not headlined: one of the two is wrong
    # (COFORGE Q2 FY27 first showed six-month revenue as the quarter's, 89.6% above Screener).
    suspect = [r["label"] for r in rows if r["check"] and abs(r["check"]["diff_pct"]) > 10]
    return {
        "ticker": ticker,
        "period_end": cur["period_end"],
        "quarter": quarter_label(cur["period_end"]),
        "derived": cur["derived"] if "derived" in cur.keys() else None,
        "suspect": suspect,
        "tax_note": _tax_note(cur, yago),
        "history": history,
        "consolidated": bool(cur["consolidated"]),
        "is_bank": is_bank,
        "unit": "Rs crore",
        "rows": rows,
        "ebitda_margin": margin,
        "margins": margins,
        "other_income_pct_of_pbt": other_income_share,
        "source_url": cur["source_url"],
        "broadcast_at": cur["broadcast_at"],
        "has_prev": prev is not None,
        "has_year_ago": yago is not None,
    }


def _tax_note(cur, yago) -> str | None:
    """When tax, not the business, explains most of the PAT change. MAXHEALTH Q2 FY27: PAT -15.6% YoY while PBT
    rose 21.3%, because a year ago tax was a credit (PAT 110% of PBT). SUZLON: PAT -69.2%, PBT -7.9%."""
    if (
        yago is None
        or None in (cur["pbt"], cur["pat"], yago["pbt"], yago["pat"])
        or cur["pbt"] <= 0
        or yago["pbt"] <= 0
    ):
        return None
    pat_yoy, pbt_yoy = pct(cur["pat"], yago["pat"]), pct(cur["pbt"], yago["pbt"])
    tax_now, tax_then = round(100 * (1 - cur["pat"] / cur["pbt"])), round(100 * (1 - yago["pat"] / yago["pbt"]))
    if pat_yoy is None or pbt_yoy is None or abs(pat_yoy - pbt_yoy) <= 15 or abs(tax_now - tax_then) <= 10:
        return None
    then = (
        f"a year ago tax was a credit (PAT was {round(100 * yago['pat'] / yago['pbt'])}% of PBT)"
        if tax_then < 0
        else f"tax took {tax_then}% of PBT a year ago"
    )
    return f"PAT {pat_yoy:+.1f}% YoY, but PBT {pbt_yoy:+.1f}%: {then}, {tax_now}% now. PBT shows the trend better."


def quarter_label(period_end: str) -> str:
    """2026-09-30 -> Q2 FY27 (Indian financial year starts in April)."""
    d = date.fromisoformat(period_end)
    q = {6: 1, 9: 2, 12: 3, 3: 4}[d.month]
    fy = d.year + 1 if d.month > 3 else d.year
    return f"Q{q} FY{fy % 100:02d}"


def results_headline(card: dict) -> str:
    """One line like 'Revenue +6.2% YoY, PAT -3.1% YoY'. Plain arithmetic, no adjectives."""
    if card.get("suspect"):
        return f"{card['quarter']} results filed; {' and '.join(card['suspect'])} differ from Screener by over 10%"
    profit = "PBT" if card.get("tax_note") else "PAT"  # when tax explains the PAT change, lead with PBT
    parts = []
    for r in card["rows"]:
        if r["label"] in ("Revenue", profit) and r["yoy"] is not None:
            parts.append(f"{r['label']} {r['yoy']:+.1f}% YoY")
    if not parts:
        for r in card["rows"]:
            if r["label"] in ("Revenue", "PAT") and r["qoq"] is not None:
                parts.append(f"{r['label']} {r['qoq']:+.1f}% QoQ")
    return ", ".join(parts) or f"{card['quarter']} results filed"


# ---------- EOD alerts ----------


def portfolio_day(c: sqlite3.Connection, tickers: list[str]) -> dict | None:
    """How the portfolio moved on the latest session: breadth, median move, best and worst."""
    last = c.execute("SELECT MAX(date) FROM eod").fetchone()[0]
    if not last:
        return None
    moves = []
    for t in tickers:
        rows = c.execute(
            "SELECT date, close FROM eod WHERE ticker=? AND date <= ? ORDER BY date DESC LIMIT 2", (t, last)
        ).fetchall()
        if len(rows) == 2 and rows[0]["date"] == last and rows[1]["close"]:
            moves.append((t, round(100 * (rows[0]["close"] / rows[1]["close"] - 1), 2)))
    if not moves:
        return None
    ordered = sorted(m for _, m in moves)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    best = max(moves, key=lambda m: m[1])
    worst = min(moves, key=lambda m: m[1])
    return {
        "date": last,
        "count": len(moves),
        "of": len(tickers),  # a ticker without a close for that day is left out, not guessed (EVIDENCE E9)
        "up": sum(1 for _, m in moves if m > 0),
        "down": sum(1 for _, m in moves if m < 0),
        "median_pct": round(median, 2),
        "best": {"ticker": best[0], "move_pct": best[1]},
        "worst": {"ticker": worst[0], "move_pct": worst[1]},
        "stocks": [{"ticker": t, "move_pct": m} for t, m in sorted(moves, key=lambda m: -m[1])],
    }


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
                "operating_profit": op_m.get(y),
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


def segment_history(c: sqlite3.Connection, ticker: str) -> dict[str, list[dict]]:
    """Each segment's revenue and result by quarter, oldest first, as filed. Used to check segment-level promises."""
    out: dict[str, list[dict]] = {}
    for r in c.execute(
        "SELECT period_end, segments FROM results WHERE ticker=? AND segments IS NOT NULL ORDER BY period_end",
        (ticker,),
    ):
        for i in json.loads(r["segments"]).get("items") or []:
            if i["revenue"] or i["result"]:
                out.setdefault(i["name"], []).append(
                    {"quarter": quarter_label(r["period_end"]), "revenue": i["revenue"], "result": i["result"]}
                )
    return out


def balance_sheet(c: sqlite3.Connection, ticker: str) -> dict:
    """How the company is funded and whether it can carry its debt, by financial year (Screener's annual sheets).

    Interest coverage = (profit before tax + interest) / interest, i.e. operating profit available per rupee of
    interest. It needs a full year of P&L, so a half-year balance sheet column (e.g. "Sep 2026") has none. It is
    left out for lenders, whose interest is the cost of their product. Funding mix is each source's share of total
    liabilities; for banks deposits are a source of their own.
    """
    get = lambda st, names: {r["period"]: r["value"] for r in _annual(_series(c, ticker, st, names)[1])}  # noqa: E731
    debt, cap, res = (
        get("balance-sheet", ["Borrowings", "Borrowing"]),
        get("balance-sheet", ["Equity Capital"]),
        get("balance-sheet", ["Reserves"]),
    )
    other, total = get("balance-sheet", ["Other Liabilities"]), get("balance-sheet", ["Total Liabilities"])
    deposits = get("balance-sheet", ["Deposits"])
    lender = ticker in FINANCIALS
    cwip, pbt, interest = (
        get("balance-sheet", ["CWIP"]),
        get("profit-loss", ["Profit before tax"]),
        get("profit-loss", ["Interest"]),
    )
    years = []
    for y in [p for p in debt if p in total][-5:]:
        equity = (cap.get(y) or 0) + (res.get(y) or 0)
        tot = total[y]
        years.append(
            {
                "period": y,
                "debt": debt[y],
                "equity": equity,
                "other_liabilities": other.get(y),
                "total": tot,
                "debt_to_equity": round(debt[y] / equity, 2) if equity else None,
                "interest_coverage": round((pbt[y] + interest[y]) / interest[y], 1)
                if not lender and pbt.get(y) is not None and interest.get(y)
                else None,
                "mix": {
                    k: round(100 * v / tot, 1) if tot and v is not None else None
                    for k, v in (
                        ("deposits", deposits.get(y)),
                        ("debt", debt[y]),
                        ("equity", equity),
                        ("other", other.get(y)),
                    )
                    if k != "deposits" or y in deposits
                },
                "cwip": cwip.get(y),
            }
        )
    covered = [y for y in years if y["interest_coverage"] is not None]
    return {
        "years": years,
        "interest_coverage": {"period": covered[-1]["period"], "value": covered[-1]["interest_coverage"]}
        if covered
        else None,
        "is_financial": lender,
    }


def segments(c: sqlite3.Connection, ticker: str) -> dict | None:
    """Revenue mix and segment margins for the latest quarter, from the segment table in the same exchange filing.

    Shares are of total segment revenue as filed (before inter-segment eliminations), because some companies'
    segment totals do not tie to headline revenue (see sources.nse._segments). Margin is segment result (profit
    before interest and tax) / segment revenue. Growth is against the same quarter a year earlier, matched by name.
    """
    cur = c.execute(
        "SELECT period_end, segments, source_url FROM results WHERE ticker=? AND segments IS NOT NULL"
        " ORDER BY period_end DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if not cur:
        return None
    seg = json.loads(cur["segments"])
    out = {
        "quarter": quarter_label(cur["period_end"]),
        "period_end": cur["period_end"],
        "source_url": cur["source_url"],
        "single": seg.get("single"),
        "items": [],
    }
    items = seg.get("items") or []
    if not items:
        return out
    ya = c.execute(
        "SELECT segments FROM results WHERE ticker=? AND period_end=?",
        (ticker, _quarter_back(date.fromisoformat(cur["period_end"]), 4)),
    ).fetchone()
    before = {i["name"]: i for i in (json.loads(ya["segments"]).get("items") or [])} if ya and ya["segments"] else {}

    def shares(rows):
        total = sum(i["revenue"] for i in rows if i["revenue"] and i["revenue"] > 0)
        return {i["name"]: 100 * i["revenue"] / total for i in rows if total and i["revenue"] is not None}

    now_share, old_share = shares(items), shares(list(before.values()))
    for i in items:
        rev, res, b = i["revenue"], i["result"], before.get(i["name"])
        if not rev and not res:  # e.g. HDFCBANK's "Unallocated" row: no revenue, no result
            continue
        out["items"].append(
            {
                "name": i["name"],
                "revenue": rev,
                "result": res,
                "share_pct": round(now_share[i["name"]], 1) if i["name"] in now_share else None,
                "margin_pct": round(100 * res / rev, 1) if res is not None and rev and rev > 0 else None,
                "yoy": pct(rev, b["revenue"]) if b else None,
                "share_change_pts": round(now_share[i["name"]] - old_share[i["name"]], 1)
                if i["name"] in now_share and i["name"] in old_share
                else None,
            }
        )
    out["items"].sort(key=lambda i: -(i["revenue"] or 0))
    return out


def scale(c: sqlite3.Connection, ticker: str, amount_cr: float) -> dict:
    """An amount from a filing as a share of annual revenue and of market cap, so 'Rs 500 crore' means something.
    Market cap matters for fund raises and acquisitions: it is roughly the dilution or the bet's size."""
    _, sales = _series(c, ticker, "profit-loss", ["Sales", "Revenue"])
    ttm = next((r["value"] for r in sales if r["period"] == "TTM"), None)
    if ttm is None and _annual(sales):
        ttm = _annual(sales)[-1]["value"]
    co = c.execute("SELECT ratios FROM companies WHERE ticker=?", (ticker,)).fetchone()
    mcap = json.loads(co["ratios"] or "{}").get("Market Cap") if co else None
    return {
        "amount_cr": amount_cr,
        "annual_revenue_cr": ttm,
        "pct_of_revenue": round(100 * amount_cr / ttm, 2) if ttm else None,
        "market_cap_cr": mcap,
        "pct_of_market_cap": round(100 * amount_cr / mcap, 2) if mcap else None,
    }


IST = ZoneInfo("Asia/Kolkata")


def reaction(c: sqlite3.Connection, ticker: str, at: str, lookback: int = 20) -> dict | None:
    """How the stock traded in the first session after a filing: the same day if filed before the 15:30 IST
    close, else the next trading day. Move against the previous close; volume against the prior 20 sessions."""
    filed = datetime.fromisoformat(at)
    after_close = filed.time() >= time(15, 30)
    rows = c.execute("SELECT date, close, volume FROM eod WHERE ticker=? ORDER BY date", (ticker,)).fetchall()
    if not rows:
        return None
    day = filed.date().isoformat()
    i = next((k for k, r in enumerate(rows) if (r["date"] > day if after_close else r["date"] >= day)), None)
    if i is None:
        # No price yet for the session after the filing. Either that session is still ahead (filed Friday
        # evening, read on Saturday: Monday), or it has closed and its price is not loaded yet.
        session = filed.date() + timedelta(days=1) if after_close else filed.date()
        while session.weekday() >= 5:  # weekends; exchange holidays are not modelled
            session += timedelta(days=1)
        now = datetime.now(IST).replace(tzinfo=None)
        ahead = session > now.date() or (session == now.date() and now.time() < time(15, 30))
        return {"pending": True, "state": "upcoming" if ahead else "not_loaded", "date": session.isoformat()}
    if i == 0 or not rows[i - 1]["close"]:
        return None
    window = [r["volume"] for r in rows[max(0, i - lookback) : i]]
    avg = sum(window) / len(window) if window else None
    return {
        "pending": False,
        "date": rows[i]["date"],
        "session": "same day" if rows[i]["date"] == day else "next session",
        "move_pct": round(100 * (rows[i]["close"] / rows[i - 1]["close"] - 1), 2),
        "vol_mult": round(rows[i]["volume"] / avg, 2) if avg else None,
    }
