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
_info_cache:    dict[str, dict]  = {}
_news_cache:    dict[str, list]  = {}
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
    """Fetch one batch with one retry. Returns (close_df, dropped_tickers)."""
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

    period  = f"{PRICE_HISTORY_DAYS}d"
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


# ── per-ticker API helpers ────────────────────────────────────────────────────

def _get_info(ticker: str) -> dict:
    if ticker not in _info_cache:
        try:
            _info_cache[ticker] = yf.Ticker(ticker).info
        except Exception as exc:
            log.warning("Could not fetch info for %s: %s", ticker, exc)
            _info_cache[ticker] = {}
    return _info_cache[ticker]


def _get_news(ticker: str) -> list:
    if ticker not in _news_cache:
        try:
            _news_cache[ticker] = yf.Ticker(ticker).news or []
        except Exception:
            _news_cache[ticker] = []
    return _news_cache[ticker]


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


def _prefetch(
    fn: object,
    tickers: list[str],
    cache: dict,
    label: str,
    workers: int = 20,
) -> None:
    missing = [t for t in tickers if t not in cache]
    if not missing:
        return
    log.info("Prefetching %s for %d tickers…", label, len(missing))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, t): t for t in missing}  # type: ignore[operator]
        done = 0
        for _ in as_completed(futures):
            done += 1
            if done % 100 == 0:
                log.info("  %s: %d/%d", label, done, len(missing))


def _prefetch_info(tickers: list[str])    -> None: _prefetch(_get_info,    tickers, _info_cache,    ".info")
def _prefetch_news(tickers: list[str])    -> None: _prefetch(_get_news,    tickers, _news_cache,    "news")
def _prefetch_holders(tickers: list[str]) -> None: _prefetch(_get_holders, tickers, _holders_cache, "holders")


# ════════════════════════════════════════════════════════════════════════════
# Signal 1 — Market-neutralized residual correlation
# ════════════════════════════════════════════════════════════════════════════

def _exp_weights(n: int, halflife: float) -> np.ndarray:
    """Normalized exponential weights; index n-1 (most recent) has highest weight."""
    lam  = 0.5 ** (1.0 / halflife)
    lags = np.arange(n - 1, -1, -1)   # n-1…0 from oldest to newest
    w    = lam ** lags
    return w / w.sum()


