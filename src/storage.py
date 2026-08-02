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
    path = _path_for(day - timedelta(days=1))
    if not path.exists():
        return None
    return json.loads(path.read_text())


if __name__ == "__main__":
    save_today({"example": "data"})
    print("saved today's snapshot")
    print("yesterday's snapshot:", load_yesterday())
