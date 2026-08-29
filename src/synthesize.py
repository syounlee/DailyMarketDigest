import re
from datetime import date

import html as html_lib

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src.formatting import (
    format_index_quotes,
    format_news_text,
    format_news_text_with_links,
    format_stock_quotes,
    index_cards_html,
    news_items_html,
    portfolio_status_html,
    portfolio_status_text,
    render_email_shell,
    takeaways_html,
    takeaways_text,
    watchlist_rows_html,
)
from src.llm_provider import get_chat_model

# Write short grounded commentary in English. Runs on a strong English model
# (e.g. Llama 3.1) when LLM_PROVIDER=ollama. All numbers/prices in the final
# email are rendered directly from fetched data below, not by this model - it
# only ever writes text, which keeps it from inventing causes for price moves
# (or events) that aren't actually in the headlines. Korean headlines are fed
# in as-is (not translated) - the model reads them directly for grounding;
# they're also shown untranslated to the reader in the Headlines section.
COMMENTARY_SYSTEM_PROMPT = """\
You write content for a daily market digest email. Given US and Korean market data plus \
news headlines (some Korean headlines are in Korean - read them, but always write your \
response in English), produce:

1. Two short paragraphs (2-3 sentences each) on what's driving today's US and Korean markets.
2. Up to 3 short "key takeaways" - notable stories from the headlines worth the reader's \
   attention, even ones not tied to a specific price move (e.g. an upcoming earnings date \
   mentioned in a headline, a regulatory development, a notable analyst call). Each takeaway \
   is one short sentence, in English, even when it summarizes a Korean headline.

Only state a cause for a price move if a provided headline actually supports it - never \
invent or guess a reason. Only include a takeaway if it is actually grounded in a headline \
you were given - never invent a story, event, or date that wasn't provided. If a watchlist \
ticker moved more than 2%, mention it specifically if a headline explains why. If a previous \
day's snapshot is provided, you may briefly note day-over-day movement.

Respond in exactly this format, nothing else:
US: <paragraph>
KR: <paragraph>
TAKEAWAYS: <takeaway 1> | <takeaway 2> | <takeaway 3>

Omit the TAKEAWAYS line entirely if nothing in the headlines is worth calling out beyond
the two paragraphs above - don't pad it with restatements of the price commentary.
"""

COMMENTARY_HUMAN_TEMPLATE = """\
## US Indices
{us_indices}

## Korean Indices
{kr_indices}

## Watchlist Quotes
{watchlist_quotes}

## English-language News
{news_en}

## Korean-language News
{news_kr}

## Yesterday's Snapshot (may be empty on first run)
{previous_snapshot}
"""


def _parse_commentary(raw: str) -> tuple[str, str, list[str]]:
    us_match = re.search(r"US:\s*(.*?)(?=\n?KR:|\Z)", raw, re.DOTALL | re.IGNORECASE)
    kr_match = re.search(r"KR:\s*(.*?)(?=\n?TAKEAWAYS:|\Z)", raw, re.DOTALL | re.IGNORECASE)
    tk_match = re.search(r"TAKEAWAYS:\s*(.*)", raw, re.DOTALL | re.IGNORECASE)

    us = us_match.group(1).strip() if us_match else ""
    kr = kr_match.group(1).strip() if kr_match else ""
    takeaways = []
    if tk_match:
        takeaways = [t.strip() for t in tk_match.group(1).strip().split("|") if t.strip()]

    if not us and not kr:
        us = raw.strip()
    return us, kr, takeaways


def _format_previous_snapshot(snapshot: dict | None) -> str:
    """Format yesterday's snapshot into a short readable price recap - not a raw
    dict dump. Yesterday's news is intentionally omitted here (it's stale and
    was previously confusing the model, which saw raw JSON keys like "news_en"
    and started describing the data structure instead of writing commentary).
    """
    if not snapshot:
        return "(none - first run)"

    parts = []
    if snapshot.get("us_indices"):
        parts.append("US indices yesterday:\n" + format_index_quotes(snapshot["us_indices"]))
    if snapshot.get("kr_indices"):
        parts.append("KR indices yesterday:\n" + format_index_quotes(snapshot["kr_indices"]))
    if snapshot.get("watchlist_quotes"):
        parts.append("Watchlist yesterday:\n" + format_stock_quotes(snapshot["watchlist_quotes"]))
    return "\n\n".join(parts) if parts else "(none - first run)"


