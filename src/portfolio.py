"""Pure computation, no LLM calls: merges a person's holding config
(ticker/shares/buy_price/cost from config/people.yaml) with their live fetched
quotes (price/currency) to compute total portfolio value, cost basis, and
gain/loss - grouped by currency, since KR holdings are valued in KRW and US
holdings in USD and shouldn't be added together.
"""


def compute_totals(holdings: list[dict], quotes: list[dict]) -> dict:
    """Returns {currency: {"value", "cost", "gain_loss", "gain_loss_pct"}}.

    A holding contributes to `value` only if it has `shares` and a matching
    quote with a price. `cost` uses the holding's `cost` field if set,
    otherwise falls back to buy_price * shares; if neither is available for
    ANY holding in a currency group, that group's cost/gain_loss/gain_loss_pct
    come back as None (still-known `value`, just no cost-basis comparison).
    """
    quotes_by_ticker = {q["ticker"]: q for q in quotes}
    buckets: dict[str, dict] = {}

    for h in holdings:
        q = quotes_by_ticker.get(h["ticker"])
        shares = h.get("shares")
        if not q or q.get("price") is None or shares is None:
            continue

        currency = q.get("currency") or "USD"
        bucket = buckets.setdefault(currency, {"value": 0.0, "cost": 0.0, "cost_known": True})
        bucket["value"] += q["price"] * shares

        cost = h.get("cost")
        if cost is None and h.get("buy_price") is not None:
            cost = h["buy_price"] * shares
        if cost is not None:
            bucket["cost"] += cost
        else:
            bucket["cost_known"] = False

    results = {}
    for currency, bucket in buckets.items():
        gain_loss = None
        gain_loss_pct = None
        if bucket["cost_known"] and bucket["cost"]:
            gain_loss = bucket["value"] - bucket["cost"]
            gain_loss_pct = gain_loss / bucket["cost"] * 100
        results[currency] = {
            "value": bucket["value"],
            "cost": bucket["cost"] if bucket["cost_known"] else None,
            "gain_loss": gain_loss,
            "gain_loss_pct": gain_loss_pct,
        }
    return results


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    import main
    from src.market_data import fetch_quotes

    people = main.load_people()
    person = people[0]
    holdings = person["watchlist_us"] + person["watchlist_kr"]
    quotes = fetch_quotes(main.tickers(person["watchlist_us"]) + main.tickers(person["watchlist_kr"]))

    totals = compute_totals(holdings, quotes)
    for currency, s in totals.items():
        print(currency, s)
