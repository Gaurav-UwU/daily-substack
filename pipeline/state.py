"""Persistent memory so the agent never repeats itself across days."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from . import config


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def load_history() -> list[dict]:
    if config.HISTORY_FILE.exists():
        try:
            return json.loads(config.HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def recent_titles(history: list[dict] | None = None) -> list[str]:
    history = history if history is not None else load_history()
    return [h.get("title", "") for h in history[-config.HISTORY_DEDUPE_WINDOW :]]


def is_dup(title: str, history: list[dict]) -> bool:
    k = _key(title)
    if not k:
        return False
    seen = {_key(h.get("title", "")) for h in history}
    seen |= {_key(h.get("topic", "")) for h in history}
    return k in seen


def append_history(*, title: str, topic: str, urls: list[str], published: bool) -> None:
    history = load_history()
    history.append({
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "title": title,
        "topic": topic,
        "urls": urls,
        "published": published,
    })
    config.HISTORY_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8"
    )
