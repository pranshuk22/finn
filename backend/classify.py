"""Filing classification in three stages: exchange label, text rules, then a small model.

Stage shares on October 2026 data before tuning: 50% label, 28% rules, 23% model (EVIDENCE E3).
"""

import re
from typing import Literal

from pydantic import BaseModel

from backend import llm
from backend.config import CATEGORIES, LABEL_MAP

# Ordered: the first matching rule wins, so narrow patterns come before broad ones.
_RULES: list[tuple[str, str]] = [
    ("unclassified", r"newspaper|clipping|advertisement|publication of|esop|stock option|"
                     r"regulation 74\s*\(5\)|trading window|loss of share|duplicate share|"
                     r"secretarial compliance|sustainability report|brsr|investor grievance"),
    ("earnings_call", r"transcript|recording|earnings call|conference call|con\.? call|concall|webcast|"
                      r"call with (media|analysts)"),
    ("results", r"financial results|results for the (quarter|period|half|year)"),
    ("investor_meetings", r"investor meet|analysts? meet|institutional investor|one-on-one|"
                          r"investor conference|roadshow|\bpresentation\b"),
    ("postal_ballot", r"postal ballot"),
    ("agm_egm", r"annual general meeting|\bagm\b|extra-?ordinary general meeting|\begm\b"),
    ("pledging", r"pledge|encumbrance"),
    ("insider_trading", r"insider trading|\bsast\b|substantial acquisition|regulation 29|regulation 7\s*\(2\)"),
    ("credit_rating", r"credit rating|\brating\b"),
    ("bonus_split", r"\bbonus\b|stock split|sub-?division"),
    ("dividend", r"dividend"),
    ("management_change", r"appoint|resign|cessation|retire|chief executive|chief financial|"
                          r"managing director|\bceo\b|\bcfo\b|key managerial|senior management"),
    ("litigation", r"nclt|nclat|insolvency|tribunal|\bcourt\b|penalty|show cause|order passed|"
                   r"tax demand|litigation|arbitration|enforcement directorate|search and seizure"),
    ("M&A", r"acqui|merger|amalgamat|demerg|joint venture|scheme of arrangement|divest|"
            r"disinvest|sale of (stake|shares|business|undertaking)|incorporation of"),
    ("fund_raise", r"initial public offer|\bipo\b|red herring|qualified institutions? placement|\bqip\b|"
                   r"rights issue|preferential (issue|allotment)|debenture|\bncds?\b|commercial paper|"
                   r"buy-?back|raising of funds|fund rais|allotment of (equity )?shares"),
    ("capex", r"capital expenditure|\bcapex\b|capacity expansion|greenfield|brownfield|"
              r"new (plant|facility|manufacturing)|commercial production|commissioning"),
    ("press_release", r"press release|media release|media statement|order|contract|launch|"
                      r"partnership|clarification|rumou?r|verification|award"),
]
_RULES_RE = [(cat, re.compile(p, re.I)) for cat, p in _RULES]

# Labels too generic to trust; their category comes from the text.
AMBIGUOUS_LABELS = {
    "General Updates", "General updates", "Updates", "Outcome of Board Meeting", "Press Release",
    "Press Release (Revised)", "Analysts/Institutional Investor Meet/Con. Call Updates",
    "Record Date", "Allotment of Securities", "Agreements", "Agreement", "Others", "Miscellaneous",
}


def by_label(label: str) -> str | None:
    if label in AMBIGUOUS_LABELS:
        return None
    return LABEL_MAP.get(label)


def by_rules(text: str) -> str | None:
    for cat, rx in _RULES_RE:
        if rx.search(text):
            return cat
    return None


