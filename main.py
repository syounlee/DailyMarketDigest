import logging
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

from src.email_sender import send_email
from src.market_data import fetch_quotes
from src.news_data import fetch_all as fetch_news_en
from src.news_data_kr import fetch_all_kr as fetch_news_kr
from src.storage import load_yesterday, save_today
from src.synthesize import build_digest

BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "data" / "agent.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()],
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


def main() -> None:
    load_dotenv()
    log.info("Starting daily digest run for %s", date.today().isoformat())

    config = load_config()

    us_indices = safe_fetch("market_data.us_indices", fetch_quotes, config["indices_us"], default=[])
    kr_indices = safe_fetch("market_data.kr_indices", fetch_quotes, config["indices_kr"], default=[])
    watchlist_quotes = safe_fetch(
        "market_data.watchlist",
        fetch_quotes,
        config["watchlist_us"] + config["watchlist_kr"],
        default=[],
    )

    news_en = safe_fetch(
        "news_data.en",
        fetch_news_en,
        config["watchlist_us"],
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

    digest = build_digest(
        us_indices, kr_indices, watchlist_quotes, news_en, news_kr, previous_snapshot
    )

    subject = f"Daily Market Digest - {date.today().isoformat()}"
    send_email(subject=subject, body_text=digest)
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


if __name__ == "__main__":
    main()
