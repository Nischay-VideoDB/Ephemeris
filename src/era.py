"""Video-level era extraction.

The first quality gate found scene-level era extraction produced a usable year for
only 9 of 58 scenes. That was the model behaving correctly: a 10-second scene
usually states no year, and it was told not to guess.

But the *clip* often does. "For decades, planetary scientists have suspected" and
"the 1965 flyby returned the first close-up images" are statements about the whole
video, invisible to any single scene. So a second pass reads the joined transcript
plus NASA's own catalogue description and returns the mission timeline the clip
covers.

This runs on `coll.generate_text()`, so the reasoning stays inside VideoDB rather
than adding a second model provider to the project.

Three-tier fallback for a scene's date, most trustworthy first:

  1. scene-level extraction, when the model gave a plausible year AND said where it
     came from (spoken words or on-screen text)
  2. video-level extraction from this module, when the clip as a whole is anchored
     to an era
  3. NASA's publication year, which is always correct and often uninteresting

`era_axis` on every record says which tier was used, so a chronology built on
inferred dates is never presented as though it came from metadata.
"""

from __future__ import annotations

import json
import re
from typing import Any

MODEL = "pro"
MAX_TRANSCRIPT_CHARS = 12000

ERA_MIN = 1957
ERA_MAX = 2030

PROMPT = """You are cataloguing an archival NASA video for a research index.

Read the catalogue description and the transcript, then report the mission history
this specific video covers. Report only what the material supports.

Rules:
- Report a mission only if the video names it or unmistakably depicts it.
- Give each mission the year of the events the video discusses, not the year the
  video was made.
- earliest_era_year is the earliest year of any event, mission, or finding the video
  discusses. If the video discusses no datable event, use 0.
- primary_topic_year is the year of the main subject of the video.
- Never guess. An empty list and 0 are correct answers when the material is silent.

Return JSON only, in exactly this shape:
{{
  "missions": [{{"mission": "Viking", "year": 1976}}],
  "earliest_era_year": 1976,
  "primary_topic_year": 1976,
  "water_relevance": "direct" | "indirect" | "none",
  "evidence_quote": "a short quote from the transcript or description supporting earliest_era_year",
  "confident": true
}}

CATALOGUE TITLE: {title}

CATALOGUE DESCRIPTION:
{description}

TRANSCRIPT:
{transcript}
"""


def _coerce_year(value: Any) -> int:
    try:
        year = int(float(value))
    except (TypeError, ValueError):
        return 0
    return year if ERA_MIN <= year <= ERA_MAX else 0


def _parse(output: Any) -> dict:
    """`generate_text` returns a dict with an `output` key on the hosted path, but
    the sandbox path returns the payload directly, and a JSON response can still
    arrive as a string. Normalise all three."""
    payload = output.get("output") if isinstance(output, dict) and "output" in output else output

    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z]*\n?|```$", "", text).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            payload = json.loads(match.group(0)) if match else {}

    return payload if isinstance(payload, dict) else {}


def extract(coll, video, entry: dict) -> dict:
    """Ask for the mission timeline of one clip. Never raises."""
    try:
        transcript = video.get_transcript_text() or ""
    except Exception:  # noqa: BLE001 - a clip with no speech is normal
        transcript = ""

    prompt = PROMPT.format(
        title=entry.get("title") or entry.get("nasa_id") or "",
        description=(entry.get("description") or "")[:4000],
        transcript=transcript[:MAX_TRANSCRIPT_CHARS] or "(no speech detected)",
    )

    try:
        raw = coll.generate_text(prompt=prompt, model_name=MODEL, response_type="json")
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}", "earliest_era_year": 0, "missions": []}

    parsed = _parse(raw)

    missions = []
    for item in parsed.get("missions") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("mission") or "").strip()
        if name:
            missions.append({"mission": name, "year": _coerce_year(item.get("year"))})

    earliest = _coerce_year(parsed.get("earliest_era_year"))
    if not earliest:
        years = [m["year"] for m in missions if m["year"]]
        earliest = min(years) if years else 0

    return {
        "missions": missions,
        "earliest_era_year": earliest,
        "primary_topic_year": _coerce_year(parsed.get("primary_topic_year")),
        "water_relevance": str(parsed.get("water_relevance") or "none"),
        "evidence_quote": str(parsed.get("evidence_quote") or "")[:400],
        "confident": bool(parsed.get("confident")),
    }
