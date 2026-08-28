"""Sunday (weekly recap) and Monday (week ahead) digest variants.

Both markets are closed Sat/Sun, and the US session for "today" hasn't opened
yet by 7 AM KST Monday - so the regular daily digest is either a duplicate
(Sunday, nothing changed since Saturday) or misleadingly stale (Monday, shows
Friday's close as if current). These two builders replace the daily digest on
those two days with content that's actually useful: how the week went, and
what's confirmed to happen in the week ahead.

Same (html, text) tuple contract as synthesize.build_digest, and reuses
src/formatting.py so all three email types render identically.
"""

import html

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from src.formatting import (
    chip_html,
    format_index_quotes,
    format_news_text,
    format_stock_quotes,
    index_cards_html,
    news_items_html,
    render_email_shell,
    watchlist_rows_html,
)
from src.llm_provider import get_chat_model

# ---------------------------------------------------------------------------
# Weekly Recap (Sunday)
# ---------------------------------------------------------------------------

WEEKLY_COMMENTARY_SYSTEM_PROMPT = """\
You write a short weekly market recap for a Sunday digest email. Given this week's US and \
Korean index/watchlist performance (week-over-week % change) plus a sampling of this week's \
news headlines, write exactly two short paragraphs (2-3 sentences each), plain English, no \
markdown, no headers.

Only state a cause for a weekly move if a provided headline actually supports it - never \
invent or guess a reason. If nothing in the headlines explains a move, just report the \
number without speculating why.

If a % change is shown as "n/a", that means no prior-week data is available for comparison -
say so plainly (e.g. "no week-over-week comparison available yet"). Never treat "n/a" as 0%
or "unchanged" - those are different things and reporting "n/a" as flat/unchanged is wrong.

Respond with exactly two lines, starting literally with "US:" and "KR:" - nothing else, \
no other text before or after.
"""

WEEKLY_COMMENTARY_HUMAN_TEMPLATE = """\
## US Indices (week-over-week)
{us_indices}

## Korean Indices (week-over-week)
{kr_indices}

## Watchlist (week-over-week)
{watchlist_quotes}

## This Week's Headlines
{week_news}
"""


def _weekly_change(this_week: list[dict], last_week: list[dict] | None) -> list[dict]:
    """Same quote shape as fetch_quotes(), but pct_change is week-over-week
    instead of the usual day-over-day. Computed here in Python, never by the
    LLM. None when there's no matching prior-week data for that ticker.
    """
    last_by_ticker = {q["ticker"]: q for q in (last_week or [])}
    out = []
    for q in this_week:
        prev = last_by_ticker.get(q["ticker"])
        pct = None
        if prev and prev.get("price") and q.get("price") is not None:
            pct = (q["price"] - prev["price"]) / prev["price"] * 100
        out.append({**q, "pct_change": pct})
    return out


def _parse_commentary(raw: str) -> tuple[str, str]:
    import re

    us_match = re.search(r"US:\s*(.*?)(?=\n?KR:|\Z)", raw, re.DOTALL | re.IGNORECASE)
    kr_match = re.search(r"KR:\s*(.*)", raw, re.DOTALL | re.IGNORECASE)
    us = us_match.group(1).strip() if us_match else ""
    kr = kr_match.group(1).strip() if kr_match else ""
    if not us and not kr:
        us = raw.strip()
    return us, kr


