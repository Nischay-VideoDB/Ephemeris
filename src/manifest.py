"""Local record of what has been uploaded and processed.

VideoDB is the source of truth for media and indexes; this file is the source of
truth for the NASA metadata attached to each video, which VideoDB never sees
until it is written into the `mission_meta` index.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "manifest.json"


def load() -> dict[str, dict]:
    if not MANIFEST_PATH.exists():
        return {}
    return json.loads(MANIFEST_PATH.read_text())


def save(entries: dict[str, dict]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(entries, indent=2, sort_keys=True))


def put(nasa_id: str, **fields: Any) -> dict[str, dict]:
    entries = load()
    entries.setdefault(nasa_id, {})
    entries[nasa_id].update(fields)
    save(entries)
    return entries


def by_video_id() -> dict[str, dict]:
    return {e["video_id"]: {**e, "nasa_id": nid} for nid, e in load().items() if e.get("video_id")}


def video_ids() -> list[str]:
    return [e["video_id"] for e in load().values() if e.get("video_id")]
