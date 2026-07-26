"""Retrieval quality gate.

Scores the indexes against hand-written ground truth before anything is built on
top of them. A weak index cannot be rescued by a good agent or a good interface,
so this runs before either exists.

Precision and recall are both reported, because they trade off: a low
score_threshold finds everything and returns noise, a high one returns only
certainties and misses most of them. One number alone would hide that.

    python evals/run.py
    python evals/run.py --kind visual_only
    python evals/run.py --threshold 0.25
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import manifest  # noqa: E402
import videodb_client as vc  # noqa: E402

GOLD_PATH = Path(__file__).resolve().parent / "gold.json"
REPORT_PATH = ROOT / "data" / "eval_report.json"

# A retrieved shot counts as a hit when it comes from the expected video and
# overlaps the expected window. Exact boundary agreement is not the goal:
# segmentation decides boundaries, and a moment that starts two seconds early is
# still the right moment.
OVERLAP_TOLERANCE = 2.0


def overlaps(shot_start: float, shot_end: float, window: list[float]) -> bool:
    want_start, want_end = float(window[0]), float(window[1])
    return (shot_start - OVERLAP_TOLERANCE) < want_end and (shot_end + OVERLAP_TOLERANCE) > want_start


def video_lookup() -> tuple[dict[str, str], dict[str, str]]:
    entries = manifest.load()
    to_video = {nid: e["video_id"] for nid, e in entries.items() if e.get("video_id")}
    to_nasa = {v: k for k, v in to_video.items()}
    return to_video, to_nasa


def run_case(coll, case: dict, to_nasa: dict[str, str], threshold: float | None,
             top_k: int | None = None) -> dict:
    mode = case.get("mode", "semantic")
    expected = case.get("expect", [])
    result: dict = {"id": case["id"], "kind": case["kind"], "mode": mode, "query": case.get("query")}

    try:
        if mode == "semantic":
            search = coll.semantic_search(
                query=case["query"],
                index_names=case.get("index_names"),
                top_k=top_k or case.get("top_k", 10),
                score_threshold=threshold if threshold is not None else case.get("score_threshold"),
            )
            shots = search.get_shots()
        elif mode == "query":
            search = coll.query(
                index_name=case["index_name"],
                filter=case["filter"],
                limit=case.get("limit", 500),
            )
            shots = search.get_shots()
        elif mode == "aggregate":
            payload = coll.aggregate(
                index_name=case["index_name"],
                group_by=case["group_by"],
                metric=case.get("metric", "count"),
            )
            rows = payload.get("results", []) if isinstance(payload, dict) else payload
            result["rows"] = rows
            result["row_count"] = len(rows)
            wanted = set(case.get("expect_groups", []))
            found = {str(r.get(case["group_by"])) for r in rows}
            result["missing_groups"] = sorted(wanted - found)
            result["passed"] = not result["missing_groups"]
            return result
        else:
            raise ValueError(f"unknown mode {mode}")
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["passed"] = False
        return result

    retrieved = [
        {
            "nasa_id": to_nasa.get(s.video_id, s.video_id),
            "start": round(float(s.start), 2),
            "end": round(float(s.end), 2),
            "score": round(float(s.search_score), 4) if s.search_score is not None else None,
            "text": (s.text or "")[:160],
        }
        for s in shots
    ]

    hits, matched = [], set()
    for i, shot in enumerate(retrieved):
        for j, want in enumerate(expected):
            if shot["nasa_id"] == want["nasa_id"] and overlaps(shot["start"], shot["end"], want["window"]):
                hits.append(i)
                matched.add(j)
                break

    # `query()` is exhaustive: it returns every row satisfying the filter, so
    # scoring it against a handful of listed windows would punish it for being
    # correct. Recall and per-video spread are the meaningful numbers there;
    # precision only means something for ranked semantic retrieval.
    recall = len(matched) / len(expected) if expected else 1.0
    precision = (len(hits) / len(retrieved)) if (retrieved and mode == "semantic") else None

    result.update({
        "retrieved_count": len(retrieved),
        "expected_count": len(expected),
        "hit_count": len(hits),
        "videos_covered": len({s["nasa_id"] for s in retrieved}),
        "precision": round(precision, 3) if precision is not None else None,
        "recall": round(recall, 3),
        "top_rank_hit": hits[0] + 1 if hits else None,
        "retrieved": retrieved[:8],
        "missed": [expected[j] for j in range(len(expected)) if j not in matched],
        "passed": recall >= case.get("min_recall", 0.5),
    })
    return result


def table(results: list[dict]) -> str:
    header = (f"{'case':28s} {'kind':13s} {'mode':10s} {'prec':>6s} {'recall':>7s} "
              f"{'rank1':>6s} {'n':>4s} {'vids':>5s}  pass")
    lines = [header, "-" * len(header)]
    for r in results:
        verdict = "yes" if r.get("passed") else "NO"
        head = f"{r['id'][:28]:28s} {r['kind'][:13]:13s} {r['mode']:10s} "
        if r["mode"] == "aggregate":
            lines.append(head + f"{'-':>6s} {'-':>7s} {'-':>6s} "
                                f"{r.get('row_count', 0):4d} {'-':>5s}  {verdict}")
            continue
        if "error" in r:
            lines.append(head + f"{'err':>6s} {'err':>7s} {'-':>6s} {'-':>4s} {'-':>5s}  NO")
            continue
        prec = f"{r['precision']:6.3f}" if r["precision"] is not None else f"{'n/a':>6s}"
        lines.append(
            head + f"{prec} {r['recall']:7.3f} {str(r['top_rank_hit'] or '-'):>6s} "
                   f"{r['retrieved_count']:4d} {r['videos_covered']:5d}  {verdict}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", help="run only cases of this kind")
    parser.add_argument("--threshold", type=float, help="override score_threshold for semantic cases")
    parser.add_argument("--top-k", type=int, dest="top_k",
                        help="override top_k for semantic cases; useful for showing how "
                             "retrieval depth has to scale with corpus size")
    args = parser.parse_args()

    gold = json.loads(GOLD_PATH.read_text())
    cases = gold["cases"]
    if args.kind:
        cases = [c for c in cases if c["kind"] == args.kind]

    coll = vc.get_collection()
    _, to_nasa = video_lookup()

    results = [run_case(coll, case, to_nasa, args.threshold, args.top_k) for case in cases]
    print(table(results))

    scored = [r for r in results if r["mode"] != "aggregate" and "error" not in r]
    ranked = [r for r in scored if r["precision"] is not None]
    summary = {
        "cases": len(results),
        "passed": sum(1 for r in results if r.get("passed")),
        "mean_precision_ranked": round(sum(r["precision"] for r in ranked) / len(ranked), 3) if ranked else 0.0,
        "mean_recall": round(sum(r["recall"] for r in scored) / len(scored), 3) if scored else 0.0,
    }
    by_kind: dict[str, dict] = {}
    for r in scored:
        bucket = by_kind.setdefault(r["kind"], {"n": 0, "precision_n": 0, "precision": 0.0, "recall": 0.0})
        bucket["n"] += 1
        bucket["recall"] += r["recall"]
        if r["precision"] is not None:
            bucket["precision_n"] += 1
            bucket["precision"] += r["precision"]
    for bucket in by_kind.values():
        bucket["precision"] = round(bucket["precision"] / bucket["precision_n"], 3) if bucket["precision_n"] else None
        bucket["recall"] = round(bucket["recall"] / bucket["n"], 3)
    summary["by_kind"] = by_kind

    print()
    print(f"passed {summary['passed']}/{summary['cases']}  "
          f"mean precision (ranked only) {summary['mean_precision_ranked']}  "
          f"mean recall {summary['mean_recall']}")
    for kind, bucket in sorted(by_kind.items()):
        prec = bucket["precision"] if bucket["precision"] is not None else "n/a"
        print(f"  {kind:16s} n={bucket['n']:2d}  precision={prec}  recall={bucket['recall']}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    print(f"\nwrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
