"""Where a moment is placed in space, and where that placement came from.

The scene-level extractor tags one scene of a four-scene Moon flyover as `comet_asteroid`,
and leaves 49 scenes across the corpus tagged `unknown`. In a spatial interface both are
visible errors: the camera flies to the wrong world, or parks the moment in a void labelled
"unplaced". `resolve_body` overrules the scene only where the clip around it is unambiguous,
and records that it did.

What must NOT happen is over-correction. A Titan scene inside a Cassini-at-Saturn clip, a
briefing on Earth inside a Mars clip, and a single Mars scene inside an Earth-heavy clip are
all ordinary, and reassigning any of them would be the error this guards against.

Run with:  python tests/test_body.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import agent  # noqa: E402


# (scene body, dominant body, share, counts, expected body, expected axis, why)
CASES = [
    ("comet_asteroid", "moon", 3 / 4, {"comet_asteroid": 1, "moon": 3}, "moon", "video",
     "lone outlier in a clip that is plainly about the Moon"),
    ("unknown", "mars", 6 / 8, {"unknown": 2, "mars": 6}, "mars", "video",
     "scene says nowhere, clip says Mars"),
    ("deep_space", "sun", 30 / 33, {"sun": 30, "deep_space": 1, "earth_orbit": 2}, "sun", "video",
     "one deep-space frame in 33 scenes of the Sun"),

    ("titan", "saturn", 7 / 8, {"saturn": 7, "titan": 1}, "titan", "scene",
     "Titan orbits Saturn: a Titan scene in a Saturn clip is right, not an outlier"),
    ("moon", "earth", 9 / 10, {"earth": 9, "moon": 1}, "moon", "scene",
     "same, for the Moon in an Earth clip"),
    ("ground", "moon", 10 / 17, {"moon": 10, "ground": 3, "earth": 1, "earth_orbit": 2, "unknown": 1},
     "ground", "scene", "Earth-based footage about elsewhere is ordinary, and not dominant here"),
    ("mars", "earth", 7 / 10, {"earth": 7, "mars": 1, "moon": 2}, "mars", "scene",
     "Earth never overrules: the archive is made on Earth"),
    ("sun", "sun", 11 / 13, {"sun": 11, "earth_orbit": 1, "earth": 1}, "sun", "scene",
     "agrees with the clip already"),
    ("deep_space", "mars", 2 / 4, {"mars": 2, "deep_space": 2}, "deep_space", "scene",
     "a genuinely mixed clip keeps every tag it was given"),
    ("unknown", "unknown", 1.0, {"unknown": 3}, "unknown", "scene",
     "nothing to fall back to"),
    ("comet_asteroid", "mars", 8 / 10, {"mars": 8, "comet_asteroid": 2}, "comet_asteroid", "scene",
     "two of a kind is a subject, not a slip"),
]


def main() -> None:
    for body, dominant, share, counts, want_body, want_axis, why in CASES:
        got = agent.resolve_body(body, dominant, share, counts)
        assert got == (want_body, want_axis), f"{body} in {dominant}: {got} != {(want_body, want_axis)} ({why})"
        moved = "->" if got[0] != body else "  "
        print(f"  {body:15s} in {dominant:15s} {moved} {got[0]:15s} ({got[1]:5s})  {why}")

    # The profile has to agree with itself: dominant is the most common body, share its fraction.
    dominant, share, counts = agent.body_profile(
        [{"celestial_body": "mars"}, {"celestial_body": "mars"}, {"celestial_body": "earth"}]
    )
    assert (dominant, counts) == ("mars", {"mars": 2, "earth": 1}), (dominant, counts)
    assert abs(share - 2 / 3) < 1e-9, share
    assert agent.body_profile([]) == ("unknown", 0.0, {})

    # Against the real corpus, if it has been built: the pass must stay a correction, not a
    # rewrite. Anything approaching a wholesale reassignment means the rule has gone wrong.
    lookup_path = ROOT / "data" / "era_lookup.json"
    if lookup_path.exists():
        lookup = json.loads(lookup_path.read_text())
        scenes = moved = 0
        for rows in lookup.values():
            dom, share, counts = agent.body_profile(rows)
            for row in rows:
                before = row.get("celestial_body") or "unknown"
                scenes += 1
                if agent.resolve_body(before, dom, share, counts)[0] != before:
                    moved += 1
        print(f"\n  corpus: {moved} of {scenes} scenes reassigned ({moved / scenes:.1%})")
        assert moved / scenes < 0.05, "the rule is rewriting the corpus, not correcting it"

    print("\nOK: outliers and unplaced scenes resolved, satellites and Earth left alone")


if __name__ == "__main__":
    main()
