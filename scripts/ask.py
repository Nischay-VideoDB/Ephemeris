"""Ask the archive a question.

    python scripts/ask.py "Trace how our understanding of water on Mars changed over time"
    python scripts/ask.py --preset water-mars
    python scripts/ask.py --json out.json "..."

Prints the reasoning trace, the cited answer, and the evidence in chronological order,
plus a playable stream of the compiled evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import agent  # noqa: E402
import manifest  # noqa: E402
import reel  # noqa: E402
import videodb_client as vc  # noqa: E402

PRESETS = {
    "water-mars": "Trace how our understanding of water on Mars changed over time.",
    "first-images": "What did the earliest missions to Mars actually show us, and how did "
                    "that shape the search for water?",
    "instruments": "How did the instruments used to look for water on Mars change across "
                   "missions?",
    # Cross-domain questions, only answerable since the corpus stopped being Mars-only.
    "water-elsewhere": "Where else in the solar system has NASA looked for water and ice, "
                       "and what did each mission actually find?",
    "first-views": "How did the first close-up views of other worlds change what people "
                   "thought those worlds were like?",
    "apollo-surface": "What did Apollo astronauts actually do on the lunar surface, and "
                      "what did they bring back?",
    "telescopes": "How did space telescopes change what astronomers could see, and what "
                  "did each generation of instrument add?",
}

BAR = "─"


def print_trace(result: dict) -> None:
    print(f"\n{BAR * 78}\nREASONING TRACE\n{BAR * 78}")
    for step in result["trace"]:
        print(f"[{step['n']}] {step['kind']:12s} {step['at']:6.2f}s  {step['summary']}")
        if step["kind"] == "decompose":
            for q in step.get("sub_questions", []):
                print(f"       sub: {q}")
            for p in step.get("phrasings", [])[:6]:
                print(f"       spoken: {p}")
            for p in step.get("visual_phrasings", []):
                print(f"       visual: {p}")
        if step["kind"] == "retrieve":
            print(f"       queries={step.get('queries_run')} by_index={step.get('hits_by_index')}")
            print(f"       thresholds={step.get('thresholds')} "
                  f"rejected={step.get('rejected_below_threshold')}")
        if step["kind"] == "diversify":
            print(f"       per clip: {step.get('kept_per_clip')}")
        if step["kind"] == "order":
            print(f"       axes: {step.get('era_axis_counts')}")


def print_rejects(result: dict) -> None:
    rejected = result["rejected"]
    counts = rejected["counts"]
    print(f"\n{BAR * 78}\nDISCARDED  "
          f"({counts['below_threshold']} below threshold, {counts['diversity']} by diversity cap)"
          f"\n{BAR * 78}")
    for row in rejected["diversity"][:6]:
        print(f"  cap      {row['nasa_id'][:44]:44s} [{row['start']:6.1f}] score={row['score']}")
    for row in rejected["below_threshold"][:6]:
        print(f"  weak     {row.get('index','?'):14s} score={row.get('score')} "
              f"< {row.get('threshold')}")


def print_answer(result: dict) -> None:
    answer = result["answer"]
    print(f"\n{BAR * 78}\nANSWER\n{BAR * 78}")
    print(answer["answer"] or "(no answer: no evidence passed the threshold)")
    if answer.get("chronology"):
        print("\nChronology:")
        for point in answer["chronology"]:
            cites = ", ".join(f"[{c}]" for c in point.get("citations", []))
            print(f"  {point.get('era', '?')}  {point.get('claim', '')} {cites}")
    if answer.get("caveats"):
        print(f"\nCaveats: {answer['caveats']}")


def print_evidence(result: dict) -> None:
    print(f"\n{BAR * 78}\nEVIDENCE (chronological)\n{BAR * 78}")
    for i, item in enumerate(result["evidence"], 1):
        era = f"{item['era_start']} ({item['era_axis']})" if item["era_start"] else "undated"
        print(f"[{i:2d}] {era:18s} {item['mission'] or 'unknown':28s} "
              f"{item['nasa_id'][:38]:38s} {item['start']:6.1f}-{item['end']:6.1f}s "
              f"{item['index']:14s} {item['score']}")
        if item["text"]:
            print(f"     {item['text'][:150]}")


def compile_reel(result: dict, coll) -> dict:
    """One reel across every source clip, in era order, with burned-in provenance."""
    try:
        return reel.build(vc.connect(), coll, result["evidence"])
    except Exception as exc:  # noqa: BLE001
        return {"stream_url": None, "shots": [], "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="*", help="the research question")
    parser.add_argument("--preset", choices=sorted(PRESETS))
    parser.add_argument("--top-k", type=int, default=agent.DEFAULT_TOP_K)
    parser.add_argument("--threshold", type=float, default=agent.DEFAULT_THRESHOLD)
    parser.add_argument("--cap", type=int, default=agent.PER_VIDEO_CAP)
    parser.add_argument("--json", help="write the full result to this path")
    parser.add_argument("--no-stream", action="store_true")
    args = parser.parse_args()

    question = " ".join(args.question).strip() or PRESETS.get(args.preset or "", "")
    if not question:
        parser.error("give a question or --preset")

    coll = vc.get_collection()
    id_by_video = {e["video_id"]: n for n, e in manifest.load().items() if e.get("video_id")}

    result = agent.ask(question, top_k=args.top_k, threshold=args.threshold,
                       cap=args.cap, coll=coll, id_by_video=id_by_video)

    print_trace(result)
    print_answer(result)
    print_evidence(result)
    print_rejects(result)

    print(f"\n{BAR * 78}\nARCHIVE TIMELINE\n{BAR * 78}")
    for bucket in result["timeline"]:
        bar = "█" * max(1, bucket["scenes"] // 4)
        print(f"  {bucket['decade']}s  {bucket['scenes']:4d}  {bar}")

    if not args.no_stream:
        print(f"\n{BAR * 78}\nEVIDENCE REEL\n{BAR * 78}")
        compiled = compile_reel(result, coll)
        result["reel"] = compiled
        if compiled.get("error"):
            print(f"  compile failed: {compiled['error']}")
        if compiled.get("stream_url"):
            print(f"  {len(compiled['shots'])} shots, {compiled['total_seconds']:.0f}s")
            for shot in compiled["shots"]:
                print(f"    {shot['at']:4d}s  +{shot['duration']:5.1f}s  {shot['caption']}")
            print(f"\n  {compiled['stream_url']}")
            print(f"  {compiled['player_url']}")

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