def _weighted_corr(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> float:
    """Weighted Pearson correlation. w must already sum to 1."""
    wx    = np.dot(w, x)
    wy    = np.dot(w, y)
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
        y    = rets[col].values
        mask = np.isfinite(y) & np.isfinite(spy)
        if mask.sum() < 10:
            residuals[col] = pd.Series(np.full(len(y), np.nan), index=rets.index)
            continue
        X      = np.column_stack([spy[mask], np.ones(mask.sum())])
        coeffs, _, _, _ = np.linalg.lstsq(X, y[mask], rcond=None)
        fitted = spy * coeffs[0] + coeffs[1]
        resid  = np.where(mask, y - fitted, np.nan)
        residuals[col] = pd.Series(resid, index=rets.index)
    return pd.DataFrame(residuals)


def signal_correlation(
    user_ticker: str, candidates: list[str], prices: pd.DataFrame
) -> dict[str, float]:
    """
    Exponentially-weighted residual correlation, market-neutralized via OLS on SPY.
    Shrunk and mapped to [0, 1].
    """
    need     = [t for t in [user_ticker] + candidates + ["SPY"] if t in prices.columns]
    rets     = prices[need].pct_change(fill_method=None).dropna(how="all")
    residuals = _market_neutralize(rets)
    windowed  = residuals.iloc[-CORR_WINDOW:]

    if user_ticker not in windowed.columns:
        return {c: 0.5 for c in candidates}

    user_r = windowed[user_ticker].values
    base_w = _exp_weights(len(user_r), CORR_HALFLIFE)

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
        w    = w / w.sum()
        corr = _weighted_corr(user_r[mask], cand_r[mask], w)
        scores[cand] = (corr * n / (n + SHRINK_K) + 1) / 2
    return scores

    # SIMPLE FALLBACK: Pearson correlation of daily returns over the full window.
    # rets = prices[[user_ticker] + candidates].pct_change(fill_method=None).dropna()
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
    """longBusinessSummary + cached recent headlines. Degrades gracefully to ticker name."""
    info  = _get_info(ticker)
    parts = [info.get("longBusinessSummary", "")]
    for item in (_get_news(ticker)[:10] if isinstance(_get_news(ticker), list) else []):
        title = (
            item.get("title")
            or (item.get("content") or {}).get("title")
            or ""
        )
        if title:
            parts.append(title)
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
    #     counts[cand] = sum(
    #         1 for item in _get_news(user_ticker)
    #         if user_name in (item.get("title","")).lower()
    #         and cand_name in (item.get("title","")).lower()
    #     )
    # mx = max(counts.values(), default=1) or 1
    # return {c: v / mx for c, v in counts.items()}


# ════════════════════════════════════════════════════════════════════════════
# Signal 4 — Fund overlap  (upgraded = rarity-weighted)
# ════════════════════════════════════════════════════════════════════════════

def signal_fund_overlap(user_ticker: str, candidates: list[str]) -> dict[str, float]:
    """
    Shared institutional holders weighted by 1/log(ubiquity+2).
    Ubiquity = count of stocks in {user} ∪ {candidates} that share the holder.
    Down-weights Vanguard/BlackRock-type universal holders.
    """
    all_tickers  = [user_ticker] + candidates
    holder_count: dict[str, int] = {}
    for t in all_tickers:
        for h in _get_holders(t):
            holder_count[h] = holder_count.get(h, 0) + 1

    user_holders = set(_get_holders(user_ticker))

    scores: dict[str, float] = {}
    for cand in candidates:
        shared       = user_holders & set(_get_holders(cand))
        scores[cand] = sum(1.0 / math.log(holder_count[h] + 2) for h in shared)
    return scores

    # SIMPLE FALLBACK: raw count of shared institutional holders, normalized by max.
    # user_holders = set(_get_holders(user_ticker))
    # counts = {c: len(user_holders & set(_get_holders(c))) for c in candidates}
    # mx = max(counts.values(), default=1) or 1
    # return {c: v / mx for c, v in counts.items()}


# ════════════════════════════════════════════════════════════════════════════
# Rank normalization + combined score
# ════════════════════════════════════════════════════════════════════════════

def rank_normalize(scores: dict[str, float]) -> dict[str, float]:
    """Percentile rank each raw score independently; ties → average rank."""
    return pd.Series(scores).rank(pct=True).to_dict()


def _combined_score(
    r_corr:   dict[str, float],
    r_sector: dict[str, float],
    r_news:   dict[str, float],
    r_funds:  dict[str, float],
) -> dict[str, float]:
    return {
        c: (0.45 * r_corr.get(c, 0.0)
          + 0.15 * r_sector.get(c, 0.0)
          + 0.20 * r_news.get(c, 0.0)
          + 0.20 * r_funds.get(c, 0.0))
        for c in r_corr
    }


def _ranking_key(
    S:        dict[str, float],
    r_corr:   dict[str, float],
    r_sector: dict[str, float],
    r_news:   dict[str, float],
    r_funds:  dict[str, float],
) -> dict[str, float]:
    if USE_MAXPOOL:
        return {c: 0.7 * S[c] + 0.3 * max(r_corr[c], r_sector[c], r_news[c], r_funds[c]) for c in S}
    else:
        return S


# ════════════════════════════════════════════════════════════════════════════
# Output assembler — /graph contract
# ════════════════════════════════════════════════════════════════════════════

def build_graph(
    holdings: list[dict],   # [{ticker, shares, cost_basis}]
    prices:   pd.DataFrame,
    universe: list[str],
) -> dict:
    """
    For each holding run all four signals, rank-normalize, compute combined score S,
    take top 8 by ranking key. Assemble nodes / edges / portfolio dict.

    Edge weight is always S (not the pooled key) so thickness reflects true signal blend.
    """
    holding_tickers = [h["ticker"] for h in holdings]
    all_needed      = list(dict.fromkeys(holding_tickers + universe))

    log.info("Prefetching .info, news, holders for %d tickers…", len(all_needed))
    _prefetch_info(all_needed)
    _prefetch_news(all_needed)
    _prefetch_holders(all_needed)

    nodes: dict[str, dict] = {}
    edges: list[dict]      = []

    for h in holdings:
        ticker     = h["ticker"]
        candidates = [t for t in universe if t != ticker]

        # Raw signals
        s1 = signal_correlation(ticker, candidates, prices)
        s2 = signal_sector(ticker, candidates)
        s3 = signal_semantic(ticker, candidates)
        s4 = signal_fund_overlap(ticker, candidates)

        # Percentile-rank each signal independently
        r1 = rank_normalize(s1)
        r2 = rank_normalize(s2)
        r3 = rank_normalize(s3)
        r4 = rank_normalize(s4)

        S   = _combined_score(r1, r2, r3, r4)
        key = _ranking_key(S, r1, r2, r3, r4)

        top8 = sorted(key, key=key.__getitem__, reverse=True)[:8]

        for cand in top8:
            edges.append({"source": ticker, "target": cand, "weight": round(S[cand], 4)})
            if cand not in nodes:
                info = _get_info(cand)
                nodes[cand] = {"ticker": cand, "name": info.get("shortName", cand)}

        if ticker not in nodes:
            info = _get_info(ticker)
            nodes[ticker] = {"ticker": ticker, "name": info.get("shortName", ticker)}

    # Portfolio positions
    positions   = []
    total_value = 0.0
    total_pl    = 0.0
    for h in holdings:
        ticker        = h["ticker"]
        shares        = h["shares"]
        cost_basis    = h["cost_basis"]
        current_price = float(prices[ticker].dropna().iloc[-1]) if ticker in prices.columns else 0.0
        current_value = shares * current_price
        pl            = shares * (current_price - cost_basis)
        total_value  += current_value
        total_pl     += pl
        positions.append({
            "ticker":        ticker,
            "shares":        shares,
            "cost_basis":    cost_basis,
            "current_price": round(current_price, 2),
            "current_value": round(current_value, 2),
            "pl":            round(pl, 2),
        })

    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "portfolio": {
            "positions":   positions,
            "total_value": round(total_value, 2),
            "total_pl":    round(total_pl, 2),
        },
    }


# ════════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python engine.py TICKER [TICKER …]  — build /graph JSON for given holdings")
        sys.exit(1)

    tickers  = [t.upper() for t in sys.argv[1:]]
    universe = load_universe()

    # Dummy holdings for CLI testing: 100 shares, cost_basis=0
    holdings = [{"ticker": t, "shares": 100, "cost_basis": 0.0} for t in tickers]

    log.info("Fetching prices for %d universe tickers…", len(universe))
    prices = fetch_prices(list(dict.fromkeys(tickers + universe)))

    graph = build_graph(holdings, prices, universe)
    print(json.dumps(graph, indent=2))

    n_nodes = len(graph["nodes"])
    n_edges = len(graph["edges"])
    weights = [e["weight"] for e in graph["edges"]]
    log.info(
        "Done — nodes: %d  edges: %d  weight range: [%.4f, %.4f]",
        n_nodes, n_edges, min(weights, default=0), max(weights, default=0),
    )
