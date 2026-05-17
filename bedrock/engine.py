import json
import logging
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

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

# in-process caches
_price_cache:   dict[str, tuple[pd.DataFrame, float]] = {}
_info_cache:    dict[str, dict] = {}
_holders_cache: dict[str, list[str]] = {}


# ════════════════════════════════════════════════════════════════════════════
# Data layer
# ════════════════════════════════════════════════════════════════════════════

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
    return pd.DataFrame(), batch


def fetch_prices(tickers: list[str]) -> pd.DataFrame:
    """Return daily close prices for tickers + SPY for PRICE_HISTORY_DAYS."""
    all_tickers = list(dict.fromkeys(["SPY"] + list(tickers)))

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
    result = result.dropna(axis=1, how="all")

    actually_dropped = [t for t in all_dropped if t not in result.columns]
    if actually_dropped:
        log.warning("Dropped tickers (no data): %s", actually_dropped)

    _price_cache[key] = (result, time.time())
    return result


# ── info / holders helpers ────────────────────────────────────────────────────

def _get_info(ticker: str) -> dict:
    if ticker not in _info_cache:
        try:
            _info_cache[ticker] = yf.Ticker(ticker).info
        except Exception as exc:
            log.warning("Could not fetch info for %s: %s", ticker, exc)
            _info_cache[ticker] = {}
    return _info_cache[ticker]


def _get_holders(ticker: str) -> list[str]:
    if ticker not in _holders_cache:
        try:
            df = yf.Ticker(ticker).institutional_holders
            if df is not None and not df.empty and "Holder" in df.columns:
                _holders_cache[ticker] = df["Holder"].dropna().tolist()
            else:
                _holders_cache[ticker] = []
        except Exception as exc:
            log.warning("Could not fetch holders for %s: %s", ticker, exc)
            _holders_cache[ticker] = []
    return _holders_cache[ticker]


def _prefetch_info(tickers: list[str], workers: int = 20) -> None:
    missing = [t for t in tickers if t not in _info_cache]
    if not missing:
        return
    log.info("Prefetching .info for %d tickers…", len(missing))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_get_info, t): t for t in missing}
        done = 0
        for _ in as_completed(futures):
            done += 1
            if done % 100 == 0:
                log.info("  info: %d/%d", done, len(missing))


def _prefetch_holders(tickers: list[str], workers: int = 20) -> None:
    missing = [t for t in tickers if t not in _holders_cache]
    if not missing:
        return
    log.info("Prefetching institutional holders for %d tickers…", len(missing))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_get_holders, t): t for t in missing}
        done = 0
        for _ in as_completed(futures):
            done += 1
            if done % 100 == 0:
                log.info("  holders: %d/%d", done, len(missing))


# ════════════════════════════════════════════════════════════════════════════
# Signal 1 — Market-neutralized residual correlation
# ════════════════════════════════════════════════════════════════════════════

def _exp_weights(n: int, halflife: float) -> np.ndarray:
    """Normalized exponential weights; index n-1 (most recent) has highest weight."""
    lam = 0.5 ** (1.0 / halflife)
    # position 0 = oldest, n-1 = newest → lag from newest = n-1-i
    lags = np.arange(n - 1, -1, -1)
    w = lam ** lags
    return w / w.sum()


