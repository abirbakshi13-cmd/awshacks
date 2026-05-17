"""
One-time script to fetch the S&P 500 constituent list from Wikipedia
and write tickers to bedrock/sp500.json.

Run with --force to overwrite an existing sp500.json.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import io

import pandas as pd
import requests

OUTPUT = Path(__file__).parent / "sp500.json"
WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; sp500-fetcher/1.0)"}


def fetch_tickers() -> list[str]:
    resp = requests.get(WIKI_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text), attrs={"id": "constituents"})
    df = tables[0]
    tickers = df["Symbol"].tolist()
    return [t.replace(".", "-") for t in tickers]


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch S&P 500 tickers from Wikipedia.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing sp500.json")
    args = parser.parse_args()

    if OUTPUT.exists() and not args.force:
        print(f"WARNING: {OUTPUT} already exists. Pass --force to overwrite.", file=sys.stderr)
        sys.exit(1)

    tickers = fetch_tickers()
    payload = {
        "tickers": tickers,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    OUTPUT.write_text(json.dumps(payload, indent=2))
    print(f"Fetched {len(tickers)} tickers -> {OUTPUT}")


if __name__ == "__main__":
    main()
