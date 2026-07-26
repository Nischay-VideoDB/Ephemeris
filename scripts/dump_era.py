"""Dump `mission_meta` index records to a local lookup table.

The agent needs, for every retrieved moment, the date and mission attached to that
exact scene. Reading it back per query would mean a network round trip per video,
and `return_fields` hydration came back empty in testing, so the reliable source is
`index.records()`.

These are the rows VideoDB actually stored, paginated out of the live index, not a
local recomputation.

Writes data/era_lookup.json keyed by nasa_id.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import indexing  # noqa: E402
import manifest  # noqa: E402
import videodb_client as vc  # noqa: E402

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "era_lookup.json"

KEEP = (
    "era_start", "era_axis", "era_basis", "primary_mission", "published_year",
    "center", "title", "water_relevance", "nasa_id", "celestial_body", "event_type",
)


def main() -> None:
    coll = vc.get_collection()
    lookup: dict[str, list[dict]] = {}
    total = 0

    for nasa_id, entry in manifest.load().items():
        if not entry.get("video_id"):
            continue
        video = coll.get_video(entry["video_id"])
        try:
            index = video.get_index(name=indexing.MISSION_META)
        except Exception as exc:  # noqa: BLE001
            print(f"{nasa_id[:46]:46s} no mission_meta ({type(exc).__name__})")
            continue

        rows: list[dict] = []
        cursor = None
        while True:
            page = index.records(limit=200, cursor=cursor)
            for record in page.records:
                data = record.data or {}
                rows.append({
                    "start": float(record.start),
                    "end": float(record.end),
                    **{k: data.get(k) for k in KEEP},
                })
            cursor = page.next_cursor
            if not cursor:
                break

        rows.sort(key=lambda r: r["start"])
        lookup[nasa_id] = rows
        total += len(rows)
        eras = {r["era_start"] for r in rows if r.get("era_start")}
        print(f"{nasa_id[:46]:46s} {len(rows):4d} rows  eras={sorted(eras)[:6]}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(lookup, indent=2))
    print(f"\n{total} rows across {len(lookup)} clips -> {OUT_PATH}")


if __name__ == "__main__":
    main()
