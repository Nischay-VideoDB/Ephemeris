"""Compile evidence into one playable reel.

The deliverable is not a list of links. It is a single video: the matched moments from
every source clip, in the order of the era each one discusses, with the mission, the
date and the NASA identifier burned into the frame so provenance survives a screen
recording or an export.

Uses the **v2 editor** (`videodb.editor`) exclusively. The older
`videodb.timeline` / `videodb.asset` pair still exists with different constructors and
different keyword names for the same concepts, and mixing them is a silent trap.

Editor constraints that shape this code, all learned the hard way:

- `track.add_clip(start, clip)` takes whole seconds. Sub-second placement is lost, so
  the layout is planned on integer boundaries.
- `Clip(duration=X)` must not exceed the source asset's length, or the render errors.
- `.length` can come back as a string, so it is always cast before arithmetic.
- Durations are floored with `math.floor(x * 100) / 100`. `round()` can round up past
  the real length and trip the previous rule.
- A negative `VideoAsset` start silently produces a broken stream.
"""

from __future__ import annotations

import math
from typing import Any

from videodb.editor import (
    Alignment,
    Background,
    Clip,
    Font,
    HorizontalAlignment,
    TextAsset,
    Timeline,
    Track,
    Transition,
    VerticalAlignment,
    VideoAsset,
)

RESOLUTION = "1280x720"
BACKGROUND = "#05070d"
# A shot is a passage: a run of consecutive matching cells, cut to sentence bounds by
# `speech.sentence_window` rather than to the ten-second indexing grid. So a shot lasts as long
# as the passage it carries. This ceiling is a backstop above `agent.MAX_PASSAGE_SECONDS`,
# which is where the real limit lives; the floor keeps a fragment watchable.
MAX_CLIP_SECONDS = 48
MIN_CLIP_SECONDS = 4
FADE = 0.4


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _floor2(value: float) -> float:
    return math.floor(value * 100) / 100


def caption_for(item: dict, number: int | None = None) -> str:
    era = item.get("era_start")
    axis = item.get("era_axis")
    mission = item.get("mission") or "unknown mission"
    # An inferred date is marked as such in the burned-in text, not just in the UI.
    # The reel is the artefact people keep, so the qualifier has to travel with it.
    if era and axis == "scene":
        stamp = f"{era}"
    elif era and axis == "video":
        stamp = f"{era} (from clip context)"
    elif era:
        stamp = f"{era} (published)"
    else:
        stamp = "undated"
    # The citation number travels with the frame. Someone watching the reel can check a claim
    # against the shot without the interface in front of them, which is the whole reason the
    # provenance is burned in rather than drawn over the player.
    prefix = f"[{number}]  " if number is not None else ""
    return f"{prefix}{stamp}  ·  {mission}  ·  NASA {item.get('nasa_id', '')[:44]}"


def plan(evidence: list[dict], max_clip: int = MAX_CLIP_SECONDS) -> list[dict]:
    """Lay the evidence out, one entry per item.

    `at` is deliberately not assigned here. A clip can still be shortened or dropped in
    `build()` once the source's real length is known, and positions decided before that
    leave silent black gaps in the stream and, worse, a shot list that no longer lines up
    with the evidence it came from. Positions are assigned in `build()` instead.
    """
    layout: list[dict] = []
    for index, item in enumerate(evidence):
        start = max(0.0, _f(item.get("start")))
        end = _f(item.get("end"), start + MIN_CLIP_SECONDS)
        duration = _floor2(min(max(end - start, MIN_CLIP_SECONDS), max_clip))
        if duration <= 0:
            continue
        layout.append({
            "evidence_index": index,
            "video_id": item["video_id"],
            "source_start": start,
            "duration": duration,
            "caption": caption_for(item, index + 1),
            "item": item,
        })
    return layout


