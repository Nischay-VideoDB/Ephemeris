"""Find a segmentation that yields citable moments.

The first recon run cut a 53-second clip into two scenes, one of them 52 seconds
long. A 52-second "moment" is not evidence, so segmentation has to be settled
before the real pipeline runs.

Only `spoken_words` is attached, because segmentation is a run-level setting and
the scene boundaries it produces are the same whichever analyzer consumes them.
Transcription is the cheapest analyzer, so this measures boundaries for very
little credit.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import videodb_client as vc  # noqa: E402

VIDEO_ID = "m-z-019f980b-ae2e-7073-88e7-1db2cf36aae7"  # ksc_102504_marsdrill, 53s
OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "segmentation_probe.json"

CONFIGS = [
    {"label": "shot/30 (baseline)", "segmentation": {"type": "shot", "threshold": 30}},
    {"label": "shot/20", "segmentation": {"type": "shot", "threshold": 20}},
    {"label": "shot/10", "segmentation": {"type": "shot", "threshold": 10}},
    {"label": "shot/12+min4", "segmentation": {"type": "shot", "threshold": 12, "min_scene_len": 4}},
    {"label": "time/10s", "segmentation": {"type": "time", "seconds": 10}},
    {"label": "time/15s", "segmentation": {"type": "time", "seconds": 15}},
]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def wait(understanding, timeout: int = 1800) -> list:
    deadline = time.time() + timeout
    while time.time() < deadline:
        analyzers = understanding.refresh().list_analyzers()
        if analyzers and all(a.is_complete for a in analyzers):
            return analyzers
        time.sleep(10)
    raise TimeoutError("analyzers did not settle")


def scenes_of(analyzer) -> list[dict]:
    output = analyzer.get_output()
    scenes = output.get("scenes", output) if isinstance(output, dict) else output
    return scenes if isinstance(scenes, list) else []


def main() -> None:
    coll = vc.get_collection()
    video = coll.get_video(VIDEO_ID)
    before = vc.usage().get("credit_used")
    log(f"probing {len(CONFIGS)} segmentations on a {video.length}s clip")

    results = []
    for config in CONFIGS:
        label = config["label"]
        try:
            understanding = video.understand(
                analyzers=[{"type": "spoken_words", "name": "transcript"}],
                segmentation=config["segmentation"],
                transform={"resolution": "480p"},
            )
            analyzers = wait(understanding)
            scenes = scenes_of(analyzers[0])
            spans = [round(float(s["end"]) - float(s["start"]), 2) for s in scenes]
            with_text = sum(1 for s in scenes if (s.get("data") or {}).get("text"))
            entry = {
                "label": label,
                "segmentation": config["segmentation"],
                "understanding_id": understanding.id,
                "scene_count": len(scenes),
                "spans": spans,
                "median_span": sorted(spans)[len(spans) // 2] if spans else None,
                "max_span": max(spans) if spans else None,
                "scenes_with_speech": with_text,
                "boundaries": [[round(float(s["start"]), 2), round(float(s["end"]), 2)] for s in scenes],
            }
            log(
                f"{label:20s} scenes={len(scenes):3d} median={entry['median_span']} "
                f"max={entry['max_span']} with_speech={with_text}"
            )
        except Exception as exc:  # noqa: BLE001
            entry = {"label": label, "segmentation": config["segmentation"],
                     "error": f"{type(exc).__name__}: {exc}"}
            log(f"{label:20s} FAILED {entry['error'][:160]}")
        results.append(entry)

    after = vc.usage().get("credit_used")
    log(f"credit delta: {round((after or 0) - (before or 0), 6)}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(
        {"video_id": VIDEO_ID, "video_length": float(video.length or 0),
         "credit_delta": round((after or 0) - (before or 0), 6), "results": results},
        indent=2,
    ))
    log(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
