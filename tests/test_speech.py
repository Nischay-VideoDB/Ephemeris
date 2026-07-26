"""Clip bounds, checked offline.

The corpus is indexed on a fixed ten-second grid, so a retrieved cell opens and closes wherever
ten seconds happened to land: clips began mid-clause ("season as they pass on Mars") and carried
whatever else shared the cell. `sentence_window` moves the cut onto sentence boundaries using
word timings.

The failure mode to guard against is over-reach. Completing a sentence is context; running back
through a paragraph to find a full stop is a different subject, and a clip that quietly starts
somewhere else is worse than one that starts a beat late.

Run with:  python tests/test_speech.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import speech  # noqa: E402


def word(text: str, start: float, end: float) -> dict:
    return {"text": text, "start": start, "end": end}


# "Over its three years the spacecraft observed every season. Aware of this, scientists watch
#  for changes."   ... then, much later and unrelated: "Unrelated later topic."
NARRATION = [
    word("Over", 60.0, 60.3), word("its", 60.3, 60.5), word("three", 60.5, 60.9),
    word("years", 60.9, 61.3), word("the", 61.3, 61.5), word("spacecraft", 61.5, 62.2),
    word("observed", 62.2, 62.8), word("every", 62.8, 63.1), word("season.", 63.1, 63.9),
    word("Aware", 64.5, 64.9), word("of", 64.9, 65.0), word("this,", 65.0, 65.4),
    word("scientists", 65.4, 66.1), word("watch", 66.1, 66.5), word("for", 66.5, 66.7),
    word("changes.", 66.7, 67.5),
    word("Unrelated", 80.0, 80.6), word("later", 80.6, 81.0), word("topic.", 81.0, 81.6),
]

BOUNDS = {"min_seconds": 4, "max_seconds": 18}


def main() -> None:
    # A cell that opens mid-sentence reaches back to where the sentence began, and forward to
    # the full stop it was cut off before.
    start, end, axis, spoken = speech.sentence_window(NARRATION, 63.0, 66.0, **BOUNDS)
    assert axis == "sentence", axis
    assert spoken.startswith("Over its three years"), spoken
    assert spoken.endswith("changes."), spoken
    assert start < 63.0 and end > 66.0, (start, end)
    print(f"  mid-sentence cell  [63.0-66.0] -> [{start}-{end}]  {spoken[:58]}…")

    # Silence under the cell leaves the grid bounds alone rather than inventing a boundary.
    assert speech.sentence_window(NARRATION, 100.0, 110.0, **BOUNDS) == (100.0, 110.0, "scene", "")
    print("  silent cell        left on the grid")

    # A run-on with no punctuation must not walk back through the whole clip looking for one.
    run_on = [word(f"w{i}", i * 0.5, i * 0.5 + 0.4) for i in range(40)] + [word("end.", 20.0, 20.4)]
    start, _, _, _ = speech.sentence_window(run_on, 18.0, 20.0, **BOUNDS)
    assert start >= 18.0 - speech.MAX_REACH_BACK, start
    print(f"  run-on             reached back to {start}, not past {18.0 - speech.MAX_REACH_BACK}")

    # A pause is a sentence break even when the transcript carries no punctuation, which is
    # common in this archive.
    gapped = [word("first", 10.0, 10.4), word("statement", 10.4, 11.0),
              word("second", 13.0, 13.5), word("statement", 13.5, 14.2)]
    _, _, _, spoken = speech.sentence_window(gapped, 13.2, 14.0, **BOUNDS)
    assert "first" not in spoken, spoken
    print("  pause              treated as a break")

    # The window never runs past the end of the source, and never comes back inverted.
    start, end, _, _ = speech.sentence_window(
        NARRATION, 66.0, 67.0, source_length=67.2, **BOUNDS,
    )
    assert end <= 67.2 and end > start, (start, end)
    print(f"  short source       clamped to [{start}-{end}]")

    # The ceiling holds even when the sentence runs long.
    long_sentence = [word(f"w{i}", i * 0.4, i * 0.4 + 0.35) for i in range(120)]
    start, end, _, _ = speech.sentence_window(long_sentence, 10.0, 20.0, **BOUNDS)
    assert end - start <= BOUNDS["max_seconds"] + 1e-6, end - start
    print(f"  long sentence      capped at {round(end - start, 2)}s")

    # Hitting the ceiling must still land on a full stop when one fits, rather than putting the
    # cut back mid-clause, which is the failure this whole module exists to fix.
    long_passage = []
    for s in range(6):
        base = s * 8.0
        long_passage += [
            word("this", base, base + 0.4), word("is", base + 0.5, base + 0.9),
            word("statement", base + 1.0, base + 1.8),
            word(f"number{s}.", base + 2.0, base + 3.0),
        ]
    start, end, _, spoken = speech.sentence_window(
        long_passage, 0.0, 40.0, min_seconds=4, max_seconds=20,
    )
    assert end - start <= 20 + 1e-6, end - start
    assert spoken.rstrip().endswith("."), spoken
    print(f"  ceiling reached    still ends on a full stop: …{spoken[-24:]!r}")

    print("\nOK: cells snap to sentences, silence and run-ons left alone, bounds respected")


if __name__ == "__main__":
    main()