def build(conn, coll, evidence: list[dict], *, max_clip: int = MAX_CLIP_SECONDS,
          with_captions: bool = True) -> dict:
    """Render the reel and return its stream URL plus the shot list."""
    layout = plan(evidence, max_clip=max_clip)
    if not layout:
        return {"stream_url": None, "shots": [], "dropped": [],
                "error": "no evidence to compile"}

    lengths: dict[str, float] = {}
    unresolved: set[str] = set()
    timeline = Timeline(conn)
    timeline.resolution = RESOLUTION
    timeline.background = BACKGROUND

    video_track = Track()
    caption_track = Track()
    shots: list[dict] = []
    dropped: list[dict] = []
    cursor = 0

    for entry in layout:
        video_id = entry["video_id"]
        if video_id not in lengths and video_id not in unresolved:
            try:
                lengths[video_id] = _f(coll.get_video(video_id).length)
            except Exception:  # noqa: BLE001 - one missing source must not lose the whole reel
                unresolved.add(video_id)

        if video_id in unresolved:
            # Referencing a video the collection will not return would fail the whole render,
            # so the moment is reported instead. It stays in the evidence and in the scene.
            dropped.append({
                "evidence_index": entry["evidence_index"],
                "nasa_id": entry["item"].get("nasa_id"),
                "reason": "source video could not be read from the collection",
                "video_id": video_id,
            })
            continue

        source_length = lengths[video_id]

        start = entry["source_start"]
        duration = entry["duration"]
        clamped = False
        if source_length:
            # Never ask for more footage than the source holds. A scene timestamp can sit at
            # or past the end of its own video when the segmentation and the stored length
            # disagree; rather than dropping the moment, slide the window back to the tail of
            # the clip, which is the nearest real footage, and record that it moved.
            if source_length - start < MIN_CLIP_SECONDS:
                pulled = _floor2(max(source_length - duration, 0.0))
                if pulled < start:
                    start = pulled
                    clamped = True
            duration = _floor2(min(duration, max(source_length - start, 0)))

        # Whole seconds, because `add_clip` places on whole seconds. A 9.6s clip in a 10s slot
        # left 0.4s of background between every shot: a black flash on most cuts, and enough to
        # read as a broken stream rather than an edit.
        #
        # Rounded rather than floored. The window now ends just after a full stop, and flooring
        # a 7.6s sentence to 7s clips the last word; rounding up spends the difference on the
        # pause after it. Re-clamped, because rounding up can pass the end of the source.
        duration = float(round(duration))
        if source_length:
            duration = min(duration, float(int(source_length - start)))

        if duration < 1:
            # Nothing usable in the source at all. Reported rather than silently skipped:
            # the moment still exists in the evidence and still needs a place in the scene.
            dropped.append({
                "evidence_index": entry["evidence_index"],
                "nasa_id": entry["item"].get("nasa_id"),
                "reason": "source too short to cut a clip from",
                "source_length": source_length,
                "source_start": entry["source_start"],
            })
            continue

        at = cursor
        cursor += int(duration)

        video_track.add_clip(at, Clip(
            asset=VideoAsset(id=video_id, start=start),
            duration=duration,
            transition=Transition(in_="fade", out="fade", duration=FADE),
        ))

        if with_captions:
            caption_track.add_clip(at, Clip(
                asset=TextAsset(
                    text=entry["caption"],
                    font=Font(family="Inter", size=22, color="#ffffff"),
                    background=Background(color="#05070d", opacity=0.62),
                    alignment=Alignment(horizontal=HorizontalAlignment.center,
                                        vertical=VerticalAlignment.bottom),
                ),
                duration=duration,
            ))

        shots.append({
            "at": at,
            "duration": duration,
            # Which evidence item this shot is. The reel can be shorter than the evidence
            # list, so every consumer must map through this rather than assume shot i is
            # evidence i: citation [n], the timeline needles, the beacons in the orrery and
            # the camera all key off the evidence index.
            "evidence_index": entry["evidence_index"],
            "clamped": clamped,
            "nasa_id": entry["item"].get("nasa_id"),
            "era_start": entry["item"].get("era_start"),
            "era_axis": entry["item"].get("era_axis"),
            "mission": entry["item"].get("mission"),
            "source_start": start,
            "caption": entry["caption"],
        })

    if not shots:
        return {"stream_url": None, "shots": [], "dropped": dropped,
                "error": "no evidence could be cut into a clip"}

    timeline.add_track(video_track)
    if with_captions:
        timeline.add_track(caption_track)

    stream_url = timeline.generate_stream()
    return {
        "stream_url": stream_url,
        "player_url": getattr(timeline, "player_url", None)
        or f"https://console.videodb.io/player?url={stream_url}",
        "shots": shots,
        "dropped": dropped,
        "total_seconds": sum(s["duration"] for s in shots),
    }
