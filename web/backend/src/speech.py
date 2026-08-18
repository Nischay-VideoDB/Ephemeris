"""Snap a clip to what was said, not to the grid it was indexed on.

The corpus was segmented on a fixed ten-second grid (`understanding.DEFAULT_SEGMENTATION`),
chosen because shot detection on archival footage was unusable. That decision is good for
retrieval and bad for playback: a cell boundary falls wherever ten seconds happens to land, so
a clip begins `season as they pass on Mars` and ends halfway through the next thought, while
carrying whatever else shared the cell.

Word-level timing is available from `video.get_transcript()`, so the cut does not have to obey
the grid. Given a cell and the words around it, this finds the sentences the cell actually sits
in and returns their bounds:

  - a cell that opens mid-sentence reaches back to where that sentence began, when it began
    recently enough to be the same thought
  - when it did not, the clip starts at the next sentence instead, rather than dragging in a
    long preamble about something else
  - the same on the other end, so the clip stops on a full stop instead of a syllable

A cell with no speech under it is left alone: nothing here can improve a visual match, and
inventing a boundary would be worse than the honest grid edge.
"""

from __future__ import annotations

import re
from typing import Any

# A word that ends a sentence. The quote forms matter: narration is full of "...built it."
SENTENCE_END = re.compile(r"[.!?]['\"”’]?$")

# Reaching back further than this to complete a sentence stops being context and starts being a
# different subject, so the clip begins at the next sentence instead.
MAX_REACH_BACK = 5.0
# Forward is more generous: the sentence the cell is in is the one that matched, and stopping
# mid-clause is the failure being fixed. Narration sentences in this archive run long, and at
# seven seconds clips were still ending on "like Humphrey" and "future infrared".
MAX_REACH_FORWARD = 12.0

# Speech either side of a cell is only the same thought if it is continuous. A gap this long is
# a new statement even without punctuation, which archival transcripts often lack.
GAP_SECONDS = 0.9

# Breathing room, so a cut does not clip the first consonant or the final plosive.
LEAD_IN = 0.20
TAIL = 0.35

# No spoken word lasts this long. Recognition over a near-silent clip emits tokens that span
# whole minutes: one timelapse in this archive transcribes as exactly two "words", `Sam,` at
# 0.24-31.91s and `it's.` at 32.06-63.81s. Believing those put a 47-second clip in an answer
# whose entire spoken content was the word "Sam". A token this long is an artefact, not speech,
# and must not be allowed to set a clip boundary.
MAX_WORD_SECONDS = 3.0

# Snapping adjusts the edges of a passage. It must never replace one. A thirty-second run of
# visually matched cells containing a single stray token ("Sa.") was being cut down to four
# seconds of that syllable, throwing away the footage the passage was actually retrieved for.
# Below this much speech, or this much of the original span, the grid bounds are the honest
# answer and the moment is left on them.
MIN_SPOKEN_WORDS = 5
MIN_COVERAGE = 0.6


def load_words(video) -> list[dict]:
    """Timed words for one video, or an empty list when it carries no speech."""
    try:
        transcript = video.get_transcript()
    except Exception:  # noqa: BLE001 - a clip with no audio is normal in this archive
        return []

    words: list[dict] = []
    for row in transcript or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        start, end = row.get("start"), row.get("end")
        if not text or start is None or end is None:
            continue
        try:
            start, end = float(start), float(end)
        except (TypeError, ValueError):
            continue
        if end <= start or end - start > MAX_WORD_SECONDS:
            continue
        words.append({"start": start, "end": end, "text": text})

    words.sort(key=lambda w: w["start"])
    return words


def _ends_sentence(word: dict) -> bool:
    return bool(SENTENCE_END.search(word["text"]))


