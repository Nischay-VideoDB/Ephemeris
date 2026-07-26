"""Build the `mission_meta` custom index records.

NASA's video library holds essentially nothing published before 2000, so ordering
evidence by publication date cannot express how understanding changed across
earlier missions. A 2015 explainer may discuss a 1976 result.

So every scene carries two dates:

- `published_year`, straight from the NASA API, always correct, never interesting
  on its own.
- `era_start`, extracted by the VLM from what the scene actually discusses,
  interesting but only as good as the extraction.

`era_axis` records which one the record is ordered by, and `era_basis` records how
the era was determined. The agent surfaces both, so a chronology built on inferred
dates is never presented as if it came from metadata.

Records are per scene, not per video. A single explainer can walk through four
decades of findings, and ordering evidence moments across the archive only works
if each moment carries its own date.
"""

from __future__ import annotations

from typing import Any

UNKNOWN_MISSION = "unknown"
WEAK_BASIS = "not_determinable"

# Anything outside this window is an extraction error rather than a date. The
# space age has a hard lower bound and the archive cannot discuss the future.
ERA_MIN = 1957
ERA_MAX = 2030


def _clean_year(value: Any) -> int | None:
    try:
        year = int(float(value))
    except (TypeError, ValueError):
        return None
    return year if ERA_MIN <= year <= ERA_MAX else None


# Mission names are open vocabulary, so the model returns whatever the footage
# calls them. One collection produced "Perseverance", "PERSEVERANCE", and "Mars
# Perseverance Rover" for a single mission, which splits `aggregate(group_by=
# primary_mission)` into three buckets and makes an `==` filter miss two thirds of
# the evidence. Canonical forms are matched on substrings, longest first, so
# "Mars Perseverance Rover" resolves before a bare "Mars" ever could.
# Order matters: the first substring match wins, so specific names must precede the general
# ones they contain ("mariner 9" before "mariner", "apollo-soyuz" before "apollo"). The list
# grew with the corpus: written for Mars, then extended once the archive covered the whole
# solar system and `Osiris Rex` / `OSIRIS-REx` / `Osiris-Rex` started counting as three
# separate missions in every aggregate.
MISSION_ALIASES = [
    # Mars
    ("perseverance", "Perseverance"),
    ("curiosity", "Curiosity"),
    ("phoenix", "Phoenix"),
    ("opportunity", "Opportunity"),
    ("spirit", "Spirit"),
    ("viking", "Viking"),
    ("pathfinder", "Mars Pathfinder"),
    ("sojourner", "Mars Pathfinder"),
    ("insight", "InSight"),
    ("maven", "MAVEN"),
    ("odyssey", "Mars Odyssey"),
    ("reconnaissance orbiter", "Mars Reconnaissance Orbiter"),
    ("mro", "Mars Reconnaissance Orbiter"),
    ("global surveyor", "Mars Global Surveyor"),
    ("ingenuity", "Ingenuity"),
    ("mariner 4", "Mariner 4"),
    ("mariner 9", "Mariner 9"),
    ("mariner", "Mariner"),

    # Moon and human spaceflight
    ("apollo-soyuz", "Apollo-Soyuz"),
    ("apollo", "Apollo"),
    ("artemis", "Artemis"),
    ("lunar reconnaissance orbiter", "Lunar Reconnaissance Orbiter"),
    ("lro", "Lunar Reconnaissance Orbiter"),
    ("skylab", "Skylab"),
    ("gemini", "Gemini"),
    ("space shuttle", "Space Shuttle"),
    ("shuttle", "Space Shuttle"),
    ("international space station", "International Space Station"),
    ("iss", "International Space Station"),

    # Outer planets and small bodies
    ("osiris", "OSIRIS-REx"),
    ("voyager 1", "Voyager 1"),
    ("voyager 2", "Voyager 2"),
    ("voyager", "Voyager"),
    ("cassini", "Cassini-Huygens"),
    ("huygens", "Cassini-Huygens"),
    ("new horizons", "New Horizons"),
    ("galileo", "Galileo"),
    ("juno", "Juno"),
    ("pioneer", "Pioneer"),
    ("neowise", "NEOWISE"),
    ("stardust", "Stardust"),

    # Sun
    ("solar dynamics observatory", "Solar Dynamics Observatory"),
    ("sdo", "Solar Dynamics Observatory"),
    ("soho", "SOHO"),
    ("stereo", "STEREO"),
    ("parker solar probe", "Parker Solar Probe"),
    ("trace", "TRACE"),

    # Astronomy
    ("hubble", "Hubble Space Telescope"),
    ("chandra", "Chandra X-ray Observatory"),
    ("james webb", "James Webb Space Telescope"),
    ("webb", "James Webb Space Telescope"),
    ("spitzer", "Spitzer Space Telescope"),
    ("kepler", "Kepler"),
    ("tess", "TESS"),
    ("sofia", "SOFIA"),
    ("stratoscope", "Stratoscope II"),

    # Earth science
    ("landsat 8", "Landsat 8"),
    ("landsat", "Landsat"),
    ("terra", "Terra"),
    ("aqua", "Aqua"),
    ("grace", "GRACE"),
    ("tropical rainfall", "TRMM"),
    ("trmm", "TRMM"),
    ("cygnss", "CYGNSS"),
    ("black marble", "Suomi NPP"),
    ("suomi", "Suomi NPP"),

    # Aeronautics and agency history
    ("x-15", "X-15"),
    ("x15", "X-15"),
    ("naca", "NACA"),
    ("wind tunnel", "NACA"),
    ("mercury", "Mercury"),
]


