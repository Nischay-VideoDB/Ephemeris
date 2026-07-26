"""Find NASA clips whose *content* reaches back before the archive's upload dates.

The library holds almost no video published before 2000, so historical reach has to
come from retrospective content: a 2015 explainer discussing a 1976 result. This
scores candidates on signals available for free in search metadata, before spending
any indexing credit:

- early mission names in the title, description, or keywords
- explicit years in the description, weighted toward older ones
- retrospective framing ("for decades", "first", "since", "history of")

Candidates are gathered per **domain** (Mars, Moon, human spaceflight, Earth science,
outer planets, Sun, deep-sky astronomy, early aeronautics). Domain coverage is the
point: a corpus that is 90% Mars answers Mars questions and nothing else, and leaves
`celestial_body` with one value to distinguish, which the interface depends on.

Writes data/candidates.json ranked, tagged by domain. Nothing is uploaded here.

    python scripts/discover.py                 # every domain
    python scripts/discover.py --domain moon   # one domain
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import manifest  # noqa: E402
import nasa  # noqa: E402

OUT_PATH = Path(__file__).resolve().parent.parent / "data" / "candidates.json"

# Missions weighted by how far back they pull the timeline. Anything that predates
# the archive's own video holdings is worth more than a modern mission already
# covered. Weights are era reach, not importance: Apollo outscores Artemis here
# because 1969 footage is what the archive cannot otherwise reach.
MISSION_WEIGHTS = {
    # Mars
    "mariner": 12, "viking": 12, "pathfinder": 10, "sojourner": 10,
    "global surveyor": 8, "mars odyssey": 7, "spirit": 6, "opportunity": 6,
    "mars express": 5, "reconnaissance orbiter": 5, "phoenix": 4,
    "curiosity": 3, "maven": 3, "insight": 2, "perseverance": 1, "ingenuity": 1,
    # Moon
    "ranger": 12, "surveyor": 12, "lunar orbiter": 12, "apollo": 11,
    "apollo 11": 12, "apollo 8": 12, "apollo 13": 11, "apollo 17": 10,
    "lunar module": 10, "clementine": 7, "lunar prospector": 7,
    "lunar reconnaissance orbiter": 4, "grail": 3, "ladee": 3, "artemis": 1,
    # Human spaceflight in Earth orbit
    "mercury": 13, "gemini": 12, "skylab": 11, "apollo-soyuz": 11,
    "space shuttle": 7, "columbia": 8, "challenger": 8, "discovery": 6,
    "atlantis": 6, "endeavour": 6, "mir": 7, "spacelab": 8,
    "international space station": 3, "expedition": 2, "crew dragon": 1,
    # Outer planets and small bodies
    "pioneer": 12, "voyager": 11, "galileo": 9, "magellan": 9, "ulysses": 8,
    "cassini": 7, "huygens": 7, "near shoemaker": 8, "stardust": 6,
    "deep impact": 6, "dawn": 4, "new horizons": 4, "juno": 3, "osiris-rex": 2,
    # Sun and heliophysics
    "skylab solar": 11, "solar maximum mission": 10, "yohkoh": 9, "soho": 7,
    "trace": 7, "stereo": 5, "solar dynamics observatory": 3, "parker solar probe": 2,
    # Astronomy
    "orbiting astronomical observatory": 12, "uhuru": 12, "einstein observatory": 11,
    "iras": 10, "cobe": 10, "compton": 9, "hubble": 6, "chandra": 5,
    "spitzer": 4, "wmap": 5, "kepler": 3, "webb": 1,
    # Earth science
    "tiros": 13, "nimbus": 12, "landsat": 10, "seasat": 10, "nimbus-7": 11,
    "upper atmosphere research satellite": 8, "topex": 8, "terra": 5, "aqua": 5,
    "aura": 5, "grace": 5, "suomi": 3, "icesat": 4,
    # Aeronautics and agency history
    "naca": 14, "x-15": 13, "x-1": 13, "bell x": 12, "wind tunnel": 8,
    "lifting body": 10, "sr-71": 8, "helios": 6,
}

RETROSPECTIVE_PHRASES = [
    "for decades", "history of", "since the", "first time", "years ago",
    "previously", "earlier missions", "over the years", "anniversary",
    "looking back", "legacy", "decades of", "past missions", "archival",
    "retrospective", "milestone", "celebrating", "then and now",
]

# One block per domain. Queries are written the way the archive's own cataloguers
# write, not the way a researcher asks, because that is what the metadata contains.
DOMAIN_QUERIES: dict[str, list[str]] = {
    "mars": [
        "Viking Mars lander", "Mars Pathfinder Sojourner", "Mariner Mars",
        "history of Mars exploration", "Mars water discovery history",
        "Spirit Opportunity rover Mars", "Mars Odyssey water ice",
        "Phoenix Mars lander water ice", "Curiosity rover ancient lake",
        "Mars ancient ocean evidence", "Perseverance Jezero delta",
    ],
    "moon": [
        "Apollo 11 moon landing", "Apollo lunar surface EVA", "Apollo 8 earthrise",
        "Ranger Surveyor lunar", "Lunar Orbiter photography", "Apollo 13 mission",
        "lunar samples geology", "Lunar Reconnaissance Orbiter moon",
        "history of lunar exploration", "Artemis moon program",
    ],
    "human_spaceflight": [
        "Mercury program astronaut", "Gemini spacewalk", "Skylab space station",
        "space shuttle launch history", "Hubble servicing mission astronauts",
        "International Space Station research", "Apollo-Soyuz test project",
        "shuttle Columbia first flight", "spacewalk EVA training",
        "history of human spaceflight",
    ],
    "outer_planets": [
        "Voyager Jupiter Saturn", "Pioneer outer planets", "Cassini Saturn rings",
        "Galileo Jupiter mission", "New Horizons Pluto", "Juno Jupiter",
        "comet mission spacecraft", "asteroid sample return",
        "history of planetary exploration", "Titan Huygens landing",
    ],
    "sun": [
        "solar flare observation", "SOHO solar observatory", "Solar Dynamics Observatory sun",
        "Parker Solar Probe corona", "solar cycle history", "coronal mass ejection",
        "total solar eclipse observation", "space weather effects",
    ],
    "astronomy": [
        "Hubble Space Telescope discovery", "Chandra X-ray observatory",
        "Webb telescope first images", "Kepler exoplanets", "cosmic background COBE",
        "history of space telescopes", "galaxy survey astronomy", "supernova observation",
    ],
    "earth_science": [
        "Landsat Earth observation history", "TIROS Nimbus weather satellite",
        "hurricane from space satellite", "climate change satellite data",
        "ozone hole discovery", "sea level rise satellite", "wildfire smoke satellite",
        "Earth science mission overview",
    ],
    "aeronautics": [
        "X-15 research aircraft", "NACA wind tunnel research", "supersonic flight research",
        "lifting body research aircraft", "aeronautics research history",
        "flight research center history", "aviation safety research NASA",
    ],
}

YEAR_RE = re.compile(r"\b(19[3-9]\d|20[0-2]\d)\b")


def score(item: dict) -> tuple[int, dict]:
    haystack = " ".join([
        item.get("title") or "",
        item.get("description") or "",
        " ".join(item.get("keywords") or []),
    ]).lower()

    missions = sorted({m for m in MISSION_WEIGHTS if m in haystack})
    mission_points = sum(MISSION_WEIGHTS[m] for m in missions)

    years = sorted({int(y) for y in YEAR_RE.findall(haystack)})
    published = item.get("published_year") or 0
    # Only years meaningfully older than the upload date indicate retrospection.
    historical_years = [y for y in years if published and y <= published - 3]
    year_points = sum(max(0, (2005 - y) // 5 + 3) for y in historical_years)

    phrases = [p for p in RETROSPECTIVE_PHRASES if p in haystack]
    phrase_points = 2 * len(phrases)

    total = mission_points + year_points + phrase_points
    return total, {
        "missions": missions,
        "years": years,
        "historical_years": historical_years,
        "phrases": phrases,
        "mission_points": mission_points,
        "year_points": year_points,
        "phrase_points": phrase_points,
    }


def main() -> None:
    args = sys.argv[1:]
    only_domain = None
    if "--domain" in args:
        only_domain = args[args.index("--domain") + 1]

    have = set(manifest.load().keys())
    seen: dict[str, dict] = {}

    for domain, queries in DOMAIN_QUERIES.items():
        if only_domain and domain != only_domain:
            continue
        found = 0
        for query in queries:
            try:
                results = nasa.search(query, page_size=40)
            except Exception as exc:  # noqa: BLE001
                print(f"  query failed {query!r}: {exc}", flush=True)
                continue
            for item in results:
                nasa_id = item.get("nasa_id")
                if not nasa_id:
                    continue
                if nasa_id in seen:
                    # First domain to surface a clip owns it, so quotas stay honest.
                    continue
                points, detail = score(item)
                seen[nasa_id] = {
                    **item,
                    "domain": domain,
                    "score": points,
                    "signals": detail,
                    "already_ingested": nasa_id in have,
                }
                found += 1
            time.sleep(0.2)
        print(f"{domain:18s} {found:4d} new candidates", flush=True)

    ranked = sorted(seen.values(), key=lambda x: (x["domain"], -x["score"]))
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"candidates": ranked}, indent=2))

    print(f"\n{len(ranked)} unique candidates -> {OUT_PATH}\n")
    for domain in DOMAIN_QUERIES:
        rows = [r for r in ranked if r["domain"] == domain]
        if not rows:
            continue
        print(f"--- {domain} ({len(rows)}) " + "-" * 60)
        for item in rows[:6]:
            print(f"{item['score']:5d}  {item.get('published_year') or 0:4d}  "
                  f"{','.join(item['signals']['missions'])[:30]:30s}  "
                  f"{(item.get('title') or '')[:56]}")


if __name__ == "__main__":
    main()
