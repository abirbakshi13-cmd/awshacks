"""
AWS Lambda handler for POST /graph.

Manual API Gateway setup (one-time):
  1. API Gateway console → Create REST API (Regional endpoint).
  2. Create resource /graph.
  3. Create method: POST → Lambda Function → this handler.
  4. Enable CORS on the /graph resource (Actions → Enable CORS).
     Set Access-Control-Allow-Origin to match ALLOWED_ORIGIN below.
  5. Deploy the API to a stage (e.g., "prod"). Note the Invoke URL.
  6. Update the frontend to POST to <Invoke URL>/graph.

Packaging reminder:
  - pandas, numpy, scikit-learn, yfinance are too large for the Lambda zip.
    Bundle them as a Lambda Layer (pip install -t python/ <deps> && zip -r layer.zip python/).
    Attach the layer to this function before deploying.
  - Do one warm-up POST request before the demo — first cold-start downloads
    price history and prefetches ~500 tickers of metadata (~2–3 min).
    Subsequent calls within CACHE_TTL_SECONDS are fast.
"""

import json
import logging

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

# NOTE: the allowed-origin value must match whatever the API Gateway CORS
# config uses — confirm with whoever owns that config before deploying.
ALLOWED_ORIGIN = "*"

_CORS_HEADERS = {
    "Access-Control-Allow-Origin":  ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def _make_response(status_code: int, body: dict | str) -> dict:
    """Wrap every response with CORS headers and a JSON body."""
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", **_CORS_HEADERS},
        "body": json.dumps(body) if not isinstance(body, str) else body,
    }


def handler(event: dict, context: object) -> dict:
    # OPTIONS preflight
    if event.get("httpMethod") == "OPTIONS":
        return _make_response(200, {})

    try:
        # ── parse body ────────────────────────────────────────────────────────
        raw = event.get("body") or "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return _make_response(400, {"error": "Request body is not valid JSON."})

        holdings = payload.get("holdings")
        if not isinstance(holdings, list) or len(holdings) == 0:
            return _make_response(
                400,
                {"error": "'holdings' must be a non-empty list of {ticker, shares, cost_basis}."},
            )

        # ── call engine ───────────────────────────────────────────────────────
        from engine import build_graph, fetch_prices, load_universe  # noqa: PLC0415

        universe = load_universe()
        holding_tickers = [h["ticker"] for h in holdings]
        prices = fetch_prices(list(dict.fromkeys(holding_tickers + universe)))
        graph  = build_graph(holdings, prices, universe)

        return _make_response(200, graph)

    except Exception as exc:
        log.exception("Unhandled error in handler")
        return _make_response(500, {"error": "Internal server error.", "detail": str(exc)})
