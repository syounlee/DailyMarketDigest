import os
from datetime import date

import requests

FINNHUB_BASE = "https://finnhub.io/api/v1"


def _api_key() -> str:
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY is not set in the environment")
    return api_key


def fetch_upcoming_earnings(tickers: list[str], start: date, end: date) -> list[dict]:
    """Fetch confirmed earnings dates within [start, end] for each ticker via
    Finnhub's earnings calendar. Only meaningfully covers US-listed tickers -
    Finnhub doesn't reliably track KRX-listed stocks, so Korean watchlist
    tickers will typically just come back with nothing, which callers should
    treat as "no confirmed earnings this week", not an error.
    """
    results = []
    for symbol in tickers:
        resp = requests.get(
            f"{FINNHUB_BASE}/calendar/earnings",
            params={
                "symbol": symbol,
                "from": start.isoformat(),
                "to": end.isoformat(),
                "token": _api_key(),
            },
            timeout=15,
        )
        resp.raise_for_status()
        for item in resp.json().get("earningsCalendar", []):
            results.append(
                {
                    "symbol": item.get("symbol", symbol),
                    "date": item.get("date"),
                    "hour": item.get("hour"),  # "bmo" (before open) / "amc" (after close) / ""
                    "eps_estimate": item.get("epsEstimate"),
                }
            )
    results.sort(key=lambda e: e.get("date") or "")
    return results


if __name__ == "__main__":
    from datetime import timedelta

    from dotenv import load_dotenv

    load_dotenv()
    import yaml

    with open("config/watchlist.yaml") as f:
        config = yaml.safe_load(f)

    today = date.today()
    entries = fetch_upcoming_earnings(config["watchlist_us"], today, today + timedelta(days=7))
    if not entries:
        print("(no confirmed earnings in the next 7 days for the US watchlist)")
    for e in entries:
        print(e)