def _generate_commentary(
    market_data_us: list[dict],
    market_data_kr: list[dict],
    watchlist_quotes: list[dict],
    news_en: list[dict],
    news_kr: list[dict],
    previous_snapshot: dict | None,
) -> tuple[str, str, list[str]]:
    prompt = ChatPromptTemplate.from_messages(
        [("system", COMMENTARY_SYSTEM_PROMPT), ("human", COMMENTARY_HUMAN_TEMPLATE)]
    )
    chain = prompt | get_chat_model("en") | StrOutputParser()

    raw = chain.invoke(
        {
            "us_indices": format_index_quotes(market_data_us),
            "kr_indices": format_index_quotes(market_data_kr),
            "watchlist_quotes": format_stock_quotes(watchlist_quotes),
            "news_en": format_news_text(news_en),
            "news_kr": format_news_text(news_kr),
            "previous_snapshot": _format_previous_snapshot(previous_snapshot),
        }
    )
    return _parse_commentary(raw)


def _render_html(
    date_str, market_data_us, market_data_kr, watchlist_quotes, news_en, news_kr,
    us_commentary, kr_commentary, takeaways, portfolio_status,
) -> str:
    body = f"""\
    <div class="sectionlabel">US Market</div>
    <div class="cards">{index_cards_html(market_data_us)}</div>
    <p class="commentary">{html_lib.escape(us_commentary) or "(no commentary)"}</p>

    <div class="sectionlabel">Korea Market</div>
    <div class="cards">{index_cards_html(market_data_kr)}</div>
    <p class="commentary">{html_lib.escape(kr_commentary) or "(no commentary)"}</p>

    <div class="sectionlabel">Watchlist</div>
    <table>{watchlist_rows_html(watchlist_quotes)}</table>

    {portfolio_status_html(portfolio_status)}

    {takeaways_html(takeaways)}

    <div class="sectionlabel">Headlines</div>
    {news_items_html(news_en)}
    {news_items_html(news_kr)}
    """
    return render_email_shell(date_str, body)


def _render_text(
    date_str, market_data_us, market_data_kr, watchlist_quotes, news_en, news_kr,
    us_commentary, kr_commentary, takeaways, portfolio_status,
) -> str:
    lines = [f"DailyMarketDigest — {date_str}", ""]
    lines += ["US MARKET", format_index_quotes(market_data_us), "", us_commentary, ""]
    lines += ["KOREA MARKET", format_index_quotes(market_data_kr), "", kr_commentary, ""]
    lines += ["WATCHLIST", format_stock_quotes(watchlist_quotes), ""]
    ps = portfolio_status_text(portfolio_status)
    if ps:
        lines += [ps]
    tk = takeaways_text(takeaways)
    if tk:
        lines += [tk]
    lines += ["HEADLINES", format_news_text_with_links(news_en)]
    if news_kr:
        lines += [format_news_text_with_links(news_kr)]
    lines += ["", "Sent by DailyMarketDigest · Data via yfinance, Finnhub, Naver API Hub"]
    return "\n".join(lines)


def build_digest(
    market_data_us: list[dict],
    market_data_kr: list[dict],
    watchlist_quotes: list[dict],
    news_en: list[dict],
    news_kr: list[dict],
    previous_snapshot: dict | None,
    portfolio_status: dict | None = None,
) -> tuple[str, str]:
    """Returns (html_body, text_body)."""
    us_commentary, kr_commentary, takeaways = _generate_commentary(
        market_data_us, market_data_kr, watchlist_quotes, news_en, news_kr, previous_snapshot
    )

    date_str = date.today().strftime("%A, %B %-d, %Y")
    args = (
        date_str, market_data_us, market_data_kr, watchlist_quotes, news_en, news_kr,
        us_commentary, kr_commentary, takeaways, portfolio_status or {},
    )
    return _render_html(*args), _render_text(*args)


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()

    from src.market_data import fetch_quotes

    us_indices = fetch_quotes(["^GSPC", "^IXIC"])
    kr_indices = fetch_quotes(["^KS11", "^KQ11"])
    watchlist = fetch_quotes(["AAPL", "005930.KS"])

    fake_news_en = [
        {
            "title": "Fed signals steady rates into next quarter",
            "source": "Reuters",
            "url": "https://example.com/fed-rates",
        },
    ]
    fake_news_kr = [
        {
            "title": "삼성전자, 3분기 실적 예상치 상회",
            "description": "반도체 부문 회복세가 실적을 견인했다.",
            "url": "https://example.com/samsung-q3",
        },
    ]
    fake_portfolio_status = {
        "USD": {"value": 1200.0, "cost": 1000.0, "gain_loss": 200.0, "gain_loss_pct": 20.0},
        "KRW": {"value": 500000.0, "cost": 550000.0, "gain_loss": -50000.0, "gain_loss_pct": -9.09},
    }

    html_body, text_body = build_digest(
        us_indices, kr_indices, watchlist, fake_news_en, fake_news_kr, previous_snapshot=None,
        portfolio_status=fake_portfolio_status,
    )
    print("--- TEXT ---")
    print(text_body)
    print("\n--- HTML (first 500 chars) ---")
    print(html_body[:500])
