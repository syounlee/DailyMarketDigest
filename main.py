import logging
from datetime import date, timedelta
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.config_utils import tickers
from src.earnings_calendar import fetch_upcoming_earnings
from src.email_sender import send_email
from src.market_data import fetch_quotes
from src.news_data import fetch_all as fetch_news_en
from src.news_data_kr import fetch_all_kr as fetch_news_kr
from src.storage import load_snapshot, load_yesterday, save_today
from src.synthesize import build_digest, translate_kr_news
from src.weekly import build_week_ahead, build_weekly_summary

BASE_DIR = Path(__file__).resolve().parent

# Logs to stderr only - run.sh redirects stdout/stderr to data/digest.log for
# scheduled runs, so a separate FileHandler here would double-write every line.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("daily_digest")


def load_config() -> dict:
    with open(BASE_DIR / "config" / "watchlist.yaml") as f:
        return yaml.safe_load(f)


def safe_fetch(step_name: str, fn, *args, default=None, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        log.exception("Step %r failed, continuing with fallback value", step_name)
        return default


def _aggregate_week_news(days: list[date]) -> tuple[list[dict], list[dict]]:
    """Pulls news_en/news_kr out of each day's saved snapshot and dedupes by
    URL - used to build "this week's headlines" for the Sunday recap. Raw
    Korean headlines (untranslated) are returned; caller translates once.
    """
    seen_en, seen_kr = set(), set()
    news_en, news_kr_raw = [], []
    for d in days:
        snap = load_snapshot(d)
        if not snap:
            continue
        for item in snap.get("news_en", []):
            if item.get("url") not in seen_en:
                seen_en.add(item.get("url"))
                news_en.append(item)
        for item in snap.get("news_kr", []):
            if item.get("url") not in seen_kr:
                seen_kr.add(item.get("url"))
                news_kr_raw.append(item)
    return news_en[:8], news_kr_raw[:8]


def _run_daily(config: dict) -> None:
    """Tue-Sat: the regular daily digest."""
    watchlist_us = tickers(config["watchlist_us"])
    watchlist_kr = tickers(config["watchlist_kr"])

    us_indices = safe_fetch("market_data.us_indices", fetch_quotes, config["indices_us"], default=[])
    kr_indices = safe_fetch("market_data.kr_indices", fetch_quotes, config["indices_kr"], default=[])
    watchlist_quotes = safe_fetch(
        "market_data.watchlist",
        fetch_quotes,
        watchlist_us + watchlist_kr,
        default=[],
    )

    news_en = safe_fetch(
        "news_data.en",
        fetch_news_en,
        watchlist_us,
        config["news_categories_en"],
        default=[],
    )
    news_kr = safe_fetch(
        "news_data.kr",
        fetch_news_kr,
        config["news_keywords_kr"],
        default=[],
    )

    previous_snapshot = load_yesterday()

    html_digest, text_digest = build_digest(
        us_indices, kr_indices, watchlist_quotes, news_en, news_kr, previous_snapshot
    )

    subject = f"Daily Market Digest - {date.today().isoformat()}"
    send_email(subject=subject, html_body=html_digest, text_body=text_digest)
    log.info("Digest email sent.")

    save_today(
        {
            "us_indices": us_indices,
            "kr_indices": kr_indices,
            "watchlist_quotes": watchlist_quotes,
            "news_en": news_en,
            "news_kr": news_kr,
        }
    )
    log.info("Snapshot saved.")


def _run_weekly_summary(config: dict) -> None:
    """Sunday: how the week went, instead of a duplicate of Saturday's digest."""
    today = date.today()

    this_week_snapshot = load_snapshot(today - timedelta(days=1)) or load_snapshot(
        today - timedelta(days=2)
    )
    if this_week_snapshot:
        this_week_us = this_week_snapshot.get("us_indices", [])
        this_week_kr = this_week_snapshot.get("kr_indices", [])
        this_week_watchlist = this_week_snapshot.get("watchlist_quotes", [])
    else:
        log.warning("No saved snapshot for this week's close - falling back to a live fetch")
        this_week_us = safe_fetch("weekly.us_indices", fetch_quotes, config["indices_us"], default=[])
        this_week_kr = safe_fetch("weekly.kr_indices", fetch_quotes, config["indices_kr"], default=[])
        this_week_watchlist = safe_fetch(
            "weekly.watchlist",
            fetch_quotes,
            tickers(config["watchlist_us"]) + tickers(config["watchlist_kr"]),
            default=[],
        )

    last_week_snapshot = load_snapshot(today - timedelta(days=8)) or load_snapshot(
        today - timedelta(days=9)
    )
    last_week_us = last_week_snapshot.get("us_indices") if last_week_snapshot else None
    last_week_kr = last_week_snapshot.get("kr_indices") if last_week_snapshot else None
    last_week_watchlist = last_week_snapshot.get("watchlist_quotes") if last_week_snapshot else None

    week_days = [today - timedelta(days=n) for n in range(2, 7)]  # this week's Mon-Fri
    week_news_en, week_news_kr_raw = _aggregate_week_news(week_days)
    week_news_kr_translated = safe_fetch(
        "weekly.translate_kr", translate_kr_news, week_news_kr_raw, default=[]
    )

    html_digest, text_digest = build_weekly_summary(
        this_week_us,
        this_week_kr,
        this_week_watchlist,
        last_week_us,
        last_week_kr,
        last_week_watchlist,
        week_news_en,
        week_news_kr_translated,
        today.strftime("%A, %B %-d, %Y"),
    )

    subject = f"Weekly Market Recap - {today.isoformat()}"
    send_email(subject=subject, html_body=html_digest, text_body=text_digest)
    log.info("Weekly recap email sent.")

    save_today(
        {
            "us_indices": this_week_us,
            "kr_indices": this_week_kr,
            "watchlist_quotes": this_week_watchlist,
            "news_en": week_news_en,
            "news_kr": week_news_kr_raw,
        }
    )
    log.info("Snapshot saved.")


def _run_week_ahead(config: dict) -> None:
    """Monday: what's confirmed for this week, instead of Friday's stale close
    presented as if current (the US session for "today" hasn't opened yet at
    7 AM KST).
    """
    today = date.today()
    watchlist_us = tickers(config["watchlist_us"])
    watchlist_kr = tickers(config["watchlist_kr"])

    us_indices = safe_fetch("week_ahead.us_indices", fetch_quotes, config["indices_us"], default=[])
    kr_indices = safe_fetch("week_ahead.kr_indices", fetch_quotes, config["indices_kr"], default=[])
    watchlist_quotes = safe_fetch(
        "week_ahead.watchlist",
        fetch_quotes,
        watchlist_us + watchlist_kr,
        default=[],
    )

    news_en = safe_fetch(
        "week_ahead.news_en",
        fetch_news_en,
        watchlist_us,
        config["news_categories_en"],
        default=[],
    )

    earnings = safe_fetch(
        "week_ahead.earnings",
        fetch_upcoming_earnings,
        watchlist_us,
        today,
        today + timedelta(days=4),  # through Friday
        default=[],
    )

    html_digest, text_digest = build_week_ahead(
        us_indices, kr_indices, watchlist_quotes, earnings, news_en,
        today.strftime("%A, %B %-d, %Y"),
    )

    subject = f"Week Ahead - {today.isoformat()}"
    send_email(subject=subject, html_body=html_digest, text_body=text_digest)
    log.info("Week-ahead email sent.")

    save_today(
        {
            "us_indices": us_indices,
            "kr_indices": kr_indices,
            "watchlist_quotes": watchlist_quotes,
            "news_en": news_en,
            "news_kr": [],
        }
    )
    log.info("Snapshot saved.")


def main() -> None:
    load_dotenv()
    today = date.today()
    log.info("Starting run for %s", today.isoformat())

    config = load_config()

    weekday = today.weekday()  # Monday=0 ... Sunday=6
    if weekday == 6:
        _run_weekly_summary(config)
    elif weekday == 0:
        _run_week_ahead(config)
    else:
        _run_daily(config)


if __name__ == "__main__":
    main()
