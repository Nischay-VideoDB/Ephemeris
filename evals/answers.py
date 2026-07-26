"""Answer quality gate.

`evals/run.py` scores retrieval: whether the right moments come back. This scores what is
built on top of them, because a run can retrieve well and still answer badly. Every check
here comes from a failure seen in a real run:

  cited        Evidence that no sentence refers to still appears in the reel, so the viewer
               watches footage the answer never explains. One run cited 2 of 8 moments and
               played all eight.
  grounded     Every claim must carry a citation. An uncited sentence is the model's own
               knowledge, which is exactly what this archive is meant to replace.
  on_setting   When the plan names a world, the moments should be set there. Asked about the
               Moon, the answer once included Titan and Mars.
  snapped      Clips cut to sentence bounds rather than left on the ten-second indexing grid,
               which cuts speech mid-word.
  spread       Clip lengths must vary. Every clip landing on the same duration means the grid
               decided them, not the speech.
  chronology   A question about change over time needs more than one dated point.

Scores existing runs from a directory of result JSON, so it can grade a sweep without
spending a single API call:

    python evals/answers.py <dir-of-result-json>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import agent  # noqa: E402

# A run that answers fewer than this share of its own evidence is padding the reel.
MIN_CITED = 0.75
# Sentences carrying a factual claim but no citation.
MAX_UNGROUNDED = 0
# Clips still sitting on the indexing grid rather than on speech.
MIN_SNAPPED = 0.6

# Openers that frame the evidence rather than assert anything about the subject, so they
# need no citation of their own.
FRAMING = re.compile(
    r"^\s*(the\s+)?(archive|clips?|footage|evidence|provided|these|those|together|taken\s+"
    r"together|neither|none|no\s+clip)\b", re.I
)


def cited_set(answer: dict) -> set[int]:
    used = set(answer.get("citations") or [])
    for point in answer.get("chronology") or []:
        used.update(point.get("citations") or [])
    return used


# A full stop only ends a sentence when what precedes it is not an initial. Splitting naively
# cut "Mary W. Jackson is shown as an engineer ... [4][7]" in two and reported the first half
# as an uncited claim about a named person, which is the one thing this check exists to catch.
SENTENCE_END = re.compile(r"(?<!\b[A-Z]\.)(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")


def ungrounded_sentences(text: str) -> list[str]:
    """Sentences that assert something and carry no [n]."""
    out = []
    for sentence in SENTENCE_END.split(text or ""):
        sentence = sentence.strip()
        if len(sentence.split()) < 6 or FRAMING.match(sentence):
            continue
        # Citations come back both as [1][2] and as [1, 2]; either is a citation.
        if not re.search(r"\[\s*\d", sentence):
            out.append(sentence)
    return out


def grade(result: dict) -> dict:
    plan = result.get("plan") or {}
    answer = result.get("answer") or {}
    evidence = result.get("evidence") or []
    reel = result.get("reel") or {}
    kinds = {step.get("kind") for step in result.get("trace") or []}

    refused = "coverage" in kinds or not plan.get("answerable", True)
    if refused:
        # A refusal is a good answer when it says why and shows nothing.
        checks = {
            "refusal_explained": bool(answer.get("caveats")),
            "refusal_shows_nothing": not evidence,
        }
        return {"refused": True, "checks": checks, "metrics": {},
                "failed": [k for k, ok in checks.items() if not ok]}

    used = cited_set(answer)
    coverage = len(used & set(range(1, len(evidence) + 1))) / len(evidence) if evidence else 0.0
    ungrounded = ungrounded_sentences(answer.get("answer") or "")

    target = plan.get("target_body")
    on_setting = (
        sum(1 for e in evidence if agent.in_system(e.get("celestial_body"), target)) / len(evidence)
        if target and evidence else None
    )
    # A low share is only a fault if on-topic material was available and passed over. Asked what
    # asteroid missions returned, retrieval surfaced five asteroid clips and the preference kept
    # every one of them; the remaining slots going to Apollo sample-return footage is the
    # preference working as intended. What must never happen is an on-topic moment dropped while
    # something off-topic stayed, so this counts only when a slot went off-target.
    passed_over = [
        row for row in (result.get("rejected") or {}).get("diversity") or []
        if agent.in_system(row.get("celestial_body"), target)
    ] if target and on_setting is not None and on_setting < 1.0 else []

    snapped = (
        sum(1 for e in evidence if e.get("clip_axis") == "sentence") / len(evidence)
        if evidence else 0.0
    )
    lengths = [round(e["end"] - e["start"], 1) for e in evidence]
    spread = len(set(lengths))

    chronology = answer.get("chronology") or []
    metrics = {
        "moments": len(evidence),
        "cited": round(coverage, 2),
        "ungrounded": len(ungrounded),
        "on_setting": None if on_setting is None else round(on_setting, 2),
        "passed_over": len(passed_over),
        "snapped": round(snapped, 2),
        "distinct_lengths": spread,
        "chronology_points": len(chronology),
        "shots": len(reel.get("shots") or []),
    }
    checks = {
        "has_answer": bool((answer.get("answer") or "").strip()),
        "cited": coverage >= MIN_CITED,
        "grounded": len(ungrounded) <= MAX_UNGROUNDED,
        "snapped": snapped >= MIN_SNAPPED,
        "varied_lengths": spread > 1,
        "on_setting": on_setting is None or on_setting >= 0.75 or not passed_over,
        "chronology": (not plan.get("needs_chronology")) or len(chronology) >= 2,
    }
    return {"refused": False, "checks": checks, "metrics": metrics,
            "failed": [k for k, ok in checks.items() if not ok],
            "ungrounded_text": ungrounded[:3]}


def main() -> None:
    where = Path(sys.argv[1] if len(sys.argv) > 1 else "data/answers")
    files = sorted(where.glob("*.json"))
    if not files:
        sys.exit(f"no result json under {where}")

    rows, failures = [], 0
    for path in files:
        result = json.loads(path.read_text())
        if "plan" not in result:
            continue
        report = grade(result)
        rows.append((path.stem, result.get("question", ""), report))
        failures += bool(report["failed"])

    print(f"{'run':22s} {'cite':>5s} {'ungr':>5s} {'set':>5s} {'snap':>5s} {'len':>4s} {'chr':>4s}  failed")
    print("─" * 100)
    for stem, question, report in rows:
        if report["refused"]:
            state = "REFUSED" if not report["failed"] else "REFUSED (bad)"
            print(f"{stem[:22]:22s} {state:>34s}  {','.join(report['failed'])}")
            continue
        m = report["metrics"]
        setting = "-" if m["on_setting"] is None else f"{m['on_setting']:.2f}"
        if m["passed_over"]:
            setting += f"!{m['passed_over']}"
        print(f"{stem[:22]:22s} {m['cited']:>5.2f} {m['ungrounded']:>5d} "
              f"{setting:>7s} {m['snapped']:>5.2f} "
              f"{m['distinct_lengths']:>4d} {m['chronology_points']:>4d}  "
              f"{','.join(report['failed'])}")

    print("─" * 100)
    print(f"{len(rows) - failures}/{len(rows)} runs clean")
    for stem, _, report in rows:
        for text in report.get("ungrounded_text") or []:
            print(f"  ungrounded  {stem[:20]:20s} {text[:96]}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
