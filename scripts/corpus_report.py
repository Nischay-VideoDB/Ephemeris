"""Summarise the corpus: era coverage, mission coverage, and index health.

Answers the question the corpus expansion was meant to fix: does the archive now
support reasoning across decades, or does everything still collapse onto the
publication date?
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import indexing  # noqa: E402
import manifest  # noqa: E402
import mission_meta as mm  # noqa: E402
import understanding as und  # noqa: E402
import videodb_client as vc  # noqa: E402


def main() -> None:
    coll = vc.get_collection()
    entries = manifest.load()

    rows: list[dict] = []
    print(f"{'nasa_id':46s} {'pub':>4s} {'len':>6s} {'scn':>4s} {'era':>5s} {'axis':>8s}  missions")
    print("-" * 118)

    total_seconds = 0.0
    for nasa_id, entry in sorted(entries.items(), key=lambda kv: kv[1].get("published_year") or 0):
        if not entry.get("video_id"):
            continue
        video = coll.get_video(entry["video_id"])
        total_seconds += float(entry.get("video_length") or 0)

        try:
            understanding = video.get_understanding(entry["understanding_id"])
            scene = und.successful(understanding.refresh().list_analyzers()).get("scene")
            scenes = und.scenes_of(scene) if scene else []
        except Exception:  # noqa: BLE001
            scenes = []

        records = mm.build_records(scenes, {**entry, "nasa_id": nasa_id})
        rows += records
        summary = mm.summarize(records)
        axes = summary.get("era_axis_counts") or {}
        dominant = max(axes, key=axes.get) if axes else "-"
        era_range = summary.get("era_range") or [0, 0]

        print(f"{nasa_id[:46]:46s} {entry.get('published_year') or 0:4d} "
              f"{entry.get('video_length') or 0:6.0f} {summary.get('count', 0):4d} "
              f"{era_range[0]:5d} {dominant:>8s}  "
              f"{','.join(summary.get('missions') or [])[:40]}")

    print()
    print(f"clips {len([e for e in entries.values() if e.get('video_id')])}   "
          f"footage {total_seconds / 60:.1f} min   scenes {len(rows)}")

    if not rows:
        return

    axes = Counter(r["era_axis"] for r in rows)
    dated = sum(v for k, v in axes.items() if k != "published")
    print(f"era_axis        {dict(axes)}   dated share {dated / len(rows):.3f}")
    print(f"era_basis       {dict(Counter(r['era_basis'] for r in rows))}")
    print(f"era_start range {min(r['era_start'] for r in rows)}-{max(r['era_start'] for r in rows)}")
    print(f"decades covered {sorted({r['era_start'] // 10 * 10 for r in rows})}")

    bodies = Counter(r.get("celestial_body", "unknown") for r in rows)
    print(f"bodies          {dict(bodies.most_common())}")
    print(f"body spread     {len([b for b, n in bodies.items() if n >= 5])} bodies with 5+ scenes")
    print(f"events          {dict(Counter(r.get('event_type', 'other') for r in rows).most_common())}")

    domains = Counter(entries[r["nasa_id"]].get("domain", "mars") for r in rows
                      if r["nasa_id"] in entries)
    print(f"domains         {dict(domains.most_common())}")

    missions = Counter(r["primary_mission"] for r in rows)
    print(f"missions        {dict(missions.most_common(14))}")
    known = sum(v for k, v in missions.items() if k != mm.UNKNOWN_MISSION)
    print(f"mission share   {known / len(rows):.3f}")
    print(f"water relevance {dict(Counter(r.get('water_relevance', 'none') for r in rows))}")

    print()
    print("index health:")
    expected = {indexing.TRANSCRIPT, indexing.SCENE_SEMANTIC, indexing.SCENE_FACETS,
                indexing.OCR, indexing.MISSION_META}
    for nasa_id, entry in sorted(entries.items()):
        if not entry.get("video_id"):
            continue
        video = coll.get_video(entry["video_id"])
        names = Counter(ix.name for ix in video.list_indexes())
        states = {ix.name: ix.status for ix in video.list_indexes()}
        missing = expected - set(names)
        dupes = {n: c for n, c in names.items() if c > 1}
        bad = {n: s for n, s in states.items() if s != "ready"}
        flags = []
        if missing:
            flags.append(f"MISSING={sorted(missing)}")
        if dupes:
            flags.append(f"DUPLICATE={dupes}")
        if bad:
            flags.append(f"NOT_READY={bad}")
        print(f"  {nasa_id[:52]:52s} {len(names)} indexes  {' '.join(flags) or 'ok'}")


if __name__ == "__main__":
    main()
