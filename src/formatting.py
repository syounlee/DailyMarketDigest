"""Shared, pure-Python formatting helpers for building digest emails.

No LLM calls here - these just turn fetched data (quotes, news) into plain text
or HTML. Kept separate from synthesize.py/weekly.py so the daily, weekly-recap,
and week-ahead pipelines all render numbers identically (in particular: indices
are point values with no currency symbol, stocks/ETFs are priced in their
actual currency - see fmt_index_value vs fmt_stock_price).
"""

import html


def format_stock_quotes(quotes: list[dict]) -> str:
    """Plain-text quote lines for actual stocks/ETFs (priced in a currency)."""
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


def format_index_quotes(quotes: list[dict]) -> str:
    """Plain-text quote lines for indices - point values, not a currency amount."""
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


def format_news_text(articles: list[dict]) -> str:
    """Compact form fed to the LLM as prompt context - no URLs here, they're
    just noise for a model reasoning about content, not clickable anyway.
    """
    if not articles:
        return "(none)"
    lines = []
    for a in articles:
        extra = f" - {a['description']}" if a.get("description") else ""
        lines.append(f"- {a['title']}{extra} ({a.get('source', a.get('url', ''))})")
    return "\n".join(lines)


def format_news_text_with_links(articles: list[dict]) -> str:
    """Full form for the plain-text email body - includes the URL so links
    are still usable (as text) in non-HTML mail clients.
    """
    if not articles:
        return "(none)"
    lines = []
    for a in articles:
        src = a.get("source") or ""
        url = a.get("url") or ""
        tail = " ".join(p for p in (f"({src})" if src else "", url) if p)
        lines.append(f"- {a['title']} {tail}".rstrip())
    return "\n".join(lines)


def fmt_stock_price(price, currency) -> str:
    if price is None:
        return "n/a"
    if currency == "KRW":
        return f"₩{price:,.0f}"
    return f"${price:,.2f}"


def fmt_index_value(price) -> str:
    """Indices are point values, not a currency amount - no $ / ₩ prefix."""
    return f"{price:,.2f}" if price is not None else "n/a"


def chip_html(pct) -> str:
    if pct is None:
        return '<span class="chip">n/a</span>'
    cls = "up" if pct >= 0 else "down"
    arrow = "▲" if pct >= 0 else "▼"
    return f'<span class="chip {cls}">{arrow} {abs(pct):.2f}%</span>'


def index_cards_html(quotes: list[dict]) -> str:
    cards = []
    for q in quotes:
        name = html.escape(str(q.get("name", q.get("ticker", ""))))
        price = html.escape(fmt_index_value(q.get("price")))
        cards.append(
            f'<div class="card"><div class="name">{name}</div>'
            f'<div class="price">{price}</div>{chip_html(q.get("pct_change"))}</div>'
        )
    return "".join(cards) or '<div class="card"><div class="name">(no data)</div></div>'


def watchlist_rows_html(quotes: list[dict]) -> str:
    rows = []
    for q in quotes:
        name = html.escape(str(q.get("name", "")))
        ticker = html.escape(str(q.get("ticker", "")))
        price = html.escape(fmt_stock_price(q.get("price"), q.get("currency")))
        rows.append(
            f"<tr><td>{name} ({ticker})</td><td class='num'>{price}</td>"
            f"<td class='num'>{chip_html(q.get('pct_change'))}</td></tr>"
        )
    return "".join(rows) or "<tr><td>(no watchlist data)</td></tr>"


def news_items_html(items: list[dict]) -> str:
    if not items:
        return '<div class="newsitem">No headlines.</div>'
    out = []
    for a in items:
        title = html.escape(str(a.get("title", "")))
        url = a.get("url") or ""
        title_html = (
            f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{title}</a>'
            if url
            else title
        )
        src = html.escape(str(a.get("source") or url))
        out.append(f'<div class="newsitem">{title_html}<span class="src">{src}</span></div>')
    return "".join(out)


def takeaways_html(takeaways: list[str]) -> str:
    """Renders the LLM-synthesized "Key Takeaways" bullets, if any. Returns ""
    (no section at all) when there's nothing beyond what the commentary
    paragraphs already cover - an empty section would just be noise.
    """
    if not takeaways:
        return ""
    items = "".join(f'<div class="newsitem">{html.escape(t)}</div>' for t in takeaways)
    return f'<div class="sectionlabel">Key Takeaways</div>{items}'


def takeaways_text(takeaways: list[str]) -> str:
    if not takeaways:
        return ""
    lines = ["KEY TAKEAWAYS"] + [f"- {t}" for t in takeaways]
    return "\n".join(lines) + "\n"


def _fmt_signed_amount(amount, currency) -> str:
    sign = "+" if amount >= 0 else "-"
    return f"{sign}{fmt_stock_price(abs(amount), currency)}"


