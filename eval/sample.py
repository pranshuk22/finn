"""Draw the classifier eval sample: 20 filings per stage, fixed seed, written WITHOUT FINN's labels.

The labeller sees only what the exchange published (label, summary text, the attachment from its subject line),
so the human label cannot be anchored on the classifier's answer.
Run: uv run python -m eval.sample
Held-out: uv run python -m eval.sample --seed 2028 --per-stage 10 --out holdout_blind.json \
  --exclude filings_labelled.json
"""

import argparse
import json
import random
import re
from pathlib import Path

from backend import db
from backend.sources import pdf

HERE = Path(__file__).parent


def first_page(url: str | None) -> str:
    if not url:
        return ""
    try:
        pages = pdf.pages(pdf.download(url), max_pages=2)
        text = " ".join(" ".join(pages).split())
        # skip letterhead and addresses: start at the subject line when there is one
        m = re.search(r"\b(Sub(ject)?\s*[:.-]|Dear Sir|Dear Madam|Re\s*:)", text, re.I)
        return text[m.start() if m else 0 :][:1200]
    except Exception as e:  # noqa: BLE001  a missing attachment is part of what the labeller sees
        return f"(attachment not readable: {type(e).__name__})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=2027)
    ap.add_argument("--per-stage", type=int, default=20)
    ap.add_argument("--out", default="sample_blind.json")
    ap.add_argument("--exclude", help="a labelled file whose filings must not be drawn again (held-out sample)")
    a = ap.parse_args()

    rng = random.Random(a.seed)
    seen = set()
    if a.exclude:
        seen = {x["id"] for x in json.loads((HERE / a.exclude).read_text())["items"]}
    with db.session() as c:
        rows = [
            dict(r) for r in c.execute("SELECT id, ticker, an_dt, nse_label, text, pdf_url, classified_by FROM filings")
        ]
    rows = [r for r in rows if r["id"] not in seen]
    sample = []
    for stage in ("label", "rule", "model"):
        pool = sorted((r for r in rows if r["classified_by"] == stage), key=lambda r: r["id"])
        sample += rng.sample(pool, min(a.per_stage, len(pool)))
    rng.shuffle(sample)  # the labeller should not see which stage a filing came from either

    def clean(s: str) -> str:  # the repo, like the app, never shows em or en dashes from filings
        return s.replace("\u2014", " - ").replace("\u2013", "-")

    blind = [
        {
            "n": i + 1,
            "id": r["id"],
            "ticker": r["ticker"],
            "date": r["an_dt"][:10],
            "nse_label": r["nse_label"],
            "text": clean(r["text"]),
            "attachment_excerpt": clean(first_page(r["pdf_url"])),
        }
        for i, r in enumerate(sample)
    ]
    out = HERE / a.out
    out.write_text(json.dumps(blind, indent=1, ensure_ascii=False))
    print(f"{len(blind)} filings -> {out}")


if __name__ == "__main__":
    main()