def build_weekly_summary(
    this_week_us_indices: list[dict],
    this_week_kr_indices: list[dict],
    this_week_watchlist: list[dict],
    last_week_us_indices: list[dict] | None,
    last_week_kr_indices: list[dict] | None,
    last_week_watchlist: list[dict] | None,
    week_news_en: list[dict],
    week_news_kr_translated: list[str],
    date_str: str,
) -> tuple[str, str]:
    """Returns (html_body, text_body). week-over-week % change (this Friday's
    close vs. last Friday's close); if last week's data isn't available yet,
    falls back to showing current levels with no week-over-week comparison.
    """
    us_weekly = _weekly_change(this_week_us_indices, last_week_us_indices)
    kr_weekly = _weekly_change(this_week_kr_indices, last_week_kr_indices)
    watchlist_weekly = _weekly_change(this_week_watchlist, last_week_watchlist)
    has_history = bool(last_week_us_indices or last_week_kr_indices)

    week_news_text = (
        "\n".join(f"- {t}" for t in week_news_kr_translated) if week_news_kr_translated else "(none)"
    )
    prompt = ChatPromptTemplate.from_messages(
        [("system", WEEKLY_COMMENTARY_SYSTEM_PROMPT), ("human", WEEKLY_COMMENTARY_HUMAN_TEMPLATE)]
    )
    chain = prompt | get_chat_model("en") | StrOutputParser()
    raw = chain.invoke(
        {
            "us_indices": format_index_quotes(us_weekly),
            "kr_indices": format_index_quotes(kr_weekly),
            "watchlist_quotes": format_stock_quotes(watchlist_weekly),
            "week_news": format_news_text(week_news_en) + "\n" + week_news_text,
        }
    )
    us_commentary, kr_commentary = _parse_commentary(raw)

    kr_news_items = [{"title": t, "source": "Translated · Naver"} for t in week_news_kr_translated]

    note_html = (
        ""
        if has_history
        else '<div class="note">First weekly recap - week-over-week comparison will '
        "appear once there's a full week of history.</div>"
    )

    body = f"""\
    {note_html}
    <div class="sectionlabel">US Market — This Week</div>
    <div class="cards">{index_cards_html(us_weekly)}</div>
    <p class="commentary">{html.escape(us_commentary) or "(no commentary)"}</p>

    <div class="sectionlabel">Korea Market — This Week</div>
    <div class="cards">{index_cards_html(kr_weekly)}</div>
    <p class="commentary">{html.escape(kr_commentary) or "(no commentary)"}</p>

    <div class="sectionlabel">Watchlist — This Week</div>
    <table>{watchlist_rows_html(watchlist_weekly)}</table>

    <div class="sectionlabel">This Week's Headlines</div>
    {news_items_html(week_news_en)}
    {news_items_html(kr_news_items)}
    """
    html_body = render_email_shell(date_str, body, subtitle="Weekly Recap")

    lines = [f"DailyMarketDigest — Weekly Recap — {date_str}", ""]
    if not has_history:
        lines += ["(First weekly recap - no week-over-week comparison yet)", ""]
    lines += ["US MARKET (week-over-week)", format_index_quotes(us_weekly), "", us_commentary, ""]
    lines += ["KOREA MARKET (week-over-week)", format_index_quotes(kr_weekly), "", kr_commentary, ""]
    lines += ["WATCHLIST (week-over-week)", format_stock_quotes(watchlist_weekly), ""]
    lines += ["THIS WEEK'S HEADLINES", format_news_text(week_news_en)]
    if week_news_kr_translated:
        lines += ["- " + t for t in week_news_kr_translated]
    lines += ["", "Sent by DailyMarketDigest · Data via yfinance, Finnhub, Naver API Hub"]
    text_body = "\n".join(lines)

    return html_body, text_body


# ---------------------------------------------------------------------------
# Week Ahead (Monday)
# ---------------------------------------------------------------------------

WEEK_AHEAD_SYSTEM_PROMPT = """\
You write a short "what to watch this week" note for a Monday digest email, sent before the \
US market has opened. You'll be given last Friday's closing levels, confirmed earnings dates \
for this week (if any), and today's general news headlines.

Write exactly one short paragraph (2-4 sentences), plain English, no markdown, no headers. \
Only mention specific events (earnings, news topics) that were actually given to you - never \
invent or guess at a calendar event, economic release, or meeting that wasn't provided. If \
there's nothing notable in what you were given, it's fine to just briefly note last week's \
closing trend instead of speculating about the week ahead.

Respond with the paragraph only - no preamble, no "Here is..." framing.
"""

WEEK_AHEAD_HUMAN_TEMPLATE = """\
## Last Friday's Closing Levels - US Indices
{us_indices}

## Last Friday's Closing Levels - Korean Indices
{kr_indices}

## Confirmed Earnings This Week (US watchlist only)
{earnings}

## Today's News
{today_news}
"""


def _earnings_html(entries: list[dict], watchlist_quotes: list[dict]) -> str:
    if not entries:
        return '<div class="note">No confirmed earnings this week for your US watchlist tickers.</div>'
    name_by_ticker = {q["ticker"]: q.get("name", q["ticker"]) for q in watchlist_quotes}
    hour_label = {"bmo": "before open", "amc": "after close"}
    items = []
    for e in entries:
        name = html.escape(str(name_by_ticker.get(e["symbol"], e["symbol"])))
        symbol = html.escape(str(e["symbol"]))
        when = html.escape(str(e.get("date") or "TBD"))
        hour = hour_label.get(e.get("hour"), "")
        hour_str = f" ({html.escape(hour)})" if hour else ""
        items.append(f'<div class="newsitem">{name} ({symbol}) reports {when}{hour_str}</div>')
    return "".join(items)


