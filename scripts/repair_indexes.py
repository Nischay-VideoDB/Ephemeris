"""Rebuild missing indexes from artifacts that already exist.

An index name is a schema contract across the whole collection. Changing the record
structure (adding celestial_body values, for example) forces every video carrying an
older index under that name to be dropped, and build.py's self-healing path does exactly
that: drops the name everywhere, then rebuilds only the video it was working on. Every
other video is left without that index until something rebuilds it.

That is what this script is for. No inference is repeated: understanding artifacts survive
index deletion, so a rebuild costs nothing but time.

    python scripts/repair_indexes.py            # report only
    python scripts/repair_indexes.py --apply    # rebuild what is missing
    python scripts/repair_indexes.py --apply --workers 4
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import indexing  # noqa: E402
import manifest  # noqa: E402
import mission_meta  # noqa: E402
import understanding as und  # noqa: E402
import videodb_client as vc  # noqa: E402

def clean_records(analyzer, fields: list[str]) -> list[dict]:
    """Scene rows as custom records, dropping any the model failed on.

    A frame that trips the provider's content-safety filter comes back as
    `{"error": {...}}` in place of the declared schema fields. One such row changes the
    artifact's field set, and since an index name is a collection-wide structural contract,
    it makes the whole clip unindexable under a name other clips already established.
    Indexing from records instead lets the good scenes through and drops only the bad ones.
    """
    records = []
    for row in und.scenes_of(analyzer):
        data = row.get("data") or {}
        if "error" in data or not data:
            continue
        record = {"start": float(row.get("start") or 0), "end": float(row.get("end") or 0)}
        for field in fields:
            value = data.get(field)
            record[field] = "" if value is None else value
        records.append(record)
    return records


SCENE_FIELDS = [
    "scene_description", "on_screen_text", "celestial_body", "event_type",
    "evidence_shown", "mission_ref", "era_year", "era_basis",
]

# mission_meta is rebuilt from records rather than an artifact, so it is handled separately.
FROM_ARTIFACT = {
    indexing.TRANSCRIPT: ("transcript", indexing.build_transcript_index),
    indexing.SCENE_SEMANTIC: ("scene", indexing.build_scene_semantic_index),
    indexing.SCENE_FACETS: ("scene", indexing.build_scene_facets_index),
    indexing.OCR: ("ocr", indexing.build_ocr_index),
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def repair_one(coll, nasa_id: str, entry: dict, apply: bool) -> dict:
    video = coll.get_video(entry["video_id"])
    present = {ix.name for ix in video.list_indexes()}

    understanding = video.get_understanding(entry["understanding_id"])
    artifacts = und.successful(understanding.refresh().list_analyzers())

    wanted = [indexing.TRANSCRIPT, indexing.SCENE_SEMANTIC, indexing.SCENE_FACETS]
    if entry.get("has_ocr", True):
        wanted.append(indexing.OCR)

    missing = [name for name in wanted if name not in present]
    if indexing.MISSION_META not in present:
        missing.append(indexing.MISSION_META)

    result = {"nasa_id": nasa_id, "missing": missing, "rebuilt": [], "skipped": [], "errors": []}
    if not missing or not apply:
        return result

    for name in missing:
        try:
            if name == indexing.MISSION_META:
                scene = artifacts.get("scene")
                if scene is None:
                    result["skipped"].append(f"{name}: no scene artifact")
                    continue
                records = mission_meta.build_records(
                    und.scenes_of(scene), {**entry, "nasa_id": nasa_id}
                )
                if not records:
                    result["skipped"].append(f"{name}: no records")
                    continue
                indexing.build_mission_meta_index(video, records)
            else:
                artifact_name, builder = FROM_ARTIFACT[name]
                artifact = artifacts.get(artifact_name)
                if artifact is None:
                    result["skipped"].append(f"{name}: no {artifact_name} artifact")
                    continue
                try:
                    builder(video, artifact)
                except Exception as exc:  # noqa: BLE001
                    if "different scene structure" not in str(exc) or name not in (
                        indexing.SCENE_SEMANTIC, indexing.SCENE_FACETS
                    ):
                        raise
                    # Rebuild from cleaned records so error rows cannot break the contract.
                    records = clean_records(artifact, SCENE_FIELDS)
                    if not records:
                        result["skipped"].append(f"{name}: no usable scenes")
                        continue
                    if name == indexing.SCENE_SEMANTIC:
                        video.index(source=records, name=name, use_for=["semantic"],
                                    fields={"semantic": ["scene_description", "on_screen_text"]})
                    else:
                        video.index(source=records, name=name, use_for=["query", "aggregate"],
                                    fields={"filter": indexing.FACET_FIELDS + ["era_year"],
                                            "aggregate": indexing.FACET_FIELDS,
                                            "sort": ["era_year"]})
                    result["rebuilt"].append(f"{name} (records)")
                    continue
            result["rebuilt"].append(name)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            # Silent footage: the artifact exists but holds nothing embeddable. A property of
            # the clip, not a failure, and it must not stop the remaining indexes.
            if "no scene has embeddable text" in message:
                result["skipped"].append(f"{name}: no embeddable text")
            elif "different scene structure" in message and name == indexing.TRANSCRIPT:
                # Silent footage: ASR emits rows with empty text and no `words` field, so the
                # artifact cannot satisfy a contract built from clips that do carry speech.
                # Correct outcome is no transcript index; the clip stays retrievable visually.
                result["skipped"].append(f"{name}: silent clip, no word-level transcript")
            else:
                result["errors"].append(f"{name}: {message[:160]}")
    return result


def main() -> None:
    args = sys.argv[1:]
    apply = "--apply" in args
    workers = 4
    if "--workers" in args:
        workers = max(1, int(args[args.index("--workers") + 1]))

    coll = vc.get_collection()
    entries = {
        nid: e for nid, e in manifest.load().items()
        if e.get("video_id") and e.get("understanding_id")
    }
    log(f"checking {len(entries)} clips, apply={apply}, workers={workers}")

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(repair_one, coll, nid, entry, apply): nid
            for nid, entry in entries.items()
        }
        for future in as_completed(futures):
            nid = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                log(f"  {nid[:46]:46s} FAILED {type(exc).__name__}: {str(exc)[:120]}")
                continue
            results.append(result)
            if result["missing"]:
                log(f"  {nid[:46]:46s} missing={result['missing']} "
                    f"rebuilt={result['rebuilt']} skipped={result['skipped']} "
                    f"errors={result['errors']}")

    needed = [r for r in results if r["missing"]]
    rebuilt = sum(len(r["rebuilt"]) for r in results)
    skipped = sum(len(r["skipped"]) for r in results)
    errors = [e for r in results for e in r["errors"]]
    log(f"clips needing repair {len(needed)} of {len(results)}; "
        f"indexes rebuilt {rebuilt}, skipped {skipped}, errors {len(errors)}")
    for err in errors[:10]:
        log(f"  ERROR {err}")


if __name__ == "__main__":
    main()
