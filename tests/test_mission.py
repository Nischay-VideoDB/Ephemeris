"""Mission labels that name the wrong world.

Asked "what were the various missions to explore the moon?", retrieval did its job: seven of
eight moments were lunar. The captions did not. Two lunar scenes were labelled `Mars
Reconnaissance Orbiter`, because the extractor heard "Lunar Reconnaissance Orbiter", and the
compilation clip "1971 Aeronautics and Space Highlights" stamps `Mariner 9` on 62 of its 88
scenes including thirteen of the Moon. The label is on the hover card, burned into the reel
caption, and now chooses the hardware that flies, so lunar footage read as a Mars mission.

The failure to guard against is over-correction. Flyby probes and observatories legitimately
appear anywhere: Voyager at Saturn, Cassini's probe at Titan, Hubble's view of Jupiter are all
correct, and a briefing filmed on Earth about a Mars orbiter is correct too.

Run with:  python tests/test_mission.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import agent  # noqa: E402


# (mission, body, expected mission, why)
CASES = [
    # Bound to one world, seen on another: the label is wrong and goes.
    ("Mariner 9", "moon", None, "Mars orbiter stamped on a lunar scene"),
    ("Mars Reconnaissance Orbiter", "moon", None, "LRO misheard as MRO"),
    ("Juno", "moon", None, "Jupiter orbiter on a lunar scene"),
    ("Mariner 9", "sun", None, "compilation smear onto a solar scene"),
    ("Terra", "mars", None, "Earth observer on a Mars scene"),
    ("Cassini-Huygens", "moon", None, "Saturn mission on a lunar scene"),

    # Legitimate, and must survive.
    ("Voyager 1", "saturn", "Voyager 1", "flyby probe genuinely at Saturn"),
    ("Voyager", "jupiter", "Voyager", "same, at Jupiter"),
    ("Pioneer", "jupiter", "Pioneer", "same"),
    ("Cassini-Huygens", "titan", "Cassini-Huygens", "Titan sits in Saturn's system"),
    ("Hubble Space Telescope", "jupiter", "Hubble Space Telescope", "a telescope images anything"),
    ("SOHO", "comet_asteroid", "SOHO", "SOHO really did discover sungrazing comets"),
    ("OSIRIS-REx", "comet_asteroid", "OSIRIS-REx", "sample return at an asteroid"),
    ("Mariner 9", "earth", "Mariner 9", "a briefing on Earth about a Mars mission"),
    ("Apollo", "ground", "Apollo", "training footage on Earth"),
    ("Mariner 9", "mars", "Mariner 9", "agrees with the scene"),
    ("Apollo", "moon", "Apollo", "agrees with the scene"),
    ("Curiosity", "unknown", "Curiosity", "an unplaced scene cannot contradict anything"),
    (None, "moon", None, "no mission to begin with"),
]


def main() -> None:
    for mission, body, want, why in CASES:
        got, axis = agent.resolve_mission(mission, body)
        assert got == want, f"{mission} on {body}: got {got!r}, wanted {want!r} ({why})"
        assert axis in {"scene", "dropped", "none"}, axis
        if mission and want is None:
            assert axis == "dropped", (mission, axis)
        print(f"  {'dropped' if got is None and mission else 'kept   '}  "
              f"{str(mission)[:28]:28s} on {body:14s}  {why}")

    # Against the real corpus: a correction, not a purge.
    lookup_path = ROOT / "data" / "era_lookup.json"
    if lookup_path.exists():
        lookup = json.loads(lookup_path.read_text())
        scenes = dropped = 0
        for rows in lookup.values():
            dominant, share, counts = agent.body_profile(rows)
            for row in rows:
                body, _ = agent.resolve_body(
                    row.get("celestial_body") or "unknown", dominant, share, counts
                )
                _, axis = agent.resolve_mission(row.get("primary_mission"), body)
                scenes += 1
                dropped += axis == "dropped"
        print(f"\n  corpus: {dropped} of {scenes} scenes lose a label ({dropped / scenes:.1%})")
        assert dropped / scenes < 0.05, "this is meant to correct labels, not strip them"

    print("\nOK: labels naming the wrong world are dropped, flybys and telescopes untouched")


if __name__ == "__main__":
    main()
