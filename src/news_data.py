import os
from datetime import date, datetime, timedelta

import requests

FINNHUB_BASE = "https://finnhub.io/api/v1"


def _api_key() -> str:
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY is not set in the environment")
    return api_key


def fetch_company_news(symbol: str, days_back: int = 1, max_results: int = 5) -> list[dict]:
    """Fetch recent real-time news for a specific ticker via Finnhub's company-news endpoint."""
    today = date.today()
    resp = requests.get(
        f"{FINNHUB_BASE}/company-news",
        params={
            "symbol": symbol,
            "from": (today - timedelta(days=days_back)).isoformat(),
            "to": today.isoformat(),
            "token": _api_key(),
        },
        timeout=15,
    )
    resp.raise_for_status()
    articles = sorted(resp.json(), key=lambda a: a.get("datetime", 0), reverse=True)
    return [_normalize(a) for a in articles[:max_results]]


def fetch_general_news(category: str = "general", max_results: int = 5) -> list[dict]:
    """Fetch recent real-time market news via Finnhub's general news endpoint.

    Valid categories: general, forex, crypto, merger.
    """
    resp = requests.get(
        f"{FINNHUB_BASE}/news",
        params={"category": category, "token": _api_key()},
        timeout=15,
    )
    resp.raise_for_status()
    articles = sorted(resp.json(), key=lambda a: a.get("datetime", 0), reverse=True)
    return [_normalize(a) for a in articles[:max_results]]


def _normalize(article: dict) -> dict:
    return {
        "title": article["headline"],
        "source": article.get("source", ""),
        "url": article["url"],
        "published_at": datetime.fromtimestamp(article["datetime"]).isoformat(),
    }


def fetch_all(tickers: list[str], categories: list[str], max_results: int = 5) -> list[dict]:
    """Fetch per-ticker company news plus general-category market news, deduped by URL."""
    seen_urls = set()
    results = []

    def _add(items: list[dict]) -> None:
        for item in items:
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                results.append(item)

    for symbol in tickers:
        _add(fetch_company_news(symbol, max_results=max_results))
    for category in categories:
        _add(fetch_general_news(category, max_results=max_results))

    return results


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    import yaml

    with open("config/watchlist.yaml") as f:
        config = yaml.safe_load(f)

    items = fetch_all(config["watchlist_us"], config["news_categories_en"])
    for item in items:
        print(item)
