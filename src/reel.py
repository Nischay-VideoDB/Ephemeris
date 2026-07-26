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
MAX_CLIP_SECONDS = 12
MIN_CLIP_SECONDS = 4
FADE = 0.4


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _floor2(value: float) -> float:
    return math.floor(value * 100) / 100


def caption_for(item: dict) -> str:
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
    return f"{stamp}  ·  {mission}  ·  NASA {item.get('nasa_id', '')[:44]}"


def plan(evidence: list[dict], max_clip: int = MAX_CLIP_SECONDS) -> list[dict]:
    """Lay the evidence out on an integer-second timeline."""
    layout: list[dict] = []
    cursor = 0
    for item in evidence:
        start = max(0.0, _f(item.get("start")))
        end = _f(item.get("end"), start + MIN_CLIP_SECONDS)
        duration = _floor2(min(max(end - start, MIN_CLIP_SECONDS), max_clip))
        if duration <= 0:
            continue
        layout.append({
            "video_id": item["video_id"],
            "source_start": start,
            "duration": duration,
            "at": cursor,
            "caption": caption_for(item),
            "item": item,
        })
        cursor += int(math.ceil(duration))
    return layout


def build(conn, coll, evidence: list[dict], *, max_clip: int = MAX_CLIP_SECONDS,
          with_captions: bool = True) -> dict:
    """Render the reel and return its stream URL plus the shot list."""
    layout = plan(evidence, max_clip=max_clip)
    if not layout:
        return {"stream_url": None, "shots": [], "error": "no evidence to compile"}

    lengths: dict[str, float] = {}
    timeline = Timeline(conn)
    timeline.resolution = RESOLUTION
    timeline.background = BACKGROUND

    video_track = Track()
    caption_track = Track()
    shots: list[dict] = []

    for entry in layout:
        video_id = entry["video_id"]
        if video_id not in lengths:
            lengths[video_id] = _f(coll.get_video(video_id).length)
        source_length = lengths[video_id]

        start = entry["source_start"]
        duration = entry["duration"]
        if source_length:
            # Never ask for more footage than the source holds.
            duration = _floor2(min(duration, max(source_length - start, 0)))
        if duration < 1:
            continue

        video_track.add_clip(entry["at"], Clip(
            asset=VideoAsset(id=video_id, start=start),
            duration=duration,
            transition=Transition(in_="fade", out="fade", duration=FADE),
        ))

        if with_captions:
            caption_track.add_clip(entry["at"], Clip(
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
            "at": entry["at"],
            "duration": duration,
            "nasa_id": entry["item"].get("nasa_id"),
            "era_start": entry["item"].get("era_start"),
            "era_axis": entry["item"].get("era_axis"),
            "mission": entry["item"].get("mission"),
            "source_start": start,
            "caption": entry["caption"],
        })

    timeline.add_track(video_track)
    if with_captions:
        timeline.add_track(caption_track)

    stream_url = timeline.generate_stream()
    return {
        "stream_url": stream_url,
        "player_url": getattr(timeline, "player_url", None)
        or f"https://console.videodb.io/player?url={stream_url}",
        "shots": shots,
        "total_seconds": sum(s["duration"] for s in shots),
    }
