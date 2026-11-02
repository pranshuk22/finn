"""End-of-day price and volume from Yahoo Finance."""

import pandas as pd
import yfinance as yf


def download(tickers: list[str], days: int = 120) -> list[tuple[str, str, float, int]]:
    """Rows of (ticker, date, close, volume).

    The latest row sometimes has volume but no close (seen for all 18 tickers on
    2026-10-30, RESEARCH E9). Such rows are dropped, never filled.
    """
    df = yf.download(
        [t + ".NS" for t in tickers],
        period=f"{days}d",
        progress=False,
        auto_adjust=False,
        group_by="ticker",
        threads=True,
    )
    rows = []
    for t in tickers:
        if (t + ".NS") not in df.columns.get_level_values(0):
            continue
        sub = df[t + ".NS"][["Close", "Volume"]].dropna(subset=["Close"])
        for idx, r in sub.iterrows():
            if pd.isna(r["Volume"]):
                continue
            rows.append((t, idx.date().isoformat(), float(r["Close"]), int(r["Volume"])))
    return rows
