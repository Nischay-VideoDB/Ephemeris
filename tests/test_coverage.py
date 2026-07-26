"""Worlds the archive does not hold.

Asked "how did NASA explore Venus?", the archive answered. It returned Artemis reentry
footage and a Mars descent animation, then reasoned that their "clear focus on atmospheric
entry and parachute descent implies NASA employed entry-and-descent engineering ... including
Venus", while conceding in the same answer that neither clip shows Venus. There are zero Venus
scenes in the corpus and one passing mention in 87 clips, of Mariner 10 using Venus for a
gravity assist.

Two guards already existed and neither could catch it. `answerable` runs before retrieval and
is right to pass: Venus is plainly spaceflight. The target-body preference in `diversify` is a
preference rather than a filter, deliberately, so that a thin subject fills its slots instead
of silently shrinking; with nothing on the target it falls back to score. Only the corpus can
say the subject is absent, so that is what is asked here.

Run with:  python tests/test_coverage.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import agent  # noqa: E402
import schema  # noqa: E402


def main() -> None:
    lookup = agent.load_era_lookup()
    if not lookup:
        print("no era_lookup.json, skipping")
        return

    coverage = agent.body_coverage(lookup)
    total = sum(coverage.values())
    for body, count in sorted(coverage.items(), key=lambda kv: -kv[1]):
        print(f"  {body:16s} {count:5d}")
    assert total == sum(len(rows) for rows in lookup.values()), "every scene must be counted"

    # What the guard refuses on. Venus and Mercury are the only targetable worlds with nothing:
    # if a Venus clip is ever added, this assertion is the thing that says so.
    absent = {b for b in schema.CELESTIAL_BODIES
              if b not in agent.NEVER_TARGETED and not coverage.get(b)}
    assert absent == {"venus", "mercury"}, f"corpus coverage changed: absent = {absent}"

    # And what it must not refuse on: a thin world is still a covered world. Jupiter has 22
    # scenes against Mars's 227, and a Jupiter question has to survive the guard and reach
    # retrieval, where the preference does its job.
    for body in ("jupiter", "titan", "saturn", "moon", "comet_asteroid"):
        assert coverage.get(body), f"{body} is covered and must not be refused"
    assert coverage["titan"] < 20, "titan is deliberately thin, and still answerable"

    print(f"\n  {total} scenes across {len(coverage)} bodies; refuses on {sorted(absent)}")
    print("OK: absent worlds are refusable, thin ones are not")


if __name__ == "__main__":
    main()
