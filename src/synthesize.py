import html
import re
from datetime import date

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src.llm_provider import get_chat_model

# Stage 1: translate Korean headlines into English, one line per headline.
# Runs on a Korean-specialized model (e.g. EXAONE) when LLM_PROVIDER=ollama.
KR_TRANSLATE_SYSTEM_PROMPT = """\
You translate Korean financial news headlines into English for a US-based reader.
Output exactly one line per input headline, in the same order, translated faithfully -
no bullets, no numbering, no commentary, no preamble. Just the translated headlines,
one per line.
"""

KR_TRANSLATE_HUMAN_TEMPLATE = """\
## Korean-language News
{news_kr}
"""

# Stage 2: write short grounded commentary in English. Runs on a strong English
# model (e.g. Llama 3.1) when LLM_PROVIDER=ollama. All numbers/prices in the
# final email are rendered directly from fetched data below, not by this model -
# it only ever writes the two commentary paragraphs, which keeps it from
# inventing causes for price moves that aren't actually in the headlines.
COMMENTARY_SYSTEM_PROMPT = """\
You write short market commentary for a daily digest email. Given US and Korean market \
data plus news headlines, write exactly two short paragraphs (2-3 sentences each), plain \
English, no markdown, no headers.

Only state a cause for a price move if a provided headline actually supports it - never \
invent or guess a reason. If nothing in the headlines explains a move, just don't speculate \
about it. If a watchlist ticker moved more than 2%, mention it specifically if a headline \
explains why. If a previous day's snapshot is provided, you may briefly note day-over-day \
movement.

Respond with exactly two lines, starting literally with "US:" and "KR:" - nothing else, \
no other text before or after.
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

## Korean-language News (translated to English)
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


def _format_index_quotes(quotes: list[dict]) -> str:
    """Like _format_quotes, but for indices - these are point values, not a currency amount."""
    if not quotes:
        return "(none)"
    lines = []
    for q in quotes:
        pct = q.get("pct_change")
        pct_str = f"{pct:+.2f}%" if pct is not None else "n/a"
        price = q.get("price")
        price_str = f"{price:,.2f} pts" if price is not None else "n/a"
        lines.append(f"- {q['name']} ({q['ticker']}): {price_str} ({pct_str})")
    return "\n".join(lines)


def _format_news(articles: list[dict]) -> str:
    if not articles:
        return "(none)"
    lines = []
    for a in articles:
        extra = f" - {a['description']}" if a.get("description") else ""
        lines.append(f"- {a['title']}{extra} ({a.get('source', a.get('url', ''))})")
    return "\n".join(lines)


def translate_kr_news(news_kr: list[dict]) -> list[str]:
    """Stage 1: translate Korean headlines to English, one string per headline."""
    if not news_kr:
        return []

    prompt = ChatPromptTemplate.from_messages(
        [("system", KR_TRANSLATE_SYSTEM_PROMPT), ("human", KR_TRANSLATE_HUMAN_TEMPLATE)]
    )
    chain = prompt | get_chat_model("kr") | StrOutputParser()
    raw = chain.invoke({"news_kr": _format_news(news_kr)})

    lines = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^[-•*]\s*", "", line)
        line = re.sub(r"^\d+[.)]\s*", "", line)
        lines.append(line)
    return lines


def _parse_commentary(raw: str) -> tuple[str, str]:
    us_match = re.search(r"US:\s*(.*?)(?=\n?KR:|\Z)", raw, re.DOTALL | re.IGNORECASE)
    kr_match = re.search(r"KR:\s*(.*)", raw, re.DOTALL | re.IGNORECASE)
    us = us_match.group(1).strip() if us_match else ""
    kr = kr_match.group(1).strip() if kr_match else ""
    if not us and not kr:
        us = raw.strip()
    return us, kr


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
        parts.append("US indices yesterday:\n" + _format_index_quotes(snapshot["us_indices"]))
    if snapshot.get("kr_indices"):
        parts.append("KR indices yesterday:\n" + _format_index_quotes(snapshot["kr_indices"]))
    if snapshot.get("watchlist_quotes"):
        parts.append("Watchlist yesterday:\n" + _format_quotes(snapshot["watchlist_quotes"]))
    return "\n\n".join(parts) if parts else "(none - first run)"


def _generate_commentary(
    market_data_us: list[dict],
    market_data_kr: list[dict],
    watchlist_quotes: list[dict],
    news_en: list[dict],
    kr_translated: list[str],
    previous_snapshot: dict | None,
) -> tuple[str, str]:
    prompt = ChatPromptTemplate.from_messages(
        [("system", COMMENTARY_SYSTEM_PROMPT), ("human", COMMENTARY_HUMAN_TEMPLATE)]
    )
    chain = prompt | get_chat_model("en") | StrOutputParser()

    news_kr_translated_text = (
        "\n".join(f"- {line}" for line in kr_translated) if kr_translated else "(none)"
    )
    raw = chain.invoke(
        {
            "us_indices": _format_index_quotes(market_data_us),
            "kr_indices": _format_index_quotes(market_data_kr),
            "watchlist_quotes": _format_quotes(watchlist_quotes),
            "news_en": _format_news(news_en),
            "news_kr_translated": news_kr_translated_text,
            "previous_snapshot": _format_previous_snapshot(previous_snapshot),
        }
    )
    return _parse_commentary(raw)


def _fmt_price(price, currency) -> str:
    if price is None:
        return "n/a"
    if currency == "KRW":
        return f"₩{price:,.0f}"
    return f"${price:,.2f}"


def _fmt_index_value(price) -> str:
    """Indices are point values, not a currency amount - no $ / ₩ prefix."""
    return f"{price:,.2f}" if price is not None else "n/a"


def _chip_html(pct) -> str:
    if pct is None:
        return '<span class="chip">n/a</span>'
    cls = "up" if pct >= 0 else "down"
    arrow = "▲" if pct >= 0 else "▼"
    return f'<span class="chip {cls}">{arrow} {abs(pct):.2f}%</span>'


def _index_cards_html(quotes: list[dict]) -> str:
    cards = []
    for q in quotes:
        name = html.escape(str(q.get("name", q.get("ticker", ""))))
        price = html.escape(_fmt_index_value(q.get("price")))
        cards.append(
            f'<div class="card"><div class="name">{name}</div>'
            f'<div class="price">{price}</div>{_chip_html(q.get("pct_change"))}</div>'
        )
    return "".join(cards) or '<div class="card"><div class="name">(no data)</div></div>'


def _watchlist_rows_html(quotes: list[dict]) -> str:
    rows = []
    for q in quotes:
        name = html.escape(str(q.get("name", "")))
        ticker = html.escape(str(q.get("ticker", "")))
        price = html.escape(_fmt_price(q.get("price"), q.get("currency")))
        rows.append(
            f"<tr><td>{name} ({ticker})</td><td class='num'>{price}</td>"
            f"<td class='num'>{_chip_html(q.get('pct_change'))}</td></tr>"
        )
    return "".join(rows) or "<tr><td>(no watchlist data)</td></tr>"


def _news_items_html(items: list[dict]) -> str:
    if not items:
        return '<div class="newsitem">No headlines today.</div>'
    out = []
    for a in items:
        title = html.escape(str(a.get("title", "")))
        src = html.escape(str(a.get("source") or a.get("url", "")))
        out.append(f'<div class="newsitem">{title}<span class="src">{src}</span></div>')
    return "".join(out)


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: #F5F6F8;
    color: #1D2229;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  }}
  .em-dash {{ max-width: 640px; margin: 0 auto; padding: 24px 22px 30px; }}
  .head {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }}
  .brand {{ font-weight: 800; font-size: 15px; letter-spacing: -0.01em; }}
  .brand .dot {{ color: #4C5FD5; }}
  .date {{ font-size: 12px; color: #6B7280; }}
  .sectionlabel {{
    font-size: 11px; font-weight: 700; letter-spacing: 0.06em; color: #6B7280;
    text-transform: uppercase; margin: 22px 0 10px;
  }}
  .cards {{ display: flex; gap: 8px; flex-wrap: wrap; }}
  .card {{
    background: #FFFFFF; border: 1px solid #E4E6EA; border-radius: 10px;
    padding: 10px 12px; flex: 1 1 140px; min-width: 140px;
  }}
  .card .name {{ font-size: 11.5px; color: #6B7280; margin-bottom: 4px; }}
  .card .price {{ font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }}
  .chip {{
    display: inline-block; margin-top: 5px; padding: 2px 7px; border-radius: 100px;
    font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums;
  }}
  .chip.up {{ color: #16803C; background: #E4F5EA; }}
  .chip.down {{ color: #C22E2E; background: #FBE7E7; }}
  table {{
    width: 100%; border-collapse: collapse; background: #FFFFFF;
    border: 1px solid #E4E6EA; border-radius: 10px; overflow: hidden;
  }}
  table td {{ padding: 10px 12px; font-size: 13px; border-bottom: 1px solid #EEF0F2; }}
  table tr:last-child td {{ border-bottom: none; }}
  table td.num {{ text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }}
  p.commentary {{ font-size: 13px; color: #4B5158; margin: 10px 2px 0; line-height: 1.6; }}
  .newsitem {{
    background: #FFFFFF; border: 1px solid #E4E6EA; border-radius: 10px;
    padding: 10px 12px; margin-bottom: 6px; font-size: 12.5px;
  }}
  .newsitem .src {{ display: block; color: #9199A3; font-size: 11px; margin-top: 3px; }}
  .foot {{ margin-top: 22px; color: #9199A3; font-size: 11px; text-align: center; }}
</style>
</head>
<body>
  <div class="em-dash">
    <div class="head">
      <span class="brand">DailyMarket<span class="dot">Digest</span></span>
      <span class="date">{date_str}</span>
    </div>

    <div class="sectionlabel">US Market</div>
    <div class="cards">{us_cards}</div>
    <p class="commentary">{us_commentary}</p>

    <div class="sectionlabel">Korea Market</div>
    <div class="cards">{kr_cards}</div>
    <p class="commentary">{kr_commentary}</p>

    <div class="sectionlabel">Watchlist</div>
    <table>{watchlist_rows}</table>

    <div class="sectionlabel">Headlines</div>
    {news_en_html}
    {news_kr_html}

    <div class="foot">Sent by DailyMarketDigest &middot; Data via yfinance, Finnhub, Naver API Hub</div>
  </div>
</body>
</html>
"""


