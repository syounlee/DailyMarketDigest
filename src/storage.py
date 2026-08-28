import json
from datetime import date, timedelta
from pathlib import Path

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"


def _path_for(day: date) -> Path:
    return SNAPSHOT_DIR / f"{day.isoformat()}.json"


def save_today(data: dict, day: date | None = None) -> None:
    day = day or date.today()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    _path_for(day).write_text(json.dumps(data, indent=2, default=str))


def load_yesterday(day: date | None = None) -> dict | None:
    day = day or date.today()
    return load_snapshot(day - timedelta(days=1))


def load_snapshot(target_date: date) -> dict | None:
    """Load the snapshot saved for any given date, or None if it doesn't exist."""
    path = _path_for(target_date)
    if not path.exists():
        return None
    return json.loads(path.read_text())


if __name__ == "__main__":
    # Read-only self-test - never writes to today's real snapshot file, so
    # running this can't clobber production data from the actual daily run.
    test_day = date(1999, 1, 1)
    save_today({"example": "data"}, day=test_day)
    print("saved test snapshot for", test_day)
    print("loaded back:", load_snapshot(test_day))
    print("yesterday's real snapshot:", load_yesterday())
    _path_for(test_day).unlink()
    print("cleaned up test snapshot")
