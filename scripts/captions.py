"""Print a clip's NASA caption track, with timestamps.

Ground truth for the eval set comes from here, not from the pipeline's own output.
NASA ships `.vtt` files alongside many videos, written by humans, so a gold case
built from them tests retrieval rather than testing the model against itself.

    python scripts/captions.py <nasa_id>
    python scripts/captions.py <nasa_id> --grep water
    python scripts/captions.py --list            # clips that have captions
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import manifest  # noqa: E402
import nasa  # noqa: E402


def main() -> None:
    args = sys.argv[1:]
    entries = manifest.load()

    if not args or "--list" in args:
        for nasa_id, entry in sorted(entries.items(), key=lambda kv: kv[1].get("domain", "")):
            if entry.get("vtt_url"):
                print(f"{entry.get('domain', 'mars'):18s} {nasa_id[:52]:52s} "
                      f"{(entry.get('title') or '')[:44]}")
        return

    nasa_id = args[0]
    needle = None
    if "--grep" in args:
        needle = args[args.index("--grep") + 1].lower()

    entry = entries.get(nasa_id)
    if not entry:
        print(f"no manifest entry for {nasa_id!r}")
        return
    if not entry.get("vtt_url"):
        print(f"{nasa_id} has no caption track")
        return

    cues = list(nasa.vtt_cues(nasa.fetch_vtt(entry["vtt_url"])))
    print(f"{entry.get('title')}  ({entry.get('video_length')}s, {len(cues)} cues, "
          f"domain={entry.get('domain', 'mars')})\n")
    for start, end, text in cues:
        if needle and needle not in text.lower():
            continue
        print(f"{start:8.1f}-{end:7.1f}  {text}")


if __name__ == "__main__":
    main()
