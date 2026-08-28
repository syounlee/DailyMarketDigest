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


def load_people() -> list[dict]:
    with open(BASE_DIR / "config" / "people.yaml") as f:
        return yaml.safe_load(f)["people"]


def safe_fetch(step_name: str, fn, *args, default=None, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        log.exception("Step %r failed, continuing with fallback value", step_name)
        return default


def _aggregate_week_news_kr(days: list[date]) -> list[dict]:
    """Shared (not per-person) - general Korean market news isn't ticker-specific."""
    seen = set()
    out = []
    for d in days:
        snap = load_snapshot(d)
        if not snap:
            continue
        for item in snap.get("news_kr", []):
            if item.get("url") not in seen:
                seen.add(item.get("url"))
                out.append(item)
    return out[:8]


def _aggregate_week_news_en(days: list[date], person_id: str) -> list[dict]:
    """Per-person - news_en is ticker-driven (company news for that person's
    US holdings + shared general categories), so it lives under people.<id>.
    """
    seen = set()
    out = []
    for d in days:
        snap = load_snapshot(d)
        if not snap:
            continue
        person_snap = snap.get("people", {}).get(person_id, {})
        for item in person_snap.get("news_en", []):
            if item.get("url") not in seen:
                seen.add(item.get("url"))
                out.append(item)
    return out[:8]


def _run_daily(config: dict, people: list[dict]) -> None:
    """Tue-Sat: the regular daily digest, personalized per person. Market
    overview (indices, Korean general news) is shared; each person gets their
    own Watchlist section and ticker-specific news in their own email.
    """
    us_indices = safe_fetch("market_data.us_indices", fetch_quotes, config["indices_us"], default=[])
    kr_indices = safe_fetch("market_data.kr_indices", fetch_quotes, config["indices_kr"], default=[])
    news_kr = safe_fetch("news_data.kr", fetch_news_kr, config["news_keywords_kr"], default=[])

    previous_snapshot = load_yesterday()
    people_snapshot = {}

    for person in people:
        watchlist_us = tickers(person["watchlist_us"])
        watchlist_kr = tickers(person["watchlist_kr"])

        watchlist_quotes = safe_fetch(
            f"market_data.watchlist.{person['id']}",
            fetch_quotes,
            watchlist_us + watchlist_kr,
            default=[],
        )
        news_en = safe_fetch(
            f"news_data.en.{person['id']}",
            fetch_news_en,
            watchlist_us,
            config["news_categories_en"],
            default=[],
        )

        person_previous = None
        if previous_snapshot:
            prev_person = previous_snapshot.get("people", {}).get(person["id"], {})
            person_previous = {
                "us_indices": previous_snapshot.get("us_indices", []),
                "kr_indices": previous_snapshot.get("kr_indices", []),
                "watchlist_quotes": prev_person.get("watchlist_quotes", []),
            }

        html_digest, text_digest = build_digest(
            us_indices, kr_indices, watchlist_quotes, news_en, news_kr, person_previous
        )

        subject = f"Daily Market Digest - {date.today().isoformat()}"
        send_email(
            subject=subject, html_body=html_digest, text_body=text_digest, recipient=person["email"]
        )
        log.info("Digest email sent to %s.", person["id"])

        people_snapshot[person["id"]] = {"watchlist_quotes": watchlist_quotes, "news_en": news_en}

    save_today(
        {
            "us_indices": us_indices,
            "kr_indices": kr_indices,
            "news_kr": news_kr,
            "people": people_snapshot,
        }
    )
    log.info("Snapshot saved.")


def _run_weekly_summary(config: dict, people: list[dict]) -> None:
    """Sunday: how the week went, instead of a duplicate of Saturday's digest."""
    today = date.today()

    this_week_snapshot = load_snapshot(today - timedelta(days=1)) or load_snapshot(
        today - timedelta(days=2)
    )
    if this_week_snapshot:
        this_week_us = this_week_snapshot.get("us_indices", [])
        this_week_kr = this_week_snapshot.get("kr_indices", [])
    else:
        log.warning("No saved snapshot for this week's close - falling back to a live fetch")
        this_week_us = safe_fetch("weekly.us_indices", fetch_quotes, config["indices_us"], default=[])
        this_week_kr = safe_fetch("weekly.kr_indices", fetch_quotes, config["indices_kr"], default=[])

    last_week_snapshot = load_snapshot(today - timedelta(days=8)) or load_snapshot(
        today - timedelta(days=9)
    )
    last_week_us = last_week_snapshot.get("us_indices") if last_week_snapshot else None
    last_week_kr = last_week_snapshot.get("kr_indices") if last_week_snapshot else None

    week_days = [today - timedelta(days=n) for n in range(2, 7)]  # this week's Mon-Fri
    week_news_kr_raw = _aggregate_week_news_kr(week_days)
    week_news_kr_translated = safe_fetch(
        "weekly.translate_kr", translate_kr_news, week_news_kr_raw, default=[]
    )

    people_snapshot = {}

    for person in people:
        this_week_watchlist = None
        if this_week_snapshot:
            this_week_watchlist = (
                this_week_snapshot.get("people", {}).get(person["id"], {}).get("watchlist_quotes")
            )
        if not this_week_watchlist:
            this_week_watchlist = safe_fetch(
                f"weekly.watchlist.{person['id']}",
                fetch_quotes,
                tickers(person["watchlist_us"]) + tickers(person["watchlist_kr"]),
                default=[],
            )

        last_week_watchlist = None
        if last_week_snapshot:
            last_week_watchlist = (
                last_week_snapshot.get("people", {}).get(person["id"], {}).get("watchlist_quotes")
            )

        week_news_en = _aggregate_week_news_en(week_days, person["id"])

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
        send_email(
            subject=subject, html_body=html_digest, text_body=text_digest, recipient=person["email"]
        )
        log.info("Weekly recap email sent to %s.", person["id"])

        people_snapshot[person["id"]] = {
            "watchlist_quotes": this_week_watchlist,
            "news_en": week_news_en,
        }

    save_today(
        {
            "us_indices": this_week_us,
            "kr_indices": this_week_kr,
            "news_kr": week_news_kr_raw,
            "people": people_snapshot,
        }
    )
    log.info("Snapshot saved.")


def _run_week_ahead(config: dict, people: list[dict]) -> None:
    """Monday: what's confirmed for this week, instead of Friday's stale close
    presented as if current (the US session for "today" hasn't opened yet at
    7 AM KST).
    """
    today = date.today()

    us_indices = safe_fetch("week_ahead.us_indices", fetch_quotes, config["indices_us"], default=[])
    kr_indices = safe_fetch("week_ahead.kr_indices", fetch_quotes, config["indices_kr"], default=[])

    people_snapshot = {}

    for person in people:
        watchlist_us = tickers(person["watchlist_us"])
        watchlist_kr = tickers(person["watchlist_kr"])

        watchlist_quotes = safe_fetch(
            f"week_ahead.watchlist.{person['id']}",
            fetch_quotes,
            watchlist_us + watchlist_kr,
            default=[],
        )
        news_en = safe_fetch(
            f"week_ahead.news_en.{person['id']}",
            fetch_news_en,
            watchlist_us,
            config["news_categories_en"],
            default=[],
        )
        earnings = safe_fetch(
            f"week_ahead.earnings.{person['id']}",
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
        send_email(
            subject=subject, html_body=html_digest, text_body=text_digest, recipient=person["email"]
        )
        log.info("Week-ahead email sent to %s.", person["id"])

        people_snapshot[person["id"]] = {"watchlist_quotes": watchlist_quotes, "news_en": news_en}

    save_today(
        {
            "us_indices": us_indices,
            "kr_indices": kr_indices,
            "news_kr": [],
            "people": people_snapshot,
        }
    )
    log.info("Snapshot saved.")


def main() -> None:
    load_dotenv()
    today = date.today()
    log.info("Starting run for %s", today.isoformat())

    config = load_config()
    people = load_people()

    weekday = today.weekday()  # Monday=0 ... Sunday=6
    if weekday == 6:
        _run_weekly_summary(config, people)
    elif weekday == 0:
        _run_week_ahead(config, people)
    else:
        _run_daily(config, people)


if __name__ == "__main__":
    main()
