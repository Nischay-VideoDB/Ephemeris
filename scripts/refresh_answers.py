"""Regenerate the answers the app ships, so they match the pipeline that is actually running.

The presets are the curated way into the interface and the first thing anyone sees. They are
generated output, not source, and every change to retrieval or synthesis leaves them a little
further behind whatever the code now does. That gap has been shipped twice: once with mission
labels naming the wrong world, and once with an answer that cited two of its eight moments
while the reel played all eight.

Refreshes both copies of each preset (`data/answer_<slug>.json`, read by nothing but kept as
the record, and `web/public/answers/<id>.json`, which the page fetches) and, with --saved, the
runs under `data/answers` as well, re-asking each question in place under its existing id.

    python scripts/refresh_answers.py                 # the five shipped presets
    python scripts/refresh_answers.py --saved         # those, plus saved runs
    python scripts/refresh_answers.py --only water-mars telescopes
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

import agent  # noqa: E402
import manifest  # noqa: E402
import reel  # noqa: E402
import videodb_client as vc  # noqa: E402
from ask import PRESETS  # noqa: E402

PUBLIC = ROOT / "web" / "public" / "answers"
DATA = ROOT / "data"
SAVED = DATA / "answers"

# Only the presets the page offers. `ask.py` knows others that are not shipped.
SHIPPED = ["water-mars", "first-images", "telescopes", "water-elsewhere", "apollo-surface"]


def run_one(question: str) -> dict:
    coll = vc.get_collection()
    id_by_video = {e["video_id"]: n for n, e in manifest.load().items() if e.get("video_id")}
    result = agent.ask(question, coll=coll, id_by_video=id_by_video)
    if result["evidence"]:
        try:
            result["reel"] = reel.build(vc.connect(), coll, result["evidence"])
        except Exception as exc:  # noqa: BLE001
            result["reel"] = {"stream_url": None, "shots": [], "error": f"{type(exc).__name__}: {exc}"}
    return result


def refresh_preset(slug: str) -> tuple[str, dict]:
    result = run_one(PRESETS[slug])
    payload = json.dumps(result, indent=2)
    (DATA / f"answer_{slug.replace('-', '_')}.json").write_text(payload)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    (PUBLIC / f"{slug}.json").write_text(payload)
    return slug, result


def refresh_saved(path: Path) -> tuple[str, dict]:
    """Re-ask a saved run's question and write it back under the same id.

    The id carries when it was first asked and that is left alone: this replaces what the
    archive answers, not the record that it was asked.
    """
    existing = json.loads(path.read_text())
    result = run_one(existing["question"])
    result["saved_id"] = existing.get("saved_id", path.stem)
    path.write_text(json.dumps(result, indent=2))
    return path.stem, result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--saved", action="store_true", help="also refresh runs in data/answers")
    parser.add_argument("--only", nargs="*", help="limit to these preset slugs")
    args = parser.parse_args()

    slugs = [s for s in SHIPPED if not args.only or s in args.only]
    jobs: list = [(slug, refresh_preset, slug) for slug in slugs]
    if args.saved:
        jobs += [(p.stem, refresh_saved, p) for p in sorted(SAVED.glob("*.json"))]

    if not jobs:
        sys.exit("nothing to refresh")

    print(f"refreshing {len(jobs)}: {', '.join(name for name, _, _ in jobs)}\n")
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [(name, pool.submit(fn, arg)) for name, fn, arg in jobs]
        for name, future in futures:
            try:
                _, result = future.result()
            except Exception as exc:  # noqa: BLE001
                print(f"  FAILED  {name}: {type(exc).__name__}: {exc}")
                continue
            cited = set(result["answer"].get("citations") or [])
            for point in result["answer"].get("chronology") or []:
                cited.update(point.get("citations") or [])
            shots = (result.get("reel") or {}).get("shots") or []
            seconds = (result.get("reel") or {}).get("total_seconds") or 0
            print(f"  {name[:44]:44s} {len(result['evidence'])} moments, "
                  f"{len(cited)} cited, {len(shots)} shots, {seconds:.0f}s")

    print("\nGrade with:  python evals/answers.py data/answers")


if __name__ == "__main__":
    main()
