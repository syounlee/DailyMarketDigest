from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src.llm_provider import get_chat_model

# Stage 1: translate/summarize Korean headlines into English. Runs on a
# Korean-specialized model (e.g. EXAONE) when LLM_PROVIDER=ollama.
KR_TRANSLATE_SYSTEM_PROMPT = """\
You translate Korean financial news headlines into English for a US-based reader.
For each headline, output one concise English bullet point capturing the key fact -
translate faithfully, don't add commentary or analysis. Output plain bullets only,
no preamble.
"""

KR_TRANSLATE_HUMAN_TEMPLATE = """\
## Korean-language News
{news_kr}
"""

# Stage 2: compose the full digest in English. Runs on a strong English model
# (e.g. Llama 3.1) when LLM_PROVIDER=ollama - this does the bulk of the writing.
SYSTEM_PROMPT = """\
You are a financial analyst writing a concise daily digest email for one reader.
Cover both the US and Korean markets. Structure the digest with these sections,
using plain text with clear headers (no markdown tables):

1. US Market Overview - major indices, one line each on direction/magnitude, \
   plus 2-3 sentences on what's driving today's US market news.
2. Korean Market Overview - KOSPI/KOSDAQ indices, same style, plus 2-3 sentences \
   on what's driving today's Korean market news (a pre-translated English summary \
   of the Korean news is provided below - use it directly).
3. Watchlist - one line per ticker (US and Korean) with price and % change, \
   noting any that moved more than 2% and why if news explains it.

Be concise: aim for a digest that reads in under two minutes. If a previous day's \
snapshot is provided, briefly reference day-over-day movement where relevant.
"""

HUMAN_TEMPLATE = """\
## US Indices
{us_indices}

## Korean Indices
{kr_indices}

## Watchlist Quotes
{watchlist_quotes}

## English-language News
{news_en}

## Korean-language News (pre-translated to English)
{news_kr_translated}

## Yesterday's Snapshot (may be empty on first run)
{previous_snapshot}
"""


def _format_quotes(quotes: list[dict]) -> str:
    if not quotes:
        return "(none)"
    lines = []
    for q in quotes:
        pct = q.get("pct_change")
        pct_str = f"{pct:+.2f}%" if pct is not None else "n/a"
        lines.append(
            f"- {q['name']} ({q['ticker']}): {q.get('price')} {q.get('currency', '')} ({pct_str})"
        )
    return "\n".join(lines)


def _format_news(articles: list[dict]) -> str:
    if not articles:
        return "(none)"
    lines = []
    for a in articles:
        extra = f" - {a['description']}" if a.get("description") else ""
        lines.append(f"- {a['title']}{extra} ({a.get('source', a.get('url', ''))})")
    return "\n".join(lines)


def translate_kr_news(news_kr: list[dict]) -> str:
    """Stage 1: translate Korean headlines to English bullets via the 'kr' role model."""
    if not news_kr:
        return "(none)"

    prompt = ChatPromptTemplate.from_messages(
        [("system", KR_TRANSLATE_SYSTEM_PROMPT), ("human", KR_TRANSLATE_HUMAN_TEMPLATE)]
    )
    chain = prompt | get_chat_model("kr") | StrOutputParser()
    return chain.invoke({"news_kr": _format_news(news_kr)})


def build_digest(
    market_data_us: list[dict],
    market_data_kr: list[dict],
    watchlist_quotes: list[dict],
    news_en: list[dict],
    news_kr: list[dict],
    previous_snapshot: dict | None,
) -> str:
    news_kr_translated = translate_kr_news(news_kr)

    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("human", HUMAN_TEMPLATE)]
    )
    chain = prompt | get_chat_model("en") | StrOutputParser()

    return chain.invoke(
        {
            "us_indices": _format_quotes(market_data_us),
            "kr_indices": _format_quotes(market_data_kr),
            "watchlist_quotes": _format_quotes(watchlist_quotes),
            "news_en": _format_news(news_en),
            "news_kr_translated": news_kr_translated,
            "previous_snapshot": previous_snapshot or "(none - first run)",
        }
    )


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    from src.market_data import fetch_quotes

    us_indices = fetch_quotes(["^GSPC", "^IXIC"])
    kr_indices = fetch_quotes(["^KS11", "^KQ11"])
    watchlist = fetch_quotes(["AAPL", "005930.KS"])

    fake_news_en = [
        {"title": "Fed signals steady rates into next quarter", "source": "Reuters"},
    ]
    fake_news_kr = [
        {
            "title": "삼성전자, 3분기 실적 예상치 상회",
            "description": "반도체 부문 회복세가 실적을 견인했다.",
            "source": "naver",
        },
    ]

    digest = build_digest(
        us_indices, kr_indices, watchlist, fake_news_en, fake_news_kr, previous_snapshot=None
    )
    print(digest)