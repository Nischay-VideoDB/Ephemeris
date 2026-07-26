"""Chained understanding runs.

Analyzer graph per video:

    spoken_words ──┐
                   ├──> vlm  (inputs=[transcript, ocr], schema, {{inputs.*}})
    ocr ───────────┘

The VLM reads the transcript and the on-screen text while it looks at the frames,
so a scene is described with knowledge of what was said and what was printed
during it. That is cross-modal fusion at ingestion time rather than a merge of
three separate searches at query time.

`object_detection` is not in the graph. The server has no hosted model for it and
rejects the run with "No active sandbox compatible with model 'rtdetr-v2-r50vd'",
so it costs a sandbox at $1/hour. It is added separately, if at all.
"""

from __future__ import annotations

import time
from typing import Callable

from schema import SAMPLING_BY_PROFILE, VLM_SCHEMA, vlm_prompt

# Measured on a 53s clip, see data/segmentation_probe.json:
#
#   shot/30   2 scenes   median 52.67s   <- one 52-second "moment", not citable
#   shot/20   3 scenes   median 14.67s
#   shot/10  13 scenes   median  2.27s   <- too choppy to watch
#   time/10s  6 scenes   median 10.00s   <- every scene carries speech
#
# Shot detection is erratic on archival footage: threshold 30 finds 2 boundaries
# where threshold 10 finds 13, and `min_scene_len` had no visible effect. Time
# segmentation is predictable, which matters because indexes sharing a name across
# videos must have identical structure.
DEFAULT_SEGMENTATION = {"type": "time", "seconds": 10}
TRANSFORM = {"resolution": "480p"}

OBJECT_MODEL = "rtdetr-v2-r50vd"


# The managed VLM tier. `pro` was the default for the first 19 clips; the hackathon
# account carries a separate per-tier budget ($20 on Llm Pro) which is independent of
# the credit balance, and it ran out mid-expansion. Tier is therefore a parameter, and
# which tier analysed a clip is recorded in the manifest so the corpus stays auditable.
DEFAULT_VLM_MODEL = "pro"


def build_analyzers(profile: str = "visual", model: str = DEFAULT_VLM_MODEL,
                    sandbox_id: str | None = None, use_ocr: bool = True) -> list[dict]:
    """`sandbox_id` switches the VLM to an open-weight model on Sandbox Compute; managed
    models reject it, so it is only set alongside a self-hosted model id.

    `use_ocr` drops the OCR analyzer and its chained input. The hackathon account's
    managed-tier budget is per tier and OCR bills against the exhausted one, so a run
    including OCR is refused outright. Without it the VLM still records on-screen text
    into `on_screen_text` from the frames, but there is no separate `ocr` index.
    """
    sampling = SAMPLING_BY_PROFILE.get(profile, SAMPLING_BY_PROFILE["visual"])
    vlm_config: dict = {"model": model, "schema": VLM_SCHEMA,
                        "prompt": vlm_prompt(with_ocr=use_ocr)}
    if sandbox_id:
        vlm_config["sandbox_id"] = sandbox_id

    analyzers: list[dict] = [{"type": "spoken_words", "name": "transcript"}]
    inputs = ["transcript"]
    if use_ocr:
        analyzers.append({"type": "ocr", "name": "ocr",
                          "sampling": {"strategy": "uniform", "frame_count": 2}})
        inputs.append("ocr")

    analyzers.append({
        "type": "vlm",
        "name": "scene",
        "inputs": inputs,
        "sampling": sampling,
        "config": vlm_config,
    })
    return analyzers


def start(video, profile: str = "visual", segmentation: dict | None = None,
          model: str = DEFAULT_VLM_MODEL, sandbox_id: str | None = None,
          use_ocr: bool = True):
    return video.understand(
        analyzers=build_analyzers(profile, model=model, sandbox_id=sandbox_id,
                                  use_ocr=use_ocr),
        segmentation=segmentation or DEFAULT_SEGMENTATION,
        transform=TRANSFORM,
    )


def wait_for_analyzers(understanding, timeout: int = 5400, poll: int = 15,
                       on_change: Callable[[dict], None] | None = None) -> list:
    """Poll analyzers rather than the run.

    A run where any analyzer fails or is skipped settles on `partial`, which the
    SDK does not count as terminal, so `wait_until_complete()` would poll until it
    raised TimeoutError. The `analyzers and` guard is also load-bearing: a refresh
    can transiently return an empty list, and `all([])` is True, which would exit
    the loop while the run is still going.
    """
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        analyzers = understanding.refresh().list_analyzers()
        status = {a.name: a.status for a in analyzers}
        if on_change and status != last:
            on_change(status)
            last = status
        if analyzers and all(a.is_complete for a in analyzers):
            return analyzers
        time.sleep(poll)
    raise TimeoutError(f"analyzers did not settle within {timeout}s")


def successful(analyzers: list) -> dict:
    """Name to analyzer, dropping any that failed or were skipped.

    Never match on `analyzer.type`: it echoes the server's internal name, so a
    `spoken_words` analyzer reports `speech_transcription`. `analyzer.name` is ours.
    """
    return {a.name: a for a in analyzers if a.is_successful}


def scenes_of(analyzer) -> list[dict]:
    """Timestamped scenes for one analyzer.

    The payload is normally {"scenes": [...]} but can be a bare list.
    """
    output = analyzer.get_output()
    scenes = output.get("scenes", output) if isinstance(output, dict) else output
    return scenes if isinstance(scenes, list) else []


def object_detection_analyzer(sandbox_id: str) -> dict:
    return {
        "type": "object_detection",
        "name": "objects",
        "sampling": {"strategy": "interval", "every": 2},
        "config": {"model": OBJECT_MODEL, "sandbox_id": sandbox_id},
    }
