import os
import re

import requests

NAVER_NEWS_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"

_TAG_RE = re.compile(r"<.*?>")


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text).replace("&quot;", '"').replace("&amp;", "&")


def fetch_headlines_kr(query: str, max_results: int = 5) -> list[dict]:
    """Fetch recent Korean-language headlines matching `query` via Naver Search API."""
    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET are not set in the environment")

    resp = requests.get(
        NAVER_NEWS_URL,
        params={"query": query, "display": max_results, "sort": "date"},
        headers={
            "X-NCP-APIGW-API-KEY-ID": client_id,
            "X-NCP-APIGW-API-KEY": client_secret,
        },
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    return [
        {
            "title": _strip_tags(item["title"]),
            "description": _strip_tags(item["description"]),
            "url": item["link"],
            "published_at": item["pubDate"],
        }
        for item in items
    ]


def fetch_all_kr(queries: list[str], max_results: int = 5) -> list[dict]:
    """Fetch Korean headlines for each query and dedupe by URL."""
    seen_urls = set()
    results = []
    for q in queries:
        for item in fetch_headlines_kr(q, max_results=max_results):
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                results.append(item)
    return results


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    import yaml

    with open("config/watchlist.yaml") as f:
        config = yaml.safe_load(f)

    queries = config["news_keywords_kr"]
    for item in fetch_all_kr(queries):
        print(item)
