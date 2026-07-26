"""Runs of matching cells become one passage.

The corpus is indexed on a ten-second grid, and when a clip genuinely covers a subject
retrieval returns a run of touching cells: one Curiosity clip came back with seventeen of them,
170 seconds unbroken. The diversity cap used to keep exactly one cell per clip and discard the
rest, so an answer was a dozen unrelated ten-second fragments, none long enough to develop a
point. Merging happens before the cap, so what the cap chooses between is passages.

What must not happen: passages swallowing a whole clip, or two unrelated parts of one clip
being welded together because they happen to share a source.

Run with:  python tests/test_passages.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import agent  # noqa: E402


def cell(clip: str, start: float, score: float = 0.5, text: str = "") -> agent.Evidence:
    return agent.Evidence(
        nasa_id=clip, video_id=f"v-{clip}", start=start, end=start + 10.0,
        score=score, index="transcript", query="q", text=text or f"cell at {start:.0f}",
    )


def main() -> None:
    trace = agent.Trace(stream=False)

    evidence = [
        # A continuous run of four: one passage.
        cell("curiosity", 100.0, 0.61), cell("curiosity", 110.0, 0.79),
        cell("curiosity", 120.0, 0.58), cell("curiosity", 130.0, 0.64),
        # Same clip, but minutes away: a separate passage, not welded to the first.
        cell("curiosity", 400.0, 0.55),
        # A lone cell in another clip stays a lone cell.
        cell("odyssey", 70.0, 0.66),
    ]

    passages = agent.build_passages(evidence, trace)
    by_clip = {}
    for p in passages:
        by_clip.setdefault(p.nasa_id, []).append(p)

    curiosity = sorted(by_clip["curiosity"], key=lambda p: p.start)
    assert len(curiosity) == 2, [(p.start, p.end, p.cells) for p in curiosity]

    run = curiosity[0]
    assert (run.start, run.end, run.cells) == (100.0, 140.0, 4), (run.start, run.end, run.cells)
    # The strongest cell gives the passage its score, so the cap ranks it on its best moment.
    assert run.score == 0.79, run.score
    # And its text is the whole passage, not one cell's fragment.
    assert "cell at 100" in run.text and "cell at 130" in run.text, run.text
    print(f"  run of 4      -> [{run.start}-{run.end}] {run.cells} cells, score {run.score}")

    far = curiosity[1]
    assert (far.start, far.end, far.cells) == (400.0, 410.0, 1), (far.start, far.end, far.cells)
    print(f"  distant cell  -> [{far.start}-{far.end}] kept separate")

    lone = by_clip["odyssey"][0]
    assert lone.cells == 1 and lone.end - lone.start == 10.0
    print("  lone cell     -> unchanged")

    # A long run is cut at the budget rather than becoming the whole clip.
    long_run = [cell("mars", 10.0 * i, 0.5) for i in range(1, 18)]
    split = sorted(agent.build_passages(long_run, trace), key=lambda p: p.start)
    assert all(p.end - p.start <= agent.MAX_PASSAGE_SECONDS for p in split), \
        [(p.start, p.end) for p in split]
    assert sum(p.cells for p in split) == 17, [p.cells for p in split]
    print(f"  17-cell run   -> {len(split)} passages, none over {agent.MAX_PASSAGE_SECONDS:.0f}s")

    # A single missing cell in the middle does not break a passage in two; a real gap does.
    gapped = [cell("x", 0.0), cell("x", 20.0), cell("x", 100.0)]
    joined = sorted(agent.build_passages(gapped, trace), key=lambda p: p.start)
    assert len(joined) == 2 and joined[0].cells == 2, [(p.start, p.end, p.cells) for p in joined]
    print("  one gap       -> bridged; a real break -> split")

    print("\nOK: runs become passages, budgets hold, unrelated parts stay apart")


if __name__ == "__main__":
    main()
