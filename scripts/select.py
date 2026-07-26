"""Turn ranked candidates into a balanced ingest list.

Ranking alone would hand back a corpus that is still mostly Mars, because Mars is
what the archive holds most of. Selection enforces a per-domain quota instead, so
the corpus can answer questions about the Moon, the Shuttle era, Earth science and
the outer planets, and so `celestial_body` has more than one value to distinguish.

Filters applied here, all cheap and all before any upload:

- must expose an mp4 rendition
- byte size within a sane window: a 400 MB file is a full press conference and
  would eat the credit budget for one clip, a 1 MB file is a broken rendition
- silent B-roll capped per domain: it is excellent visual evidence but carries no
  narration, so a corpus made of it has nothing for the transcript index to hold

Writes data/selection.json. Nothing is uploaded here.

    python scripts/select.py                       # default quotas
    python scripts/select.py --quota moon=16
    python scripts/select.py --max-mb 90
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import manifest  # noqa: E402
import nasa  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES_PATH = ROOT / "data" / "candidates.json"
OUT_PATH = ROOT / "data" / "selection.json"

# Mars is already the deepest part of the corpus, so it gets the smallest top-up.
DEFAULT_QUOTAS = {
    "moon": 12,
    "human_spaceflight": 12,
    "outer_planets": 12,
    "earth_science": 10,
    "sun": 8,
    "astronomy": 8,
    "mars": 0,
    "aeronautics": 6,
}

# Weekly newsreels mention a dozen missions in eight minutes, which makes them score
# highly and cover nothing. They are the single worst thing to put in a corpus meant to
# answer "how did understanding of X change".
EXCLUDE_TITLE = (
    "this week @nasa", "inside ksc", "nasa day in", "@nasa –", "@nasa -",
    "week @nasa", "nasa update", "video file",
)

# A clip earns a domain by talking about it, not by name-dropping missions. Mission-name
# density alone put ISS crew launches in the Moon bucket and an Artemis test in astronomy.
DOMAIN_TERMS = {
    "moon": ("moon", "lunar", "apollo", "artemis", "regolith", "crater"),
    "human_spaceflight": ("astronaut", "shuttle", "space station", "spacewalk", "crew",
                          "mercury", "gemini", "skylab", "orbit", "eva"),
    "outer_planets": ("jupiter", "saturn", "pluto", "asteroid", "comet", "titan", "europa",
                      "voyager", "cassini", "juno", "osiris", "neptune", "uranus"),
    "earth_science": ("earth", "landsat", "climate", "hurricane", "ocean", "forest", "ice",
                      "atmosphere", "satellite imagery", "sea level", "wildfire"),
    "sun": ("sun", "solar", "corona", "eclipse", "flare", "heliophysics", "sunspot"),
    "astronomy": ("telescope", "galaxy", "star", "nebula", "hubble", "webb", "chandra",
                  "exoplanet", "universe", "cosmic"),
    "mars": ("mars", "martian"),
    "aeronautics": ("aircraft", "flight research", "wind tunnel", "aeronautic", "x-15",
                    "supersonic", "airfoil", "naca"),
}

MIN_DESCRIPTION = 120

MIN_MB = 2.0
MAX_MB = 110.0
SILENT_CAP = 3  # per domain

SILENT_HINTS = ("silent", "b-roll", "broll", "resource reel", "no audio")
BRIEFING_HINTS = (
    "interview", "briefing", "press conference", "news conference", "panel",
    "q&a", "testimony", "remarks", "ceremony", "hearing", "roundtable",
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def profile_for(meta: dict) -> str:
    """Sampling profile. Talking heads want one frame per scene, moving footage
    wants several, and guessing wrong costs either accuracy or credit."""
    text = f"{meta.get('title', '')} {meta.get('description', '')}".lower()
    return "briefing" if any(h in text for h in BRIEFING_HINTS) else "visual"


def on_topic(meta: dict, domain: str) -> bool:
    text = f"{meta.get('title', '')} {meta.get('description', '')}".lower()
    return any(term in text for term in DOMAIN_TERMS.get(domain, ()))


def excluded_format(meta: dict) -> bool:
    return any(bad in (meta.get("title") or "").lower() for bad in EXCLUDE_TITLE)


def looks_silent(meta: dict) -> bool:
    text = f"{meta.get('title', '')} {meta.get('description', '')}".lower()
    return any(h in text for h in SILENT_HINTS)


def main() -> None:
    args = sys.argv[1:]
    quotas = dict(DEFAULT_QUOTAS)
    max_mb = MAX_MB
    for i, arg in enumerate(args):
        if arg == "--quota":
            key, _, value = args[i + 1].partition("=")
            quotas[key] = int(value)
        if arg == "--max-mb":
            max_mb = float(args[i + 1])

    candidates = json.loads(CANDIDATES_PATH.read_text())["candidates"]
    have = set(manifest.load().keys())

    by_domain: dict[str, list[dict]] = {}
    for item in candidates:
        by_domain.setdefault(item["domain"], []).append(item)
    for rows in by_domain.values():
        rows.sort(key=lambda x: -x["score"])

    selection: list[dict] = []
    stats: dict[str, dict] = {}

    for domain, quota in quotas.items():
        rows = by_domain.get(domain, [])
        picked = 0
        silent = 0
        rejected = {"ingested": 0, "no_mp4": 0, "too_big": 0, "too_small": 0, "silent_cap": 0,
                    "unreachable": 0, "off_topic": 0, "newsreel": 0, "thin_metadata": 0}

        for item in rows:
            if picked >= quota:
                break
            nasa_id = item["nasa_id"]
            if nasa_id in have:
                rejected["ingested"] += 1
                continue

            try:
                meta = nasa.resolve(nasa_id)
            except Exception:  # noqa: BLE001
                rejected["unreachable"] += 1
                continue
            if not meta.get("mp4_url"):
                rejected["no_mp4"] += 1
                continue
            if excluded_format(meta):
                rejected["newsreel"] += 1
                continue
            if not on_topic(meta, domain):
                rejected["off_topic"] += 1
                continue
            if len((meta.get("description") or "")) < MIN_DESCRIPTION:
                # An opaque KSC reel id with two lines of metadata is a coin flip on content.
                rejected["thin_metadata"] += 1
                continue

            is_silent = looks_silent(meta)
            if is_silent and silent >= SILENT_CAP:
                rejected["silent_cap"] += 1
                continue

            try:
                status, size = nasa.probe_size(meta["mp4_url"])
            except Exception:  # noqa: BLE001
                rejected["unreachable"] += 1
                continue
            if status >= 400 or not size:
                rejected["unreachable"] += 1
                continue

            mb = size / 1e6
            if mb > max_mb:
                rejected["too_big"] += 1
                continue
            if mb < MIN_MB:
                rejected["too_small"] += 1
                continue

            selection.append({
                "nasa_id": nasa_id,
                "domain": domain,
                "profile": profile_for(meta),
                "score": item["score"],
                "size_mb": round(mb, 1),
                "title": meta.get("title"),
                "published_year": meta.get("published_year"),
                "missions": item["signals"]["missions"][:6],
                "historical_years": item["signals"]["historical_years"][:6],
                "silent": is_silent,
                "note": f"{domain} coverage, discovery score {item['score']}",
            })
            picked += 1
            silent += int(is_silent)
            time.sleep(0.1)

        stats[domain] = {"picked": picked, "quota": quota, "rejected": rejected}
        log(f"{domain:18s} picked {picked:3d}/{quota:<3d} rejected={rejected}")

    OUT_PATH.write_text(json.dumps({"selection": selection}, indent=2))
    total_mb = sum(s["size_mb"] for s in selection)
    log(f"selected {len(selection)} clips, {total_mb:.0f} MB -> {OUT_PATH}")
    log(f"profiles: visual={sum(1 for s in selection if s['profile'] == 'visual')} "
        f"briefing={sum(1 for s in selection if s['profile'] == 'briefing')}")


if __name__ == "__main__":
    main()
