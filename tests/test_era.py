"""Dates a mission could not possibly have been part of.

A refreshed reel captioned one shot "1990 · Curiosity". Curiosity landed in 2012, so the
moment sorted before Hubble on a timeline whose whole purpose is ordering the archive by when
things happened. The year had not been read from the scene at all: the extractor found no date
there and fell back to the clip as a whole, and a compilation dated once at the top hands that
year to every scene beneath it.

The failure to guard against is overwriting a real date. Archive footage is full of
retrospect, and a scene that says "Viking landed in 1976" while a Perseverance clip plays is
correct. Only inferred dates are open to correction; a date the scene stated is left alone.

Run with:  python tests/test_era.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import agent  # noqa: E402


# (era_start, era_axis, mission, expected era, expected axis, why)
CASES = [
    # Inferred and impossible: the window wins.
    (1990, "video", "Curiosity", 2011, "mission", "rover dated 21 years before it launched"),
    (1961, "video", "Mariner 9", 1971, "mission", "compilation's own year, not the mission's"),
    (1965, "published", "Hubble Space Telescope", 1990, "mission", "telescope predates itself"),
    (2004, "video", "Apollo", 1975, "mission", "clamps down to the near bound, not up"),
    (1958, "video", "Perseverance", 2020, "mission", "far end of the archive"),

    # Inferred and possible: untouched.
    (1971, "video", "Mariner 9", 1971, "video", "inside the window"),
    (1969, "video", "Apollo", 1969, "video", "inside the window"),
    (2015, "published", "Curiosity", 2015, "published", "inside the window"),

    # Stated in the scene: never overruled, however odd it looks.
    (1976, "scene", "Perseverance", 1976, "scene", "a modern clip recounting Viking"),
    (1961, "scene", "Mariner 9", 1961, "scene", "the scene said so"),

    # Nothing to check against.
    (1990, "video", None, 1990, "video", "no mission"),
    (1990, "video", "unknown", 1990, "video", "unrecognised mission"),
    (None, "video", "Curiosity", None, "video", "undated"),
]


def main() -> None:
    for era, axis, mission, want_era, want_axis, why in CASES:
        got_era, got_axis, note = agent.resolve_era(era, axis, mission)
        assert got_era == want_era, f"{mission} {era} ({axis}): got {got_era}, wanted {want_era} ({why})"
        assert got_axis == want_axis, f"{mission} {era}: axis {got_axis}, wanted {want_axis} ({why})"
        assert (note is not None) == (got_axis == "mission"), (mission, era, note)
        moved = f"-> {got_era}" if got_era != era else "kept"
        print(f"  {str(mission)[:24]:24s} {str(era):>5s} ({axis:9s}) {moved:>9s}  {why}")

    # Against the real corpus: how much of the archive's dating this touches.
    lookup = agent.load_era_lookup()
    if lookup:
        total = corrected = 0
        axes: Counter = Counter()
        for rows in lookup.values():
            dominant, share, counts = agent.body_profile(rows)
            for row in rows:
                body, _ = agent.resolve_body(row.get("celestial_body") or "unknown",
                                             dominant, share, counts)
                mission, _ = agent.resolve_mission(row.get("primary_mission"), body)
                era, axis, note = agent.resolve_era(row.get("era_start"), row.get("era_axis"),
                                                    mission)
                total += 1
                axes[axis] += 1
                corrected += note is not None
        print(f"\n  corpus: {corrected} of {total} scenes re-dated ({corrected / total:.1%})")
        print(f"  axes: {dict(axes)}")
        assert corrected / total < 0.25, "this corrects impossible dates, not most of them"
        # The correction must never be the commonest source of a date.
        assert axes["mission"] < axes["scene"], "inferred dates should not outnumber stated ones"

    print("\nOK: impossible dates move into the mission's window, stated dates are left alone")


if __name__ == "__main__":
    main()
