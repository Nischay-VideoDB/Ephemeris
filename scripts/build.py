"""Run understanding and build indexes for every clip in the manifest.

Idempotent per clip: understanding ids and index names are recorded in the
manifest, so a re-run resumes rather than repeating paid work.

    python scripts/build.py                # process everything pending
    python scripts/build.py --only <id>    # one nasa_id
    python scripts/build.py --reindex      # rebuild indexes from existing artifacts
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import era  # noqa: E402
import indexing  # noqa: E402
import manifest  # noqa: E402
import mission_meta  # noqa: E402
import understanding as und  # noqa: E402
import videodb_client as vc  # noqa: E402

REPORT_PATH = Path(__file__).resolve().parent.parent / "data" / "build_report.json"

# Set from argv in main(). Module-level because run_understanding is called per clip from
# the scheduler loop rather than threaded through it.
VLM_MODEL = und.DEFAULT_VLM_MODEL
USE_OCR = True


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run_understanding(video, entry: dict, nasa_id: str, reindex: bool):
    existing = entry.get("understanding_id")
    if existing and reindex:
        log(f"  reusing understanding {existing}")
        return video.get_understanding(existing)
    if existing:
        understanding = video.get_understanding(existing)
        analyzers = understanding.refresh().list_analyzers()
        if analyzers and all(a.is_complete for a in analyzers):
            log(f"  understanding {existing} already complete")
            return understanding
        log(f"  resuming understanding {existing}")
        return understanding

    profile = entry.get("profile", "visual")
    log(f"  starting understanding (profile={profile}, model={VLM_MODEL}, ocr={USE_OCR})")
    understanding = und.start(video, profile=profile, model=VLM_MODEL, use_ocr=USE_OCR)
    # Which model analysed a clip is provenance, not trivia: the corpus is split across
    # tiers because a per-tier budget ran out mid-expansion.
    manifest.put(nasa_id, understanding_id=understanding.id,
                 vlm_model=VLM_MODEL, has_ocr=USE_OCR)
    return understanding


def extract_video_era(coll, video, entry: dict, nasa_id: str) -> dict:
    """Clip-level era pass. Cheap next to indexing, and it rescues the scenes that
    correctly declined to guess a year on their own."""
    if entry.get("video_era") and not entry["video_era"].get("error"):
        return entry["video_era"]

    result = era.extract(coll, video, {**entry, "nasa_id": nasa_id})
    if result.get("error"):
        log(f"    video era FAILED: {result['error'][:120]}")
    else:
        log(f"    video era earliest={result['earliest_era_year']} "
            f"topic={result['primary_topic_year']} water={result['water_relevance']} "
            f"missions={[m['mission'] for m in result['missions']][:6]}")
    manifest.put(nasa_id, video_era=result)
    return result


def build_indexes(coll, video, entry: dict, nasa_id: str, by_name: dict) -> list[dict]:
    built: list[dict] = []

    # Index creation does not replace, it adds. Re-running would leave two indexes
    # answering to the same name, so drop existing ones first. Deleting an index
    # removes only its retrieval structures; the video and its artifacts survive,
    # which is why this is safe to do on every run.
    existing = {ix.name: ix for ix in video.list_indexes()}

    def record(index):
        if index is None:
            return
        info = indexing.describe(index)
        built.append(info)
        log(f"    {info['name']:16s} status={info['status']} records={info['record_count']} "
            f"use_for={info['use_for']}")

    def fresh(name: str) -> None:
        stale = existing.pop(name, None)
        if stale is not None:
            stale.delete()

    def create(name: str, factory):
        """Create an index, healing a collection-wide schema conflict if one occurs.

        An index name is a schema contract across the *whole collection*, not per
        video. Adding a field to the records therefore fails on every video that
        still carries an older index under the same name, and dropping it only on
        the video being processed is not enough. When the server reports a
        structure mismatch, drop that name everywhere and retry once.
        """
        try:
            return factory()
        except Exception as exc:  # noqa: BLE001
            if "different scene structure" not in str(exc):
                raise
            log(f"    {name}: collection-wide structure changed, dropping stale copies")
            dropped = 0
            for other in coll.get_videos():
                for index in other.list_indexes():
                    if index.name == name:
                        index.delete()
                        dropped += 1
            log(f"    {name}: dropped {dropped}, retrying")
            return factory()

    def create_optional(name: str, factory):
        """Some clips are silent archival B-roll: music and natural sound, no narration.
        Their transcript artifact exists but holds no text, and a semantic index over
        nothing is refused. That is a property of the footage, not a build failure, so
        it must not cost the clip its other four indexes."""
        try:
            return create(name, factory)
        except Exception as exc:  # noqa: BLE001
            if "no scene has embeddable text" in str(exc):
                log(f"    {name}: skipped, clip has no embeddable text (silent footage)")
                return None
            raise

    transcript = by_name.get("transcript")
    scene = by_name.get("scene")
    ocr = by_name.get("ocr")

    if transcript is not None:
        fresh(indexing.TRANSCRIPT)
        record(create_optional(indexing.TRANSCRIPT,
                               lambda: indexing.build_transcript_index(video, transcript)))
    if ocr is not None:
        fresh(indexing.OCR)
        record(create(indexing.OCR, lambda: indexing.build_ocr_index(video, ocr)))

    if scene is not None:
        # Two indexes from one artifact: prose for vector search, enums for exact
        # filtering and counting. One model pass, two retrieval surfaces.
        fresh(indexing.SCENE_SEMANTIC)
        record(create_optional(indexing.SCENE_SEMANTIC,
                               lambda: indexing.build_scene_semantic_index(video, scene)))
        fresh(indexing.SCENE_FACETS)
        record(create(indexing.SCENE_FACETS,
                      lambda: indexing.build_scene_facets_index(video, scene)))

        video_era = extract_video_era(coll, video, entry, nasa_id)

        scenes = und.scenes_of(scene)
        records = mission_meta.build_records(
            scenes, {**entry, "nasa_id": nasa_id, "video_era": video_era}
        )
        summary = mission_meta.summarize(records)
        log(f"    mission_meta records={summary['count']} "
            f"dated={summary.get('dated_share')} axes={summary.get('era_axis_counts')} "
            f"range={summary.get('era_range')} missions={summary.get('missions')}")
        manifest.put(nasa_id, mission_meta_summary=summary)
        if records:
            fresh(indexing.MISSION_META)
            record(create(indexing.MISSION_META,
                          lambda: indexing.build_mission_meta_index(video, records)))

    return built


def index_one(coll, video, nasa_id: str, understanding, report: dict) -> None:
    """Index a clip whose analyzers have settled."""
    analyzers = understanding.refresh().list_analyzers()
    by_name = und.successful(analyzers)
    failed = [a.name for a in analyzers if not a.is_successful]
    if failed:
        log(f"  {nasa_id}: WARNING failed analyzers {failed}")

    built = build_indexes(coll, video, manifest.load()[nasa_id], nasa_id, by_name)
    manifest.put(nasa_id, indexes=[i["name"] for i in built])
    report["clips"][nasa_id] = {
        "video_id": video.id,
        "analyzers": {a.name: a.status for a in analyzers},
        "indexes": built,
    }


def main() -> None:
    args = sys.argv[1:]
    reindex = "--reindex" in args
    only = None
    if "--only" in args:
        only = args[args.index("--only") + 1]
    # Understanding runs server-side, so the wall clock is analyzer latency rather than
    # local work. Keeping several runs in flight turns an hours-long serial pass over a
    # large corpus into one bounded by the slowest few clips.
    workers = 1
    if "--workers" in args:
        workers = max(1, int(args[args.index("--workers") + 1]))

    global VLM_MODEL, USE_OCR
    if "--vlm-model" in args:
        VLM_MODEL = args[args.index("--vlm-model") + 1]
    if "--no-ocr" in args:
        USE_OCR = False

    coll = vc.get_collection()
    entries = manifest.load()
    before = vc.usage().get("credit_used")
    log(f"credit_used before: {before}, workers={workers}, vlm={VLM_MODEL}, ocr={USE_OCR}")

    report: dict = {"clips": {}}

    pending: list[tuple[str, dict]] = []
    for nasa_id, entry in entries.items():
        if only and nasa_id != only:
            continue
        if not entry.get("video_id"):
            log(f"skip {nasa_id}: not uploaded")
            continue
        if entry.get("indexes") and not reindex:
            log(f"skip {nasa_id}: already indexed")
            continue
        pending.append((nasa_id, entry))

    log(f"{len(pending)} clips to process")
    in_flight: dict[str, dict] = {}
    done = 0

    while pending or in_flight:
        while pending and len(in_flight) < workers:
            nasa_id, entry = pending.pop(0)
            log(f"start {nasa_id} ({entry.get('video_length')}s, {entry.get('profile')})")
            try:
                video = coll.get_video(entry["video_id"])
                understanding = run_understanding(video, entry, nasa_id, reindex)
                in_flight[nasa_id] = {"video": video, "understanding": understanding,
                                      "started": time.time()}
            except Exception as exc:  # noqa: BLE001
                log(f"  ERROR starting {nasa_id}: {type(exc).__name__}: {exc}")
                report["clips"][nasa_id] = {"error": f"{type(exc).__name__}: {exc}"}

        if not in_flight:
            break

        for nasa_id in list(in_flight):
            state = in_flight[nasa_id]
            settled = False
            try:
                analyzers = state["understanding"].refresh().list_analyzers()
                # The `analyzers and` guard matters: a refresh can transiently return an
                # empty list, and all([]) is True, which would index a run still going.
                if analyzers and all(a.is_complete for a in analyzers):
                    settled = True
                elif time.time() - state["started"] > 5400:
                    raise TimeoutError("analyzers did not settle within 5400s")

                if settled:
                    index_one(coll, state["video"], nasa_id, state["understanding"], report)
                    done += 1
                    log(f"  done {nasa_id} ({done} finished, {len(pending)} queued)")
            except Exception as exc:  # noqa: BLE001
                settled = True
                log(f"  ERROR {nasa_id}: {type(exc).__name__}: {exc}")
                report["clips"][nasa_id] = {"error": f"{type(exc).__name__}: {exc}"}

            if settled:
                in_flight.pop(nasa_id, None)

        if in_flight:
            time.sleep(15)

    after = vc.usage().get("credit_used")
    report["credit_used"] = {"before": before, "after": after,
                             "delta": round((after or 0) - (before or 0), 6)}
    log(f"credit_used after: {after} (delta {report['credit_used']['delta']})")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    log(f"wrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
