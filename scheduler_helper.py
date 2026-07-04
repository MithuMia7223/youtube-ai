"""
scheduler_helper.py
Manages per-user auto-upload schedules using a simple JSON file.
"""
import json
import os
from datetime import datetime

SCHEDULE_FILE = "schedules.json"


def _load() -> dict:
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save(data: dict):
    with open(SCHEDULE_FILE, 'w') as f:
        json.dump(data, f, indent=2, default=str)


def set_schedule(chat_id: int, hour: int, minute: int, niche: str, voice: str, is_short: bool = False):
    """Create or update the schedule for a user."""
    data = _load()
    key = str(chat_id)
    existing = data.get(key, {})
    data[key] = {
        "chat_id": chat_id,
        "hour": hour,
        "minute": minute,
        "niche": niche,
        "voice": voice,
        "is_short": is_short,
        "enabled": True,
        "videos_created": existing.get("videos_created", 0),
        "last_run": existing.get("last_run", None),
        "created_at": existing.get("created_at", datetime.now().isoformat()),
    }
    _save(data)


def remove_schedule(chat_id: int) -> bool:
    """Remove a user's schedule. Returns True if it existed."""
    data = _load()
    key = str(chat_id)
    if key in data:
        del data[key]
        _save(data)
        return True
    return False


def get_schedule(chat_id: int) -> dict | None:
    """Return the schedule dict for a user, or None."""
    data = _load()
    return data.get(str(chat_id))


def get_all_schedules() -> list[dict]:
    """Return all schedules as a list."""
    data = _load()
    return list(data.values())


def get_due_schedules() -> list[dict]:
    """Return schedules that are due to run right now (within the current minute)."""
    now = datetime.now()
    due = []
    for sched in get_all_schedules():
        if not sched.get("enabled"):
            continue
        if sched["hour"] == now.hour and sched["minute"] == now.minute:
            last_run = sched.get("last_run")
            if last_run:
                last_dt = datetime.fromisoformat(last_run)
                # Only run once per minute
                if (now - last_dt).total_seconds() < 60:
                    continue
            due.append(sched)
    return due


def mark_run(chat_id: int):
    """Mark a schedule as having just run, and increment counter."""
    data = _load()
    key = str(chat_id)
    if key in data:
        data[key]["last_run"] = datetime.now().isoformat()
        data[key]["videos_created"] = data[key].get("videos_created", 0) + 1
        _save(data)
