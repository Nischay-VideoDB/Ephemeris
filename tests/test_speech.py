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

    # Recognition over a near-silent clip emits tokens spanning half a minute. Believing them
    # put a 47-second shot in an answer whose whole spoken content was the word "Sam".
    class FakeVideo:
        def get_transcript(self):
            return [
                {"text": "Sam,", "start": 0.24, "end": 31.91},
                {"text": "it's.", "start": 32.06, "end": 63.81},
                {"text": "real", "start": 64.0, "end": 64.4},
                {"text": "words.", "start": 64.4, "end": 65.0},
                {"text": "backwards", "start": 70.0, "end": 69.0},   # end before start
            ]

    kept = speech.load_words(FakeVideo())
    assert [w["text"] for w in kept] == ["real", "words."], kept
    print(f"  bad tokens         dropped, {len(kept)} real words kept")

    # With nothing usable left, the cell stays on the grid instead of being stretched to fit
    # an artefact. A silent clip is a visual match and has no sentence to snap to.
    class SilentVideo:
        def get_transcript(self):
            return [{"text": "Sam,", "start": 0.24, "end": 31.91}]

    silent = speech.load_words(SilentVideo())
    assert silent == []
    assert speech.sentence_window(silent, 0.0, 30.0, **BOUNDS) == (0.0, 30.0, "scene", "")
    print("  all-artefact clip  left on the grid, not stretched")

    # A run of visually matched cells with one stray token in it is a passage of pictures, not
    # of speech. Snapping to that token cut thirty seconds of footage down to four.
    stray = [word("Sa.", 12.0, 12.4)]
    assert speech.sentence_window(stray, 0.0, 30.0, min_seconds=4, max_seconds=40) == \
        (0.0, 30.0, "scene", "")
    # The fallback still obeys the ceiling rather than handing back a window over budget.
    assert speech.sentence_window(stray, 0.0, 30.0, **BOUNDS) == (0.0, 18.0, "scene", "")
    print("  stray token        passage kept, not cut down to the syllable")

    # But a short complete sentence filling its cell is still real speech and still snaps.
    short = [word("Water", 10.2, 10.6), word("once", 10.6, 11.0), word("flowed", 11.0, 11.5),
             word("across", 11.5, 12.0), word("this", 12.0, 12.3), word("plain.", 12.3, 13.0)]
    _, _, axis, spoken = speech.sentence_window(short, 10.0, 14.0, **BOUNDS)
    assert axis == "sentence" and spoken.endswith("plain."), (axis, spoken)
    print("  short sentence     still snaps")

    # When the sentence runs on past what the reach allows, back up to the last full stop rather
    # than ending on a syllable: clips were closing on "like Humphrey" and "future infrared".
    # A passage of narration that closes cleanly, followed by a sentence too long to finish
    # inside the reach: the clip should end on the full stop, not partway into the next thought.
    runs_on = [word(f"w{i}", i * 0.5, i * 0.5 + 0.45) for i in range(30)]
    runs_on.append(word("here.", 15.0, 15.6))
    runs_on += [word(f"x{i}", 16.0 + i * 0.4, 16.0 + i * 0.4 + 0.35) for i in range(80)]
    _, end, axis, spoken = speech.sentence_window(runs_on, 0.0, 20.0, min_seconds=4, max_seconds=45)
    assert axis == "sentence" and spoken.rstrip().endswith("here."), (axis, spoken[-40:])
    print(f"  unfinishable       backs up to the last full stop at {end}s")

    print("\nOK: cells snap to sentences, silence and run-ons left alone, bounds respected")


if __name__ == "__main__":
    main()