def _earnings_text(entries: list[dict], watchlist_quotes: list[dict]) -> str:
    if not entries:
        return "(no confirmed earnings this week for your US watchlist tickers)"
    name_by_ticker = {q["ticker"]: q.get("name", q["ticker"]) for q in watchlist_quotes}
    hour_label = {"bmo": "before open", "amc": "after close"}
    lines = []
    for e in entries:
        name = name_by_ticker.get(e["symbol"], e["symbol"])
        hour = hour_label.get(e.get("hour"), "")
        hour_str = f" ({hour})" if hour else ""
        lines.append(f"- {name} ({e['symbol']}) reports {e.get('date') or 'TBD'}{hour_str}")
    return "\n".join(lines)


def build_week_ahead(
    last_close_us_indices: list[dict],
    last_close_kr_indices: list[dict],
    watchlist_quotes: list[dict],
    earnings: list[dict],
    today_news_en: list[dict],
    date_str: str,
) -> tuple[str, str]:
    """Returns (html_body, text_body). Market data here is naturally last
    Friday's close (the US session for "today" hasn't opened yet at 7 AM KST
    Monday) - explicitly labeled as such rather than presented as current.
    """
    prompt = ChatPromptTemplate.from_messages(
        [("system", WEEK_AHEAD_SYSTEM_PROMPT), ("human", WEEK_AHEAD_HUMAN_TEMPLATE)]
    )
    chain = prompt | get_chat_model("en") | StrOutputParser()
    commentary = chain.invoke(
        {
            "us_indices": format_index_quotes(last_close_us_indices),
            "kr_indices": format_index_quotes(last_close_kr_indices),
            "earnings": _earnings_text(earnings, watchlist_quotes),
            "today_news": format_news_text(today_news_en),
        }
    ).strip()

    body = f"""\
    <div class="note">Markets are closed over the weekend - the levels below are last
    Friday's close, not today's live prices.</div>

    <div class="sectionlabel">Where We Left Off — US</div>
    <div class="cards">{index_cards_html(last_close_us_indices)}</div>

    <div class="sectionlabel">Where We Left Off — Korea</div>
    <div class="cards">{index_cards_html(last_close_kr_indices)}</div>

    <div class="sectionlabel">Earnings This Week</div>
    {_earnings_html(earnings, watchlist_quotes)}

    <div class="sectionlabel">What to Watch</div>
    <p class="commentary">{html.escape(commentary) or "(no commentary)"}</p>

    <div class="sectionlabel">Today's Headlines</div>
    {news_items_html(today_news_en)}
    """
    html_body = render_email_shell(date_str, body, subtitle="Week Ahead")

    lines = [f"DailyMarketDigest — Week Ahead — {date_str}", ""]
    lines += ["(Levels below are last Friday's close, not today's live prices)", ""]
    lines += ["US INDICES (Friday close)", format_index_quotes(last_close_us_indices), ""]
    lines += ["KOREA INDICES (Friday close)", format_index_quotes(last_close_kr_indices), ""]
    lines += ["EARNINGS THIS WEEK", _earnings_text(earnings, watchlist_quotes), ""]
    lines += ["WHAT TO WATCH", commentary, ""]
    lines += ["TODAY'S HEADLINES", format_news_text(today_news_en)]
    lines += ["", "Sent by DailyMarketDigest · Data via yfinance, Finnhub, Naver API Hub"]
    text_body = "\n".join(lines)

    return html_body, text_body


if __name__ == "__main__":
    from datetime import date, timedelta

    from dotenv import load_dotenv

    load_dotenv()

    from src.earnings_calendar import fetch_upcoming_earnings
    from src.market_data import fetch_quotes

    us_indices = fetch_quotes(["^GSPC", "^IXIC"])
    kr_indices = fetch_quotes(["^KS11", "^KQ11"])
    watchlist = fetch_quotes(["AAPL", "005930.KS"])
    fake_news_en = [{"title": "Fed signals steady rates into next quarter", "source": "Reuters"}]

    print("=== WEEKLY SUMMARY (no last-week data) ===")
    html_body, text_body = build_weekly_summary(
        us_indices, kr_indices, watchlist, None, None, None, fake_news_en, [], "Sun, Aug 30"
    )
    print(text_body)

    print("\n=== WEEK AHEAD ===")
    earnings = fetch_upcoming_earnings(["AAPL"], date.today(), date.today() + timedelta(days=7))
    html_body, text_body = build_week_ahead(
        us_indices, kr_indices, watchlist, earnings, fake_news_en, "Mon, Aug 31"
    )
    print(text_body)