def _weighted_corr(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    """Weighted Pearson correlation. w must already sum to 1."""
    wx = np.dot(w, x)
    wy = np.dot(w, y)
    cov   = np.dot(w, (x - wx) * (y - wy))
    std_x = np.sqrt(np.dot(w, (x - wx) ** 2))
    std_y = np.sqrt(np.dot(w, (y - wy) ** 2))
    if std_x < 1e-10 or std_y < 1e-10:
        return 0.0
    return float(cov / (std_x * std_y))


def _market_neutralize(rets: pd.DataFrame) -> pd.DataFrame:
    """Replace each non-SPY column with OLS residuals after regressing on SPY returns."""
    if "SPY" not in rets.columns:
        return rets
    spy = rets["SPY"].values
    residuals: dict[str, pd.Series] = {}
    for col in rets.columns:
        if col == "SPY":
            continue
        y = rets[col].values
        mask = np.isfinite(y) & np.isfinite(spy)
        if mask.sum() < 10:
            residuals[col] = pd.Series(np.full(len(y), np.nan), index=rets.index)
            continue
        X = np.column_stack([spy[mask], np.ones(mask.sum())])
        coeffs, _, _, _ = np.linalg.lstsq(X, y[mask], rcond=None)
        fitted = spy * coeffs[0] + coeffs[1]
        resid = np.where(mask, y - fitted, np.nan)
        residuals[col] = pd.Series(resid, index=rets.index)
    return pd.DataFrame(residuals)


def signal_correlation(
    user_ticker: str, candidates: list[str], prices: pd.DataFrame
) -> dict[str, float]:
    """
    Score each candidate by exponentially-weighted residual correlation with user_ticker,
    after market-neutralizing both series via OLS on SPY. Shrunk and mapped to [0,1].
    """
    need = [t for t in [user_ticker] + candidates + ["SPY"] if t in prices.columns]
    rets = prices[need].pct_change(fill_method=None).dropna(how="all")
    residuals = _market_neutralize(rets)
    windowed  = residuals.iloc[-CORR_WINDOW:]

    if user_ticker not in windowed.columns:
        return {c: 0.5 for c in candidates}

    user_r    = windowed[user_ticker].values
    base_w    = _exp_weights(len(user_r), CORR_HALFLIFE)

    scores: dict[str, float] = {}
    for cand in candidates:
        if cand not in windowed.columns:
            scores[cand] = 0.5
            continue
        cand_r = windowed[cand].values
        mask   = np.isfinite(user_r) & np.isfinite(cand_r)
        n      = int(mask.sum())
        if n < 10:
            scores[cand] = 0.5
            continue
        w    = base_w[mask]
        w    = w / w.sum()          # renormalize after dropping NaN positions
        corr = _weighted_corr(user_r[mask], cand_r[mask], w)
        corr_shrunk = corr * n / (n + SHRINK_K)
        scores[cand] = (corr_shrunk + 1) / 2
    return scores

    # SIMPLE FALLBACK: Pearson correlation of daily returns over the full window.
    # rets = prices[[user_ticker] + candidates].pct_change().dropna()
    # return {c: (rets[user_ticker].corr(rets[c]) + 1) / 2
    #         for c in candidates if c in rets.columns}


# ════════════════════════════════════════════════════════════════════════════
# Signal 2 — Sector / industry  (intentionally simple, no upgrade)
# ════════════════════════════════════════════════════════════════════════════

def signal_sector(user_ticker: str, candidates: list[str]) -> dict[str, float]:
    """Same industry → 1.0; same sector → 0.6; otherwise → 0.0."""
    user_info     = _get_info(user_ticker)
    user_industry = user_info.get("industry", "")
    user_sector   = user_info.get("sector", "")

    scores: dict[str, float] = {}
    for cand in candidates:
        info = _get_info(cand)
        if user_industry and info.get("industry") == user_industry:
            scores[cand] = 1.0
        elif user_sector and info.get("sector") == user_sector:
            scores[cand] = 0.6
        else:
            scores[cand] = 0.0
    return scores


# ════════════════════════════════════════════════════════════════════════════
# Signal 3 — News / semantic  (upgraded = TF-IDF cosine)
# ════════════════════════════════════════════════════════════════════════════

def _build_document(ticker: str) -> str:
    """longBusinessSummary + recent headlines; degrades gracefully to ticker name."""
    info  = _get_info(ticker)
    parts = [info.get("longBusinessSummary", "")]
    try:
        news = yf.Ticker(ticker).news or []
        for item in (news[:10] if isinstance(news, list) else []):
            # yfinance ≥ 0.2.x nests title under content dict
            title = (
                item.get("title")
                or (item.get("content") or {}).get("title")
                or ""
            )
            if title:
                parts.append(title)
    except Exception:
        pass
    doc = " ".join(p for p in parts if p).strip()
    return doc or ticker  # never empty


def signal_semantic(user_ticker: str, candidates: list[str]) -> dict[str, float]:
    """TF-IDF cosine similarity between user stock's document and each candidate's."""
    all_tickers = [user_ticker] + candidates
    docs = [_build_document(t) for t in all_tickers]

    try:
        vec    = TfidfVectorizer(norm="l2", stop_words="english")
        matrix = vec.fit_transform(docs)
        sims   = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    except Exception as exc:
        log.warning("TF-IDF failed (%s); returning 0.0 for all candidates", exc)
        return {c: 0.0 for c in candidates}

    return {cand: float(sim) for cand, sim in zip(candidates, sims)}

    # SIMPLE FALLBACK: co-occurrence of both company names in the same Yahoo RSS headline.
    # user_name = _get_info(user_ticker).get("shortName", user_ticker).lower()
    # counts: dict[str, int] = {}
    # for cand in candidates:
    #     cand_name = _get_info(cand).get("shortName", cand).lower()
    #     try:
    #         headlines = [n.get("title", "") for n in (yf.Ticker(user_ticker).news or [])]
    #     except Exception:
    #         headlines = []
    #     counts[cand] = sum(
    #         1 for h in headlines if user_name in h.lower() and cand_name in h.lower()
    #     )
    # mx = max(counts.values(), default=1) or 1
    # return {c: v / mx for c, v in counts.items()}


# ════════════════════════════════════════════════════════════════════════════
# Signal 4 — Fund overlap  (upgraded = rarity-weighted)
# ════════════════════════════════════════════════════════════════════════════

def signal_fund_overlap(user_ticker: str, candidates: list[str]) -> dict[str, float]:
    """
    Shared institutional holders, weighted by 1/log(ubiquity+2).
    Ubiquity = how many stocks in {user} ∪ {candidates} share that holder.
    Down-weights Vanguard/BlackRock-type universal holders.
    """
    all_tickers = [user_ticker] + candidates

    # Count how many stocks in the working set each holder appears in
    holder_count: dict[str, int] = {}
    for t in all_tickers:
        for h in _get_holders(t):
            holder_count[h] = holder_count.get(h, 0) + 1

    user_holders = set(_get_holders(user_ticker))

    scores: dict[str, float] = {}
    for cand in candidates:
        cand_holders = set(_get_holders(cand))
        shared       = user_holders & cand_holders
        scores[cand] = sum(1.0 / math.log(holder_count[h] + 2) for h in shared)
    return scores

    # SIMPLE FALLBACK: raw count of shared institutional holders, normalized by max.
    # user_holders = set(_get_holders(user_ticker))
    # counts = {c: len(user_holders & set(_get_holders(c))) for c in candidates}
    # mx = max(counts.values(), default=1) or 1
    # return {c: v / mx for c, v in counts.items()}


# ════════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════════

def _top10(scores: dict[str, float]) -> list[tuple[str, float]]:
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:10]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python engine.py TICKER          — run all four signals vs universe")
        print("  python engine.py TICKER1 TICKER2 — fetch prices and print shape")
        sys.exit(1)

    if len(sys.argv) == 2:
        # ── Signal mode: single ticker vs full universe ───────────────────────
        user     = sys.argv[1].upper()
        universe = load_universe()
        candidates = [t for t in universe if t != user]

        print(f"\n{'='*62}")
        print(f"  {user}  vs  {len(candidates)} universe candidates")
        print(f"{'='*62}\n")

        # Signal 1 — needs prices for everyone
        print("► Signal 1: fetching prices (universe + SPY)…")
        prices = fetch_prices([user] + universe)
        s1 = signal_correlation(user, candidates, prices)
        print("\nSignal 1 — Residual Correlation  [0=anti, 0.5=neutral, 1=max]")
        for ticker, score in _top10(s1):
            print(f"  {ticker:<8}  {score:.4f}")

        # Signals 2 & 3 share a .info prefetch
        print("\n► Signals 2 & 3: prefetching .info…")
        _prefetch_info([user] + candidates)

        s2 = signal_sector(user, candidates)
        print("\nSignal 2 — Sector / Industry  [0=none, 0.6=sector, 1.0=industry]")
        for ticker, score in _top10(s2):
            info = _get_info(ticker)
            print(f"  {ticker:<8}  {score:.1f}  {info.get('industry', '?')}")

        s3 = signal_semantic(user, candidates)
        print("\nSignal 3 — Semantic / TF-IDF  [0=unrelated, 1=identical]")
        for ticker, score in _top10(s3):
            print(f"  {ticker:<8}  {score:.4f}")

        # Signal 4 — needs institutional holders
        print("\n► Signal 4: prefetching institutional holders…")
        _prefetch_holders([user] + candidates)

        s4 = signal_fund_overlap(user, candidates)
        print("\nSignal 4 — Fund Overlap / Rarity-Weighted  [higher = more rare shared holders]")
        for ticker, score in _top10(s4):
            print(f"  {ticker:<8}  {score:.4f}")

    else:
        # ── Price-shape mode (backward compat) ───────────────────────────────
        tickers = [t.upper() for t in sys.argv[1:]]
        df = fetch_prices(tickers)
        print(f"\nShape: {df.shape}")
        print(f"Columns: {list(df.columns)}")
        print(f"SPY present: {'SPY' in df.columns}")
        dropped = [t for t in tickers if t not in df.columns]
        if dropped:
            print(f"Dropped: {dropped}")
        print(df.tail(3))