def portfolio_status_html(status: dict) -> str:
    """Renders per-currency portfolio totals (KR holdings in KRW, US holdings
    in USD, kept separate rather than added together) as cards, same visual
    language as the index cards. Returns "" (no section) if status is empty.
    """
    if not status:
        return ""
    cards = []
    for currency, s in status.items():
        value_str = html.escape(fmt_stock_price(s["value"], currency))
        sub = ""
        if s.get("cost") is not None and s.get("gain_loss") is not None:
            cost_str = html.escape(fmt_stock_price(s["cost"], currency))
            gl_str = html.escape(_fmt_signed_amount(s["gain_loss"], currency))
            sub = f'<div class="subtext">cost {cost_str} &middot; {gl_str}</div>'
        cards.append(
            f'<div class="card"><div class="name">Total Value ({currency})</div>'
            f'<div class="price">{value_str}</div>{chip_html(s.get("gain_loss_pct"))}{sub}</div>'
        )
    return f'<div class="sectionlabel">Portfolio Status</div><div class="cards">{"".join(cards)}</div>'


def portfolio_status_text(status: dict) -> str:
    if not status:
        return ""
    lines = ["PORTFOLIO STATUS"]
    for currency, s in status.items():
        value_str = fmt_stock_price(s["value"], currency)
        if s.get("cost") is not None and s.get("gain_loss") is not None:
            cost_str = fmt_stock_price(s["cost"], currency)
            gl_str = _fmt_signed_amount(s["gain_loss"], currency)
            lines.append(
                f"- Total ({currency}): {value_str} "
                f"(cost {cost_str}, {gl_str} / {s['gain_loss_pct']:+.2f}%)"
            )
        else:
            lines.append(f"- Total ({currency}): {value_str} (cost basis unknown)")
    return "\n".join(lines) + "\n"


BASE_CSS = """\
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: #F5F6F8;
    color: #1D2229;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
  }
  .em-dash { max-width: 640px; margin: 0 auto; padding: 24px 22px 30px; }
  .head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 18px; }
  .brand { font-weight: 800; font-size: 15px; letter-spacing: -0.01em; }
  .brand .dot { color: #4C5FD5; }
  .brand .sub { color: #6B7280; font-weight: 600; }
  .date { font-size: 12px; color: #6B7280; }
  .sectionlabel {
    font-size: 11px; font-weight: 700; letter-spacing: 0.06em; color: #6B7280;
    text-transform: uppercase; margin: 22px 0 10px;
  }
  .cards { display: flex; gap: 8px; flex-wrap: wrap; }
  .card {
    background: #FFFFFF; border: 1px solid #E4E6EA; border-radius: 10px;
    padding: 10px 12px; flex: 1 1 140px; min-width: 140px;
  }
  .card .name { font-size: 11.5px; color: #6B7280; margin-bottom: 4px; }
  .card .price { font-size: 15px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .card .subtext { font-size: 10.5px; color: #9199A3; margin-top: 4px; font-variant-numeric: tabular-nums; }
  .chip {
    display: inline-block; margin-top: 5px; padding: 2px 7px; border-radius: 100px;
    font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums;
  }
  .chip.up { color: #16803C; background: #E4F5EA; }
  .chip.down { color: #C22E2E; background: #FBE7E7; }
  table {
    width: 100%; border-collapse: collapse; background: #FFFFFF;
    border: 1px solid #E4E6EA; border-radius: 10px; overflow: hidden;
  }
  table td { padding: 10px 12px; font-size: 13px; border-bottom: 1px solid #EEF0F2; }
  table tr:last-child td { border-bottom: none; }
  table td.num { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
  p.commentary { font-size: 13px; color: #4B5158; margin: 10px 2px 0; line-height: 1.6; }
  .newsitem {
    background: #FFFFFF; border: 1px solid #E4E6EA; border-radius: 10px;
    padding: 10px 12px; margin-bottom: 6px; font-size: 12.5px;
  }
  .newsitem a { color: #4C5FD5; text-decoration: none; }
  .newsitem a:hover { text-decoration: underline; }
  .newsitem .src { display: block; color: #9199A3; font-size: 11px; margin-top: 3px; }
  .note {
    background: #FFF8E9; border: 1px solid #F0DFAE; border-radius: 10px;
    padding: 10px 12px; font-size: 12.5px; color: #6B5B2A; margin-bottom: 10px;
  }
  .foot { margin-top: 22px; color: #9199A3; font-size: 11px; text-align: center; }
"""


def render_email_shell(date_str: str, body_html: str, subtitle: str = "") -> str:
    """Wraps section content in the shared Dashboard-style shell (header + CSS).

    `subtitle` distinguishes the daily digest ("") from the weekly variants
    ("Weekly Recap", "Week Ahead") while keeping the same visual identity.
    """
    brand = 'DailyMarket<span class="dot">Digest</span>'
    if subtitle:
        brand += f' <span class="sub">&middot; {html.escape(subtitle)}</span>'

    return f"""\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
{BASE_CSS}
</style>
</head>
<body>
  <div class="em-dash">
    <div class="head">
      <span class="brand">{brand}</span>
      <span class="date">{html.escape(date_str)}</span>
    </div>
    {body_html}
    <div class="foot">Sent by DailyMarketDigest &middot; Data via yfinance, Finnhub, Naver API Hub</div>
  </div>
</body>
</html>
"""