def sentence_window(
    words: list[dict],
    start: float,
    end: float,
    *,
    min_seconds: float,
    max_seconds: float,
    source_length: float = 0.0,
) -> tuple[float, float, str, str]:
    """Return `(start, end, axis, text)` for the clip that should actually play.

    `axis` is `sentence` when speech decided the bounds and `scene` when the grid cell was kept,
    so nothing downstream has to guess which it is looking at.
    """
    inside = [i for i, w in enumerate(words) if w["end"] > start and w["start"] < end]
    if not inside:
        return start, end, "scene", ""

    first, last = inside[0], inside[-1]

    # Back to the start of the sentence this cell opens in, if that is close enough to still be
    # the same thought. Otherwise begin at the next sentence and let the fragment go.
    left = first
    while left > 0:
        previous = words[left - 1]
        if _ends_sentence(previous):
            break
        if words[left]["start"] - previous["end"] > GAP_SECONDS:
            break
        if start - previous["start"] > MAX_REACH_BACK:
            # Too far back to justify. Trim forward to the first word of the next sentence
            # inside the cell instead, when there is one.
            forward = next(
                (i + 1 for i in inside[:-1] if _ends_sentence(words[i])),
                None,
            )
            left = forward if forward is not None else first
            break
        left -= 1

    # Forward to the end of the sentence the cell closes in.
    right = last
    while right < len(words) - 1 and not _ends_sentence(words[right]):
        following = words[right + 1]
        if following["start"] - words[right]["end"] > GAP_SECONDS:
            break
        if following["end"] - end > MAX_REACH_FORWARD:
            break
        right += 1

    if right < left:
        return start, end, "scene", ""

    # The sentence still did not finish inside the reach. Rather than ending on a syllable, back
    # up to the last full stop in the window, as long as that leaves a clip worth playing.
    if not _ends_sentence(words[right]):
        stop = next((i for i in range(right, left - 1, -1) if _ends_sentence(words[i])), None)
        if stop is not None:
            trimmed = words[stop]["end"] + TAIL
            span = trimmed - max(0.0, words[left]["start"] - LEAD_IN)
            if span >= min_seconds and span >= MIN_COVERAGE * (end - start):
                right = stop

    new_start = max(0.0, words[left]["start"] - LEAD_IN)
    new_end = words[right]["end"] + TAIL

    if source_length:
        new_end = min(new_end, source_length)

    if new_end - new_start > max_seconds:
        # Hitting the ceiling must not put the cut back in the middle of a clause, which is the
        # whole failure being fixed here. End on the last full stop that fits instead, and only
        # cut hard if the budget does not contain one.
        budget = new_start + max_seconds
        stop = next(
            (
                words[i]["end"] + TAIL
                for i in range(right, left - 1, -1)
                if _ends_sentence(words[i]) and words[i]["end"] + TAIL <= budget
            ),
            None,
        )
        new_end = stop if stop is not None and stop - new_start >= min_seconds else budget
        right = next(
            (i for i in range(right, left - 1, -1) if words[i]["end"] + TAIL <= new_end),
            left,
        )

    if new_end - new_start < min_seconds:
        new_end = new_start + min_seconds
        if source_length and new_end > source_length:
            new_end = source_length
            new_start = max(0.0, new_end - min_seconds)

    spoken = " ".join(words[i]["text"] for i in range(left, right + 1))

    # A passage that is mostly pictures keeps the bounds it was retrieved with. Speech decides
    # the cut only when there is speech to decide it. Coverage is measured against what the
    # window was ever allowed to be, so a passage longer than the ceiling is not read as a
    # shrink; and the fallback obeys that ceiling too.
    target = min(end - start, max_seconds)
    covered = (new_end - new_start) / max(target, 1e-6)
    if len(spoken.split()) < MIN_SPOKEN_WORDS or covered < MIN_COVERAGE:
        return start, min(end, start + max_seconds), "scene", ""

    return round(new_start, 2), round(new_end, 2), "sentence", spoken


def refine(video, item: dict, *, min_seconds: float, max_seconds: float,
           words: list[dict] | None = None) -> dict[str, Any]:
    """Convenience wrapper: fetch the words if they were not supplied, then snap one cell."""
    if words is None:
        words = load_words(video)
    length = 0.0
    try:
        length = float(video.length or 0.0)
    except (TypeError, ValueError):
        length = 0.0

    start, end, axis, spoken = sentence_window(
        words, float(item["start"]), float(item["end"]),
        min_seconds=min_seconds, max_seconds=max_seconds, source_length=length,
    )
    return {"start": start, "end": end, "clip_axis": axis, "spoken": spoken}