def _render_html(
    date_str, market_data_us, market_data_kr, watchlist_quotes, news_en, kr_translated,
    us_commentary, kr_commentary,
) -> str:
    kr_news_items = [{"title": t, "source": "Translated · Naver"} for t in kr_translated]
    return _HTML_TEMPLATE.format(
        date_str=html.escape(date_str),
        us_cards=_index_cards_html(market_data_us),
        kr_cards=_index_cards_html(market_data_kr),
        us_commentary=html.escape(us_commentary) or "(no commentary)",
        kr_commentary=html.escape(kr_commentary) or "(no commentary)",
        watchlist_rows=_watchlist_rows_html(watchlist_quotes),
        news_en_html=_news_items_html(news_en),
        news_kr_html=_news_items_html(kr_news_items),
    )


def _render_text(
    date_str, market_data_us, market_data_kr, watchlist_quotes, news_en, kr_translated,
    us_commentary, kr_commentary,
) -> str:
    lines = [f"DailyMarketDigest — {date_str}", ""]
    lines += ["US MARKET", _format_index_quotes(market_data_us), "", us_commentary, ""]
    lines += ["KOREA MARKET", _format_index_quotes(market_data_kr), "", kr_commentary, ""]
    lines += ["WATCHLIST", _format_quotes(watchlist_quotes), ""]
    lines += ["HEADLINES", _format_news(news_en)]
    if kr_translated:
        lines += ["- " + t for t in kr_translated]
    lines += ["", "Sent by DailyMarketDigest · Data via yfinance, Finnhub, Naver API Hub"]
    return "\n".join(lines)


