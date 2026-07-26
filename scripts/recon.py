"""Field-name reconnaissance.

The bundled docs disagree with each other about what fields each analyzer
actually emits (see NOTES.md). `video.index()` validates `fields` synchronously
and the resulting error enumerates the real names, so the fastest way to learn
the truth is to ask for a field that cannot exist and read the complaint.

Writes docs/field-schema.md. Run once; re-run after changing the VLM schema.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import nasa  # noqa: E402
import videodb_client as vc  # noqa: E402

RECON_NASA_ID = "ksc_102504_marsdrill"
STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "recon.json"
OUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "field-schema.md"

# Kept deliberately small: this run exists to learn field names, not to produce
# good retrieval. Coarse shots and one frame per scene keep it cheap and fast.
SEGMENTATION = {"type": "shot", "threshold": 30}
TRANSFORM = {"resolution": "480p"}

VLM_SCHEMA = {
    "scene_description": "text",
    "celestial_body": {
        "type": "enum",
        "values": ["mars", "moon", "earth", "earth_orbit", "sun", "deep_space", "ground", "unknown"],
    },
    "event_type": {
        "type": "enum",
        "values": [
            "launch", "landing", "surface_ops", "instrument_readout", "briefing",
            "data_visualization", "animation", "eva", "other",
        ],
    },
    "evidence_shown": {
        "type": "enum",
        "values": ["surface_imagery", "data_visualization", "instrument", "model_animation", "none"],
    },
    "mission_ref": {
        "type": "string",
        "required": False,
        "description": "NASA mission named or clearly depicted in this scene, if any.",
    },
    "era_year": {
        "type": "number",
        "required": False,
        "description": "Year of the events or findings discussed, not the year the video was published.",
    },
    "on_screen_text": "text",
}

VLM_PROMPT = (
    "This is archival NASA footage. Describe the scene using the frames as primary "
    "evidence. Name the celestial body shown, the kind of event, and what form of "
    "evidence is on screen. If a mission is named or depicted, record it. If the "
    "narration or on-screen text refers to findings from a particular year, record "
    "that year in era_year.\n\n"
    "Spoken words:\n{{inputs.transcript}}\n\n"
    "On-screen text:\n{{inputs.ocr}}"
)

# Hosted analyzers. `object_detection` is deliberately absent: the server has no
# default model for it and rejects the run with "No active sandbox compatible
# with model 'rtdetr-v2-r50vd'". It is probed separately by --with-objects.
ANALYZERS = [
    {"type": "spoken_words", "name": "transcript"},
    {"type": "ocr", "name": "ocr", "sampling": {"strategy": "uniform", "frame_count": 2}},
    {
        "type": "vlm",
        "name": "scene",
        "inputs": ["transcript", "ocr"],
        "sampling": {"strategy": "uniform", "frame_count": 3},
        "config": {"model": "pro", "schema": VLM_SCHEMA, "prompt": VLM_PROMPT},
    },
]

OBJECT_MODEL = "rtdetr-v2-r50vd"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def upload(coll, state: dict):
    if state.get("video_id"):
        log(f"reusing uploaded video {state['video_id']}")
        return coll.get_video(state["video_id"])

    meta = nasa.resolve(RECON_NASA_ID)
    log(f"uploading {RECON_NASA_ID} -> {meta['mp4_url']}")
    video = coll.upload(url=meta["mp4_url"], name=meta["title"] or RECON_NASA_ID)
    state["video_id"] = video.id
    state["nasa"] = {k: v for k, v in meta.items() if k != "all_hrefs"}
    save_state(state)
    log(f"uploaded video_id={video.id} length={video.length}s")
    return video


def run_understanding(video, state: dict, key: str, analyzers: list):
    if state.get(key):
        log(f"reusing understanding {state[key]}")
        return video.get_understanding(state[key])

    log(f"starting understanding run ({key}) with {[a['name'] for a in analyzers]}")
    understanding = video.understand(
        analyzers=analyzers,
        segmentation=SEGMENTATION,
        transform=TRANSFORM,
    )
    state[key] = understanding.id
    save_state(state)
    return understanding


def wait_for_analyzers(understanding, timeout: int = 5400) -> list:
    """Poll analyzers, not the run.

    A run with any failed or skipped analyzer settles on `partial`, which the SDK
    does not treat as terminal, so wait_until_complete() would poll to
    TimeoutError. The `analyzers and` guard matters too: a refresh can transiently
    return an empty list and all([]) is True, which would exit early.
    """
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        analyzers = understanding.refresh().list_analyzers()
        state = {a.name: a.status for a in analyzers}
        if state != last:
            log(f"analyzers: {state}")
            last = state
        if analyzers and all(a.is_complete for a in analyzers):
            return analyzers
        time.sleep(15)
    raise TimeoutError("analyzers did not settle")


def probe_fields(video, analyzer) -> dict:
    """Ask for an impossible field and read the real names out of the error."""
    result: dict = {"analyzer": analyzer.name, "type": analyzer.type}
    try:
        video.index(
            source=analyzer,
            name=f"probe_{analyzer.name}_{int(time.time())}",
            fields={"filter": ["__does_not_exist__"]},
        )
        result["error"] = None
        result["note"] = "index() accepted a bogus field, validation is looser than documented"
    except Exception as exc:  # noqa: BLE001 - we want whatever the server says
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def sample_output(analyzer, limit: int = 2) -> dict:
    try:
        output = analyzer.get_output()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}

    scenes = output.get("scenes", output) if isinstance(output, dict) else output
    if not isinstance(scenes, list):
        return {"raw_type": type(output).__name__, "raw": str(output)[:800]}

    return {
        "scene_count": len(scenes),
        "samples": [
            {
                "start": s.get("start"),
                "end": s.get("end"),
                "data_keys": sorted((s.get("data") or {}).keys()),
                "data": s.get("data"),
            }
            for s in scenes[:limit]
        ],
    }


def run_object_detection(video, state: dict) -> list:
    """Probe object_detection, which only runs on a sandbox.

    Billing is by sandbox runtime, so the sandbox is stopped in a finally block.
    provisioning/active/alert all count against the concurrency cap, so a leaked
    sandbox blocks later creates as well as burning credit.
    """
    conn = vc.connect()
    sandbox = None
    try:
        log(f"creating small sandbox for {OBJECT_MODEL}")
        sandbox = conn.create_sandbox(tier="small", models=[OBJECT_MODEL])
        sandbox.wait_for_ready(timeout=600, interval=5)
        log(f"sandbox {sandbox.id} status={sandbox.status}")

        analyzers = [{
            "type": "object_detection",
            "name": "objects",
            "sampling": {"strategy": "interval", "every": 2},
            "config": {"model": OBJECT_MODEL, "sandbox_id": sandbox.id},
        }]
        understanding = run_understanding(video, state, "objects_understanding_id", analyzers)
        return wait_for_analyzers(understanding, timeout=2700)
    finally:
        if sandbox is not None:
            log(f"stopping sandbox {sandbox.id}")
            try:
                sandbox.stop()
                sandbox.wait_for_stop(timeout=180, interval=5)
                log(f"sandbox final status={sandbox.status}")
            except Exception as exc:  # noqa: BLE001
                log(f"WARNING sandbox stop failed: {type(exc).__name__}: {exc}")


def main() -> None:
    with_objects = "--with-objects" in sys.argv
    coll = vc.get_collection()
    state = load_state()

    before = vc.usage().get("credit_used")
    log(f"credit_used before: {before}")

    video = upload(coll, state)
    understanding = run_understanding(video, state, "understanding_id", ANALYZERS)
    analyzers = wait_for_analyzers(understanding)

    if with_objects:
        analyzers = list(analyzers) + list(run_object_detection(video, state))

    report: dict = {
        "video_id": video.id,
        "video_length": video.length,
        "nasa_id": RECON_NASA_ID,
        "segmentation": SEGMENTATION,
        "analyzers": {},
    }

    for analyzer in analyzers:
        log(f"probing {analyzer.name} (status={analyzer.status})")
        entry = {
            "status": analyzer.status,
            "sdk_type": analyzer.type,
            "successful": analyzer.is_successful,
        }
        if analyzer.is_successful:
            entry["output"] = sample_output(analyzer)
            entry["field_probe"] = probe_fields(video, analyzer)
        report["analyzers"][analyzer.name] = entry

    after = vc.usage().get("credit_used")
    report["credit_used"] = {"before": before, "after": after}
    log(f"credit_used after: {after} (delta {round((after or 0) - (before or 0), 6)})")

    state["report"] = report
    save_state(state)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render(report))
    log(f"wrote {OUT_PATH}")


def render(report: dict) -> str:
    lines = [
        "# Observed field schema",
        "",
        "Generated by `scripts/recon.py`. Every value here came from a live API response",
        "or a live validation error, not from documentation.",
        "",
        f"- video: `{report['nasa_id']}` (`{report['video_id']}`), {report['video_length']}s",
        f"- segmentation: `{report['segmentation']}`",
        f"- credits used by this run: {report['credit_used']}",
        "",
    ]
    for name, entry in report["analyzers"].items():
        lines += [
            f"## `{name}`",
            "",
            f"- status: `{entry['status']}`",
            f"- `analyzer.type` reported by SDK: `{entry['sdk_type']}`",
            "",
        ]
        output = entry.get("output") or {}
        if "samples" in output:
            lines.append(f"- scenes produced: {output['scene_count']}")
            for sample in output["samples"]:
                lines += [
                    "",
                    f"Scene `{sample['start']}`-`{sample['end']}` data keys:",
                    "",
                    "```",
                    ", ".join(sample["data_keys"]) or "(none)",
                    "```",
                    "",
                    "```json",
                    json.dumps(sample["data"], indent=2)[:2000],
                    "```",
                ]
        elif output:
            lines += ["", "```", json.dumps(output, indent=2)[:1500], "```"]

        probe = entry.get("field_probe") or {}
        if probe.get("error"):
            lines += [
                "",
                "Validation error for a bogus filter field (lists the valid names):",
                "",
                "```",
                probe["error"][:2000],
                "```",
            ]
        elif probe:
            lines += ["", f"Note: {probe.get('note')}"]
        lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
