"""Summarise the corpus per celestial body, for the interface's body inspector.

Every number here comes from the `mission_meta` index on the server, through `aggregate()`
and `query()`, rather than from a local scan of the manifest. That is the point: clicking
Saturn in the scene should report what VideoDB actually holds, and the same call that answers
the panel is the one the agent uses to filter and count.

Writes web/public/corpus/bodies.json.

    python scripts/dump_bodies.py
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import indexing  # noqa: E402
import manifest  # noqa: E402
import videodb_client as vc  # noqa: E402

OUT_PATH = ROOT / "web" / "public" / "corpus" / "bodies.json"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def rows_for(coll, body: str) -> list[dict]:
    """Every mission_meta record for one body. `query()` is exhaustive rather than ranked,
    which is what makes it the right call for counting."""
    response = coll.query(
        index_name=indexing.MISSION_META,
        filter=[{"field": "celestial_body", "op": "==", "value": body}],
        limit=2000,
    )
    out: list[dict] = []
    for shot in response.shots:
        # Custom-record indexes surface their fields on `shot.metadata`, not `shot.data`.
        # `shot.text` is None here: these rows carry structure, not prose.
        data = getattr(shot, "metadata", None) or {}
        out.append({
            "video_id": getattr(shot, "video_id", None),
            "start": float(getattr(shot, "start", 0) or 0),
            "end": float(getattr(shot, "end", 0) or 0),
            "era_start": data.get("era_start"),
            "mission": data.get("primary_mission"),
            "event_type": data.get("event_type"),
            "nasa_id": data.get("nasa_id"),
        })
    return out


def main() -> None:
    coll = vc.get_collection()
    entries = manifest.load()
    by_video = {e["video_id"]: (nid, e) for nid, e in entries.items() if e.get("video_id")}

    # One aggregate call gives the shape of the whole corpus; the per-body detail then only
    # has to be fetched for bodies that actually have scenes.
    counts = coll.aggregate(
        index_name=indexing.MISSION_META, group_by="celestial_body", metric="count"
    )
    # Observed shape: a bare list of {"<group_by field>": value, "value": count}. The count
    # lives under "value", which collides with the intuition that "value" is the group key.
    buckets: dict[str, int] = {}
    for row in counts if isinstance(counts, list) else counts.get("results", []):
        key = row.get("celestial_body")
        if key is None:
            continue
        buckets[str(key)] = int(row.get("value") or 0)
    log(f"aggregate: {buckets}")

    bodies: dict[str, dict] = {}
    for body, scene_count in sorted(buckets.items(), key=lambda kv: -kv[1]):
        if not body or body == "None":
            continue
        rows = rows_for(coll, body)
        clips = {r["nasa_id"] or by_video.get(r["video_id"], (None, {}))[0] for r in rows}
        clips.discard(None)

        seconds = sum(max(0.0, r["end"] - r["start"]) for r in rows)
        years = [int(r["era_start"]) for r in rows if r.get("era_start")]
        missions = Counter(r["mission"] for r in rows if r.get("mission") and r["mission"] != "unknown")
        events = Counter(r["event_type"] for r in rows if r.get("event_type"))

        bodies[body] = {
            "scenes": scene_count or len(rows),
            "clips": len(clips),
            "minutes": round(seconds / 60, 1),
            "era_range": [min(years), max(years)] if years else None,
            "missions": [m for m, _ in missions.most_common(10)],
            "events": dict(events.most_common()),
        }
        log(f"{body:16s} scenes={bodies[body]['scenes']:4d} clips={bodies[body]['clips']:3d} "
            f"era={bodies[body]['era_range']} missions={bodies[body]['missions'][:4]}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "bodies": bodies,
    }, indent=2))
    log(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