def _clean_mission(value: Any) -> str:
    text = (str(value or "")).strip()
    if not text or text.lower() == UNKNOWN_MISSION:
        return UNKNOWN_MISSION

    lowered = text.lower()
    for needle, canonical in MISSION_ALIASES:
        if needle in lowered:
            return canonical
    return text


def build_records(scenes: list[dict], entry: dict) -> list[dict]:
    """One record per VLM scene, joining scene-level extraction to NASA metadata.

    `entry` is a manifest row: nasa_id, title, center, published_year, and
    optionally `video_era` produced by src/era.py.
    """
    published_year = entry.get("published_year") or 0
    video_era = entry.get("video_era") or {}
    video_year = _clean_year(video_era.get("earliest_era_year"))
    video_missions = [m for m in (video_era.get("missions") or []) if m.get("mission")]
    video_primary = _clean_mission(video_missions[0]["mission"]) if video_missions else UNKNOWN_MISSION

    records: list[dict] = []

    for scene in scenes:
        data = scene.get("data") or {}
        era_year = _clean_year(data.get("era_year"))
        era_basis = str(data.get("era_basis") or WEAK_BASIS)
        mission = _clean_mission(data.get("mission_ref"))

        # Three tiers, most trustworthy first. A scene-level era counts only when the
        # model produced a plausible year *and* said where it came from; otherwise the
        # clip-level pass gets a turn; otherwise the publication date, which is always
        # correct and rarely interesting. `era_axis` records which tier won so a
        # chronology never presents an inference as metadata.
        if era_year is not None and era_basis != WEAK_BASIS:
            era_start, era_axis = era_year, "scene"
        elif video_year is not None:
            era_start, era_axis = video_year, "video"
            if era_basis == WEAK_BASIS:
                era_basis = "video_context"
        else:
            era_start, era_axis = published_year, "published"

        if mission == UNKNOWN_MISSION and video_primary != UNKNOWN_MISSION:
            mission = video_primary

        records.append({
            "start": float(scene.get("start", 0.0)),
            "end": float(scene.get("end", 0.0)),
            "nasa_id": entry.get("nasa_id", ""),
            "title": entry.get("title", ""),
            "center": entry.get("center") or "unknown",
            "published_year": int(published_year),
            "primary_mission": mission,
            "era_start": int(era_start),
            "era_basis": era_basis,
            "era_axis": era_axis,
            "water_relevance": str(video_era.get("water_relevance") or "none"),
            # Carried through from the VLM scene so retrieval results can be placed
            # spatially and shaped by event kind without a second lookup. The scene
            # facets index already holds these, but the agent joins mission_meta, and
            # joining two indexes per moment would double the round trips.
            "celestial_body": str(data.get("celestial_body") or "unknown"),
            "event_type": str(data.get("event_type") or "other"),
            "source_url": entry.get("mp4_url", ""),
        })

    return records


def summarize(records: list[dict]) -> dict:
    """Aggregate view used for reporting and for sanity-checking extraction."""
    if not records:
        return {"count": 0}

    dated = [r for r in records if r["era_axis"] != "published"]
    missions = sorted({r["primary_mission"] for r in records if r["primary_mission"] != UNKNOWN_MISSION})

    axes: dict[str, int] = {}
    bases: dict[str, int] = {}
    bodies: dict[str, int] = {}
    for record in records:
        axes[record["era_axis"]] = axes.get(record["era_axis"], 0) + 1
        bases[record["era_basis"]] = bases.get(record["era_basis"], 0) + 1
        body = record.get("celestial_body", "unknown")
        bodies[body] = bodies.get(body, 0) + 1

    return {
        "count": len(records),
        "dated_count": len(dated),
        "dated_share": round(len(dated) / len(records), 3),
        "era_range": [min(r["era_start"] for r in records), max(r["era_start"] for r in records)],
        "missions": missions,
        "era_axis_counts": axes,
        "era_basis_counts": bases,
        "body_counts": bodies,
    }
