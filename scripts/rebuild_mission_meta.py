"""Rebuild only the `mission_meta` index, across the whole collection.

An index name is a schema contract for the entire collection, not per video. Adding a
field to the records therefore fails on every video that still carries an older index
under the same name, and dropping it on one video is not enough. So this drops the name
everywhere first, then rebuilds from the existing understanding artifacts.

No model inference happens here. Understanding runs are reused, so this is cheap: it
only rewrites retrieval structures.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import indexing  # noqa: E402
import manifest  # noqa: E402
import mission_meta as mm  # noqa: E402
import understanding as und  # noqa: E402
import videodb_client as vc  # noqa: E402


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> None:
    coll = vc.get_collection()
    entries = {k: v for k, v in manifest.load().items()
               if v.get("video_id") and v.get("understanding_id")}

    log(f"dropping {indexing.MISSION_META} across {len(entries)} videos")
    dropped = 0
    for nasa_id, entry in entries.items():
        video = coll.get_video(entry["video_id"])
        for index in video.list_indexes():
            if index.name == indexing.MISSION_META:
                index.delete()
                dropped += 1
    log(f"dropped {dropped}")

    built = []
    bodies: dict[str, int] = {}
    for nasa_id, entry in entries.items():
        video = coll.get_video(entry["video_id"])
        understanding = video.get_understanding(entry["understanding_id"])
        scene = und.successful(understanding.refresh().list_analyzers()).get("scene")
        if scene is None:
            log(f"{nasa_id[:44]:44s} no scene analyzer, skipped")
            continue

        records = mm.build_records(und.scenes_of(scene), {**entry, "nasa_id": nasa_id})
        if not records:
            log(f"{nasa_id[:44]:44s} no records, skipped")
            continue

        summary = mm.summarize(records)
        for body, count in (summary.get("body_counts") or {}).items():
            bodies[body] = bodies.get(body, 0) + count

        try:
            index = indexing.build_mission_meta_index(video, records)
            built.append((nasa_id, index))
            log(f"{nasa_id[:44]:44s} {len(records):3d} records  bodies={summary.get('body_counts')}")
        except Exception as exc:  # noqa: BLE001
            log(f"{nasa_id[:44]:44s} FAILED {type(exc).__name__}: {str(exc)[:180]}")
        manifest.put(nasa_id, mission_meta_summary=summary)

    log("waiting for indexes to become ready")
    failed = 0
    for nasa_id, index in built:
        try:
            index.wait_until_complete(timeout=600)
            if not index.is_successful:
                failed += 1
                log(f"{nasa_id[:44]:44s} status={index.status} err={index.error}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            log(f"{nasa_id[:44]:44s} wait failed {type(exc).__name__}: {str(exc)[:120]}")

    log(f"rebuilt {len(built)}, failed {failed}")
    log(f"celestial_body across corpus: {dict(sorted(bodies.items(), key=lambda kv: -kv[1]))}")


if __name__ == "__main__":
    main()
