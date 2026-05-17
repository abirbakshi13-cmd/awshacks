import json
import logging
import sys
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

# ── tunable constants ────────────────────────────────────────────────────────
PRICE_HISTORY_DAYS   = 365   # fetch a year for slack
CORR_WINDOW          = 120   # compute correlation on this many recent days
CORR_HALFLIFE        = 35    # exponential decay half-life in trading days
SHRINK_K             = 10    # correlation shrinkage constant
BATCH_SIZE           = 50
CACHE_TTL_SECONDS    = 3600
USE_MAXPOOL          = False  # optional tiebreaker, off by default
# ────────────────────────────────────────────────────────────────────────────

_UNIVERSE_PATH = Path(__file__).parent / "sp500.json"

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# in-process cache: {cache_key: (DataFrame, timestamp)}
_price_cache: dict[str, tuple[pd.DataFrame, float]] = {}


def load_universe() -> list[str]:
    data = json.loads(_UNIVERSE_PATH.read_text())
    return data["tickers"]


def _cache_key(tickers: list[str]) -> str:
    return ",".join(sorted(tickers))


def _fetch_batch(batch: list[str], period: str) -> tuple[pd.DataFrame, list[str]]:
    """Fetch one batch; one retry on failure. Returns (close_df, dropped)."""
    for attempt in range(2):
        try:
            raw = yf.download(
                batch,
                period=period,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if raw.empty:
                raise ValueError("empty response")
            # yfinance returns MultiIndex columns when >1 ticker
            if isinstance(raw.columns, pd.MultiIndex):
                close = raw["Close"]
            else:
                close = raw[["Close"]].rename(columns={"Close": batch[0]})
            return close, []
        except Exception as exc:
            if attempt == 0:
                log.warning("Batch failed (%s), retrying…", exc)
            else:
                log.error("Batch permanently failed (%s); dropping: %s", exc, batch)
                return pd.DataFrame(), batch
    return pd.DataFrame(), batch  # unreachable, satisfies type checker


def fetch_prices(tickers: list[str]) -> pd.DataFrame:
    """Return daily close prices for tickers + SPY for PRICE_HISTORY_DAYS."""
    all_tickers = list(dict.fromkeys(["SPY"] + list(tickers)))  # SPY first, deduped

    key = _cache_key(all_tickers)
    cached = _price_cache.get(key)
    if cached is not None:
        df, ts = cached
        if time.time() - ts < CACHE_TTL_SECONDS:
            log.info("Cache hit (%d tickers)", len(df.columns))
            return df

    period = f"{PRICE_HISTORY_DAYS}d"
    batches = [all_tickers[i : i + BATCH_SIZE] for i in range(0, len(all_tickers), BATCH_SIZE)]

    frames: list[pd.DataFrame] = []
    all_dropped: list[str] = []

    for i, batch in enumerate(batches):
        log.info("Fetching batch %d/%d (%d tickers)…", i + 1, len(batches), len(batch))
        df_batch, dropped = _fetch_batch(batch, period)
        if not df_batch.empty:
            frames.append(df_batch)
        all_dropped.extend(dropped)

    if not frames:
        raise RuntimeError("All batches failed; no price data available.")

    result = pd.concat(frames, axis=1)
    # drop columns that are entirely NaN (tickers with no data at all)
    result = result.dropna(axis=1, how="all")

    actually_dropped = [t for t in all_dropped if t not in result.columns]
    if actually_dropped:
        log.warning("Dropped tickers (no data): %s", actually_dropped)

    _price_cache[key] = (result, time.time())
    return result


if __name__ == "__main__":
    tickers = sys.argv[1:] if len(sys.argv) > 1 else []
    if not tickers:
        print("Usage: python engine.py TICKER1 TICKER2 ...")
        sys.exit(1)

    df = fetch_prices(tickers)
    print(f"\nShape: {df.shape}")
    print(f"Columns: {list(df.columns)}")
    print(f"SPY present: {'SPY' in df.columns}")
    dropped = [t for t in tickers if t not in df.columns]
    if dropped:
        print(f"Dropped: {dropped}")
    print(df.tail(3))