def _has(text: str, pattern: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def priority(category: str, text: str, label: str = "") -> str:
    """needs_you | worth_knowing | routine. The judgment table in the README, as code."""
    t = text
    if category == "results":
        if _has(t, r"newspaper|advertisement|publication"):
            return "routine"
        if _has(t, r"to consider|intimation of (the )?board meeting|will be held|is scheduled|trading window"):
            return "routine"
        if label == "Investor Presentation" or _has(t, r"presentation"):
            return "worth_knowing"
        return "needs_you"
    if category == "management_change":
        if _has(t, r"re-?appoint|designation|company secretary|compliance officer|"
                   r"senior management personnel|independent director"):
            return "worth_knowing"
        if _has(t, r"\bceo\b|\bcfo\b|chief executive|chief financial|managing director|chairman|"
                   r"whole-?time director|key managerial|\bkmp\b") or label == "Change in Management":
            return "needs_you"
        return "worth_knowing"
    if category == "litigation":
        if _has(t, r"insolvency|nclt|nclat|\bsebi\b|enforcement directorate|\bcbi\b|fraud|"
                   r"search|suspension|winding up"):
            return "needs_you"
        return "worth_knowing"
    if category == "credit_rating":
        if _has(t, r"downgrad|negative"):
            return "needs_you"
        if _has(t, r"upgrad|positive"):
            return "worth_knowing"
        return "routine"
    if category == "pledging":
        return "needs_you" if _has(t, r"invo[ck]|creat") else "worth_knowing"
    if category == "insider_trading":
        return "worth_knowing" if _has(t, r"promoter") and _has(t, r"sale|sold|dispos|sell") else "routine"
    if category == "dividend":
        if _has(t, r"payment|\btds\b|record date") and not _has(t, r"declar|recommend"):
            return "routine"
        return "worth_knowing"
    if category in ("M&A", "fund_raise", "capex", "bonus_split"):
        return "worth_knowing"
    if category == "press_release":
        return "worth_knowing" if _has(t, r"order|contract|award|launch|acqui|clarification|rumou?r|verification") else "routine"
    return "routine"


_PREFIX = re.compile(
    r"^.{0,120}?has (informed|submitted to) the exchange,?\s*(the\s+)?(regarding|about|that|for)?\s*",
    re.I,
)


def tidy_summary(text: str) -> str:
    """The company's own one-liner minus the boilerplate opening."""
    s = _PREFIX.sub("", text).strip().strip("'\"").rstrip(".")
    s = re.sub(r"\s+", " ", s)
    return (s[:1].upper() + s[1:]) if s else text


# ---------- model stage ----------

class _Item(BaseModel):
    id: str
    category: Literal[tuple(CATEGORIES)]  # type: ignore[valid-type]
    material: bool
    one_line: str


class _Batch(BaseModel):
    items: list[_Item]


_SYSTEM = """You sort Indian stock exchange filings for an investor.
Categories: results, M&A, fund_raise, management_change, litigation, insider_trading,
earnings_call, investor_meetings, credit_rating, dividend, bonus_split, capex, press_release,
postal_ballot, agm_egm, pledging, unclassified.
unclassified means routine paperwork that does not move the stock.
material is true only if a long-term shareholder would want to know about it today.
one_line: at most 15 words, plain English, state the fact, no company name, no adjectives.
Use only the text given. If the text is too vague to tell, choose unclassified and say what it is."""


# Summaries this generic say nothing; for these we read the start of the PDF before asking the model.
_VAGUE = re.compile(r"general updates?|disclosure under regulation 30|outcome of (the )?(board )?meeting|"
                    r"intimation|updates?$|regulation 30", re.I)


def is_vague(text: str) -> bool:
    return len(text) < 260 and _VAGUE.search(text) is not None


def by_model(filings: list[dict], batch_size: int = 20) -> dict[str, _Item]:
    out: dict[str, _Item] = {}
    for i in range(0, len(filings), batch_size):
        chunk = filings[i:i + batch_size]
        lines = []
        for f in chunk:
            line = f"[{f['id']}] {f['ticker']} | label: {f['nse_label']} | {f['text']}"
            if f.get("peek"):
                line += f"\n    first page of the filing: {f['peek']}"
            lines.append(line)
        res: _Batch = llm.generate(
            task="classify", model=llm.LITE, contents="\n".join(lines), schema=_Batch, system=_SYSTEM,
        )
        for it in res.items:
            out[it.id] = it
    return out


def classify(filings: list[dict], use_model: bool = True) -> list[dict]:
    """Adds category, priority, summary, classified_by to each filing dict."""
    pending = []
    for f in filings:
        cat = by_label(f["nse_label"])
        how = "label"
        if cat is None:
            cat = by_rules(f["text"])
            how = "rule"
        if cat is None:
            pending.append(f)
            continue
        f.update(category=cat, classified_by=how, summary=tidy_summary(f["text"]),
                 priority=priority(cat, f["text"], f["nse_label"]))

    if pending and use_model:
        results = by_model(pending)
        for f in pending:
            it = results.get(f["id"])
            if it is None:
                f.update(category="unclassified", classified_by="fallback",
                         summary=tidy_summary(f["text"]), priority="routine")
                continue
            p = priority(it.category, f["text"] + " " + f.get("peek", ""), f["nse_label"])
            if it.material and p == "routine":
                p = "worth_knowing"
            if not it.material and p == "needs_you":
                p = "worth_knowing"
            f.update(category=it.category, classified_by="model", summary=it.one_line, priority=p)
    else:
        for f in pending:
            f.update(category="unclassified", classified_by="fallback",
                     summary=tidy_summary(f["text"]), priority="routine")
    return filings
