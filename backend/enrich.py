"""Read the filing PDF for cards that need more than the exchange one-liner.

Management changes: who joined or left, in what role, and a short background from a web search.
Exchange summaries like "change in Management" do not name the person (EVIDENCE E4).
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from backend import classify, db, llm
from backend.config import PORTFOLIO, USER_AGENT
from backend.sources import pdf


class Person(BaseModel):
    name: str
    role: str = Field(description="Role at this company, e.g. 'Chief Financial Officer'")
    change: Literal["joining", "leaving", "redesignated", "reappointed"]
    senior: bool = Field(description="True for CEO, CFO, MD, chairperson, whole-time director or KMP")
    profile_from_filing: str | None = Field(
        None, description="The person's background as the filing itself states it, at most 40 words, else null"
    )
    entity: str | None = Field(
        None, description="The subsidiary or group company where the role is, if it is not the filing company"
    )
    effective: str | None = None


class FilingRead(BaseModel):
    one_line: str = Field(description="At most 20 words. The fact, with numbers if the filing gives them.")
    people: list[Person] = []
    amount_rs_crore: float | None = Field(None, description="Deal, order, capex or fund-raise size if stated")


_READ_SYSTEM = """You read the first pages of an Indian stock exchange filing and state what it says.
one_line: at most 20 words, plain English, no company name, no adjectives, include the key number if there is one.
people: only people whose role changes in this filing. Leave empty otherwise.
If the change is at a subsidiary or group company, set entity to that company's name and say so in one_line
(for example "Subsidiary ICICI Life: MD and CEO resigns"). Never present a subsidiary's role as the parent's.
amount_rs_crore: convert lakh to crore (100 lakh = 1 crore) and millions to crore (10 million = 1 crore)
only if the filing states an amount in rupees. Otherwise null.
Use only the text given."""


class Bio(BaseModel):
    lines: list[str] = Field(description="Up to 3 short lines: current or last role, earlier roles, education")
    sources: list[int] = Field(description="Numbers of the search results each line relies on")
    confident: bool = Field(description="False if the results may be about a different person with the same name")


_BIO_SYSTEM = """You write a 3-line professional background of a named person for an investor, using only the
numbered web search results given. Background means where they worked before this appointment, in which roles,
and their education. Do not restate the new appointment itself.
Prefer the company's own website or filing over LinkedIn or news when they disagree.
If the results may describe a different person with the same name, set confident to false.
Do not add anything that is not in the results."""


def _needs_read(f) -> bool:
    if f["priority"] == "routine" or f["enrichment"] or not f["pdf_url"]:
        return False
    if f["category"] == "management_change":
        return True
    return classify.is_vague(f["summary"] or "") or len(f["summary"] or "") < 40


class _ReadItem(FilingRead):
    id: str


class _ReadBatch(BaseModel):
    items: list[_ReadItem]


def _pdf_text(f, client: httpx.Client) -> str | None:
    # Appointment disclosures carry the appointee's brief profile in an annexure, so read further.
    mgmt = f["category"] == "management_change"
    try:
        text = " ".join(pdf.pages(pdf.download(f["pdf_url"], client), max_pages=6 if mgmt else 3))
    except Exception as e:  # noqa: BLE001  a bad PDF must not stop the run
        print(f"  pdf failed {f['ticker']} {f['id']}: {e}")
        return None
    text = " ".join(text.split())[: 9000 if mgmt else 5000]
    return text if len(text) >= 80 else None


def read_filings(batch: list[tuple]) -> dict[str, dict]:
    """Several filings per call: the free tier allows 15 requests a minute on Flash-Lite."""
    blocks = [
        f"===== filing {f['id']} | company {f['ticker']} | exchange label: {f['nse_label']} =====\n{text}"
        for f, text in batch
    ]
    res: _ReadBatch = llm.generate(
        task="read_filing",
        model=llm.LITE,
        schema=_ReadBatch,
        system=_READ_SYSTEM + "\nReturn one item per filing, with its id.",
        contents="\n\n".join(blocks),
    )
    return {it.id: it.model_dump(exclude={"id"}) for it in res.items}


_STOP = {"limited", "ltd", "the", "of", "and", "&", "india", "co", "company"}


def _company_key(company: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", company.lower()) if w not in _STOP]
    return words[0] if words else company.lower()


def search_bio(name: str, company: str, role: str) -> dict | None:
    from ddgs import DDGS

    # Quoted, role-specific queries returned nothing; company in the query still guards against namesakes.
    results, query = [], ""
    # Plain "name company" results were mostly news of the appointment itself; asking for career history
    # surfaced earlier employers and education (EVIDENCE E18).
    for query in (f"{name} career previously worked", f"{name} {company} profile"):
        for attempt in range(2):  # the search backend returns "No results" intermittently
            try:
                results = DDGS().text(query, max_results=6)
            except Exception as e:  # noqa: BLE001  search is best-effort enrichment
                print(f"  search failed {name} ({query}): {e}")
                results = []
            if results:
                break
            time.sleep(3.0 * (attempt + 1))
        if results:
            break
    if not results:
        return None
    listing = "\n".join(f"[{i + 1}] {r['title']} | {r['href']}\n{r['body']}" for i, r in enumerate(results))
    bio: Bio = llm.generate(
        task="bio",
        model=llm.LITE,
        schema=Bio,
        system=_BIO_SYSTEM,
        contents=f"Person: {name}, {role} at {company}.\n\nSearch results:\n{listing}",
    )
    used = sorted({i for i in bio.sources if 1 <= i <= len(results)})
    if not used or not bio.lines:
        return None
    # Namesakes are common (EVIDENCE E5, E18). Trust the bio only if a source it uses names the company.
    key = _company_key(company)
    tied = any(key in (results[i - 1]["title"] + " " + results[i - 1]["body"]).lower() for i in used)
    return {
        "lines": bio.lines[:3],
        "confident": bio.confident and tied,
        "tied_to_company": tied,
        "sources": [{"title": results[i - 1]["title"], "url": results[i - 1]["href"]} for i in used],
        "query": query,
    }


def run(days: int = 35, limit: int | None = None) -> None:
    with db.session() as c:
        rows = c.execute(
            "SELECT * FROM filings WHERE an_dt >= date('now', ?) ORDER BY an_dt DESC", (f"-{days} days",)
        ).fetchall()
    todo = [r for r in rows if _needs_read(r)][:limit]
    print(f"enrich: {len(todo)} filings to read")

    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        with ThreadPoolExecutor(max_workers=4) as ex:
            texts = list(ex.map(lambda f: _pdf_text(f, client), todo))
    pairs = [(f, t) for f, t in zip(todo, texts, strict=True) if t]
    reads: dict[str, dict] = {}
    for i in range(0, len(pairs), 5):
        try:
            reads.update(read_filings(pairs[i : i + 5]))
        except Exception as e:  # noqa: BLE001  skip the batch; the next run picks it up again
            print(f"  batch failed: {e}")

    for f in todo:
        r = reads.get(f["id"])
        if not r:
            continue
        company = PORTFOLIO.get(f["ticker"], (f["ticker"],))[0]
        for p in r["people"]:
            if p["senior"] and p["change"] == "joining":
                p["bio"] = search_bio(p["name"], p.get("entity") or company, p["role"])
                time.sleep(1.0)
        summary = r["one_line"] if r["one_line"] else f["summary"]
        prio = f["priority"]
        if f["category"] == "management_change" and r["people"]:
            prio = management_priority(r["people"])
        with db.session() as c:
            c.execute(
                "UPDATE filings SET summary=?, priority=?, enrichment=? WHERE id=?",
                (summary, prio, json.dumps({"read": True, **r}), f["id"]),
            )
    print(f"enrich: done, {len(reads)} read")


_SENIOR = re.compile(
    r"\b(ceo|cfo|coo|md)\b|chief (executive|financial|operating) officer|managing director|"
    r"chair(man|person)?\b|whole[- ]?time director|executive director|key managerial",
    re.I,
)
_NOT_SENIOR = re.compile(r"independent|non-?executive|nominee", re.I)


def is_senior(role: str) -> bool:
    """Seniority is a rule, not the model's call: it marked independent directors and senior-management staff
    as senior, which put routine board changes into Needs you (classifier eval, E27)."""
    return bool(_SENIOR.search(role or "")) and not _NOT_SENIOR.search(role or "")


def management_priority(people: list[dict]) -> str:
    """Needs you only for a senior arrival or exit at the listed company itself."""
    if not people:
        return "worth_knowing"  # nothing could be read: do not bury it, do not escalate it
    own = [p for p in people if not p.get("entity")]
    if any(is_senior(p["role"]) and p["change"] in ("joining", "leaving") for p in own):
        return "needs_you"
    if all(p["change"] == "reappointed" for p in people):
        return "routine"
    return "worth_knowing"


def people_line(people: list[dict]) -> str | None:
    """'Jane Doe joins as CFO; John Roe leaves as CFO'. Built in Python from the extracted fields."""
    verbs = {"joining": "joins as", "leaving": "leaves as", "redesignated": "becomes", "reappointed": "reappointed as"}
    parts = [f"{p['name']} {verbs[p['change']]} {p['role']}" for p in people]
    return re.sub(r"\s+", " ", "; ".join(parts)) if parts else None


if __name__ == "__main__":
    run()