def build_digest(
    market_data_us: list[dict],
    market_data_kr: list[dict],
    watchlist_quotes: list[dict],
    news_en: list[dict],
    news_kr: list[dict],
    previous_snapshot: dict | None,
) -> tuple[str, str]:
    """Returns (html_body, text_body)."""
    kr_translated = translate_kr_news(news_kr)
    us_commentary, kr_commentary = _generate_commentary(
        market_data_us, market_data_kr, watchlist_quotes, news_en, kr_translated, previous_snapshot
    )

    date_str = date.today().strftime("%A, %B %-d, %Y")
    args = (
        date_str, market_data_us, market_data_kr, watchlist_quotes, news_en, kr_translated,
        us_commentary, kr_commentary,
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
        {"title": "Fed signals steady rates into next quarter", "source": "Reuters"},
    ]
    fake_news_kr = [
        {
            "title": "삼성전자, 3분기 실적 예상치 상회",
            "description": "반도체 부문 회복세가 실적을 견인했다.",
            "source": "naver",
        },
    ]

    html_body, text_body = build_digest(
        us_indices, kr_indices, watchlist, fake_news_en, fake_news_kr, previous_snapshot=None
    )
    print("--- TEXT ---")
    print(text_body)
    print("\n--- HTML (first 500 chars) ---")
    print(html_body[:500])
