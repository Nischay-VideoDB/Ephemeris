"""Reel compilation, checked offline.

The regression this guards: the compiler can produce fewer shots than there is evidence, and
for a while nothing recorded which shot was which moment. Every consumer assumed shot i was
evidence i, so one dropped moment shifted the citation targets, the timeline needles, the
beacon colours and the camera by one, silently, for the rest of the answer.

Run with:  python tests/test_reel.py

No pytest dependency and no network: the v2 editor classes are stubbed, so this exercises the
layout arithmetic rather than the render.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import reel  # noqa: E402


class FakeTrack:
    def __init__(self):
        self.clips = []

    def add_clip(self, at, clip):
        self.clips.append((at, clip))


class FakeTimeline:
    def __init__(self, conn):
        self.tracks = []
        self.resolution = None
        self.background = None
        self.player_url = "player://test"

    def add_track(self, track):
        self.tracks.append(track)

    def generate_stream(self):
        return "stream://test"


class FakeVideo:
    def __init__(self, length):
        self.length = length


class FakeCollection:
    """Raises for an unknown id, which is what the real client does."""

    def __init__(self, lengths):
        self.lengths = lengths

    def get_video(self, video_id):
        if video_id not in self.lengths:
            raise KeyError(video_id)
        return FakeVideo(self.lengths[video_id])


reel.Timeline = FakeTimeline
reel.Track = FakeTrack
reel.Clip = lambda **kwargs: kwargs
reel.VideoAsset = lambda **kwargs: kwargs
reel.TextAsset = lambda **kwargs: kwargs
reel.Transition = lambda **kwargs: kwargs


EVIDENCE = [
    {"video_id": "long", "start": 10, "end": 20, "nasa_id": "A", "era_start": 1976,
     "era_axis": "scene", "mission": "Viking"},
    # Starts exactly at the end of its 30s source. A real corpus case: scene segmentation and
    # the stored length disagree. Must slide back to the tail, not vanish.
    {"video_id": "short", "start": 30, "end": 30, "nasa_id": "B", "era_start": 1969,
     "era_axis": "video", "mission": "Apollo"},
    {"video_id": "long", "start": 100, "end": 112, "nasa_id": "C", "era_start": None,
     "era_axis": None, "mission": None},
    # Half a second of source: nothing to cut, must be reported.
    {"video_id": "tiny", "start": 0, "end": 10, "nasa_id": "D", "era_start": 1965,
     "era_axis": "published", "mission": "Mariner"},
    # Not in the collection at all: referencing it would fail the whole render.
    {"video_id": "gone", "start": 0, "end": 10, "nasa_id": "E", "era_start": 1962,
     "era_axis": "published", "mission": "Ranger"},
]


def main() -> None:
    coll = FakeCollection({"long": 600.0, "short": 30.0, "tiny": 0.5})
    out = reel.build(conn=None, coll=coll, evidence=EVIDENCE)

    shots, dropped = out["shots"], out["dropped"]
    for shot in shots:
        print(f"  ev={shot['evidence_index']} at={shot['at']:3d} dur={shot['duration']:5.2f} "
              f"src={shot['source_start']:6.2f} clamped={shot['clamped']} {shot['nasa_id']}")
    for row in dropped:
        print(f"  dropped ev={row['evidence_index']} {row['nasa_id']}: {row['reason']}")

    # Every shot says which moment it is, and the drops do not renumber the survivors.
    assert [s["evidence_index"] for s in shots] == [0, 1, 2], shots
    assert [d["evidence_index"] for d in dropped] == [3, 4], dropped

    # A start past the end of the source moves back into the clip instead of losing the moment.
    assert shots[1]["clamped"] is True
    assert shots[1]["source_start"] == 26.0, shots[1]["source_start"]
    assert shots[0]["clamped"] is False

    # Positions are assigned after the drop decisions, so the stream holds no black gap where a
    # dropped moment would have been.
    cursor, expected = 0, []
    for shot in shots:
        expected.append(cursor)
        cursor += int(math.ceil(shot["duration"]))
    assert [s["at"] for s in shots] == expected, [s["at"] for s in shots]
    assert out["total_seconds"] == sum(s["duration"] for s in shots)

    # Nothing compilable at all is an error, not an empty reel that looks fine.
    empty = reel.build(conn=None, coll=FakeCollection({"tiny": 0.5}), evidence=[EVIDENCE[3]])
    assert empty["stream_url"] is None and empty["error"], empty
    assert [d["evidence_index"] for d in empty["dropped"]] == [0]

    print("\nOK: shot/evidence mapping, clamping, drop reporting, contiguous timeline")


if __name__ == "__main__":
    main()
