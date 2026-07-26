"""The research agent.

Not a search wrapper. A question goes in, and what comes out is a synthesised answer
grounded in moments drawn from across the archive, ordered by the era each moment
discusses, with a trace of how it was assembled.

The shape of the loop is dictated by three things the quality gate proved, not by
taste:

1. **Query expansion is load bearing.** "twin rovers landing in 2004 to search for
   signs of a watery history" retrieves nothing; the archive says "the first of two
   rovers". The same claim in the archive's wording hits rank 1 at 0.78. So
   decomposition produces alternate phrasings, not only sub-questions.

2. **Indexes must be queried separately.** Scores from different indexes are not
   comparable, and searching them together lets one crowd out another: a transcript
   hit at 0.6899 was absent from a 20-result multi-index search. So each index is
   queried on its own and results are merged under an explicit policy.

3. **Source diversity must be enforced.** Collection search concentrates on whichever
   clip is densest on the topic, which would build a "how this changed over time"
   answer out of a single source. So a per-video cap is applied before ordering.

The trace records what was retrieved *and what was discarded and why*. Rejects are the
part that makes the reasoning checkable.
"""

from __future__ import annotations

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import indexing
import reel
import schema
import speech
import videodb_client as vc

ERA_LOOKUP_PATH = Path(__file__).resolve().parent.parent / "data" / "era_lookup.json"

TRANSCRIPT_INDEXES = [indexing.TRANSCRIPT]
VISUAL_INDEXES = [indexing.SCENE_SEMANTIC]
TEXT_ON_SCREEN_INDEXES = [indexing.OCR]

# Retrieval depth has to track corpus size, because a fixed depth means a correct answer
# gets crowded out as the archive grows. Measured twice: at 58 scenes depth 5 was enough;
# at 386 scenes recall fell to 0.767 until depth 15; at ~1500 scenes across 87 clips the
# visual case `martian-terrain-mesa` fell to rank 26 and needed 30.
DEFAULT_TOP_K = 30
DEFAULT_THRESHOLD = 0.35
# Two passages from one clip is a clip that genuinely covers the subject twice. Three was the
# old cap and never once bound, because a moment was a ten-second cell and there were always
# more clips than slots.
PER_VIDEO_CAP = 2
# Moments are passages now, tens of seconds each, so fourteen of them runs to eight minutes.
# Eight passages at twenty to forty seconds is a piece long enough to follow and short enough
# to watch, still drawn from eight separate productions across the decades.
MAX_EVIDENCE = 8

# One threshold across indexes is wrong, because their scores are not on the same
# scale. OCR records are short, fragmentary strings (a lower-third, a mission clock),
# so cosine similarity against a sentence-length query sits systematically lower than
# it does for prose. Measured on the two demo questions, every OCR match landed in
# 0.30-0.35 and was discarded by a shared 0.35 floor, while transcript and scene hits
# cleared 0.60 comfortably. Same reason the indexes are queried separately.
THRESHOLD_BY_INDEX = {
    indexing.TRANSCRIPT: 0.35,
    indexing.SCENE_SEMANTIC: 0.35,
    indexing.OCR: 0.28,
}


# --------------------------------------------------------------------------- data

@dataclass
class Evidence:
    nasa_id: str
    video_id: str
    start: float
    end: float
    score: float
    index: str
    query: str
    text: str = ""
    era_start: int | None = None
    era_axis: str | None = None
    era_basis: str | None = None
    mission: str | None = None
    title: str = ""
    published_year: int | None = None
    # Where the moment is set and what kind of event it is. Carried so a spatial
    # interface can place a result without a second index lookup per moment.
    celestial_body: str = "unknown"
    event_type: str = "other"
    # Where `celestial_body` came from: "scene" when the scene's own extraction was used,
    # "video" when it was overruled by what the rest of the clip is plainly about. Same
    # contract as era_axis: an inferred placement is never presented as an extracted one.
    body_axis: str = "scene"
    # The words actually inside the played window, once it has been snapped to sentences, and
    # whether speech or the indexing grid decided its bounds.
    spoken: str = ""
    clip_axis: str = "scene"
    # How many consecutive indexed cells this moment covers. More than one means retrieval
    # matched a continuous passage rather than an isolated ten seconds.
    cells: int = 1
    # "scene" when the extracted mission was kept, "dropped" when it named a world this moment
    # is not set on, "none" when the scene carried no mission at all.
    mission_axis: str = "scene"

    @property
    def key(self) -> tuple[str, float]:
        return (self.nasa_id, round(self.start, 1))


@dataclass
class Trace:
    """Reasoning steps, accumulated for the answer and streamed as they happen.

    A full run takes about ninety seconds. Collecting the trace silently and returning it
    at the end left the interface with nothing to show for that minute and a half, which
    reads as a dead button. Each step is therefore also written to stderr as one JSON line
    the moment it is recorded, so a caller can follow along. stderr rather than stdout
    because stdout carries the human-readable report.
    """

    steps: list[dict] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    stream: bool = True

    def add(self, kind: str, summary: str, **detail: Any) -> None:
        step = {
            "n": len(self.steps) + 1,
            "kind": kind,
            "summary": summary,
            "at": round(time.time() - self.started, 2),
            **detail,
        }
        self.steps.append(step)
        if self.stream:
            try:
                sys.stderr.write("@progress " + json.dumps(
                    {"n": step["n"], "kind": kind, "summary": summary, "at": step["at"]}
                ) + "\n")
                sys.stderr.flush()
            except Exception:  # noqa: BLE001
                pass  # progress reporting must never break a run

    def to_list(self) -> list[dict]:
        return self.steps


# ------------------------------------------------------------------- era join

def load_era_lookup() -> dict[str, list[dict]]:
    if not ERA_LOOKUP_PATH.exists():
        return {}
    return json.loads(ERA_LOOKUP_PATH.read_text())


# Earth is where the archive is made: a briefing, a launch or a lab test inside a clip about
# Mars is not a tagging mistake, so these are never treated as outliers and never overrule a
# scene. Bodies that orbit each other are not outliers in each other's company either: a Titan
# scene inside a Cassini-at-Saturn clip is exactly right.
COMPANION_BODIES = {"earth", "earth_orbit", "ground"}
ORBITS = {("moon", "earth"), ("titan", "saturn")}

# One scene out of a clip that is otherwise plainly about somewhere else. Set high enough that
# a genuinely mixed clip keeps every tag it was given.
BODY_DOMINANCE = 0.6


def _related_bodies(a: str, b: str) -> bool:
    return (a, b) in ORBITS or (b, a) in ORBITS


def body_profile(rows: list[dict]) -> tuple[str, float, dict[str, int]]:
    """What the clip as a whole is about: the most common body, its share, and the counts."""
    counts: dict[str, int] = {}
    for row in rows:
        body = row.get("celestial_body") or "unknown"
        counts[body] = counts.get(body, 0) + 1
    if not counts:
        return "unknown", 0.0, counts
    dominant = max(counts, key=lambda b: (counts[b], b))
    return dominant, counts[dominant] / len(rows), counts


def resolve_body(scene_body: str, dominant: str, share: float, counts: dict[str, int]) -> tuple[str, str]:
    """Decide where a moment is set, and say where that came from.

    Scene-level extraction is trusted by default. It is overruled in exactly two cases, both
    of which put a marker on the wrong world in a spatial interface and are visibly wrong to
    anyone watching the clip:

      - the scene says nowhere at all, in a clip that is plainly somewhere
      - the scene is the only one of its kind in a clip that is otherwise about one place, and
        that place is not Earth and is unrelated to what the scene claims

    A Titan scene in a Saturn clip, or a briefing in a Mars clip, is left alone: both are
    ordinary, and overruling them would be the error.
    """
    if dominant == "unknown" or share < BODY_DOMINANCE:
        return scene_body, "scene"

    if scene_body == "unknown":
        return dominant, "video"

    if (
        counts.get(scene_body) == 1
        and scene_body not in COMPANION_BODIES
        and dominant not in COMPANION_BODIES
        and not _related_bodies(scene_body, dominant)
    ):
        return dominant, "video"

    return scene_body, "scene"


# Never worth preferring in retrieval: `unknown` says nothing, and Earth and its immediate
# surroundings are where the archive is made rather than a subject that narrows anything.
NEVER_TARGETED = frozenset({"unknown", "ground", "earth", "earth_orbit"})


def body_coverage(lookup: dict[str, list[dict]]) -> dict[str, int]:
    """How many scenes the archive actually holds for each world, after body resolution.

    This is a property of the corpus, not of any query, so it answers a question retrieval
    cannot: whether there is anything here at all. Semantic search always returns its best
    matches, and "a probe descends through an atmosphere under parachutes" scores well on a
    Venus question using Artemis reentry footage.
    """
    counts: dict[str, int] = {}
    for rows in lookup.values():
        dominant, share, profile = body_profile(rows)
        for row in rows:
            body, _ = resolve_body(
                row.get("celestial_body") or "unknown", dominant, share, profile
            )
            counts[body] = counts.get(body, 0) + 1
    return counts


# A mission that orbits, lands on or drives across exactly one world. If a scene set somewhere
# else carries one of these, the label is wrong: the compilation clip "1971 Aeronautics and Space
# Highlights" stamps `Mariner 9`, a Mars orbiter, on 62 of its 88 scenes including thirteen of the
# Moon, and two lunar scenes elsewhere are labelled `Mars Reconnaissance Orbiter` because the
# extractor heard "Lunar Reconnaissance Orbiter".
BOUND_MISSIONS: list[tuple[str, str]] = [
    (r"mariner|mars reconnaissance|curiosity|perseverance|viking|spirit\b|opportunity|sojourner"
     r"|phoenix|insight|odyssey|maven|pathfinder", "mars"),
    (r"apollo|ranger|surveyor|lunar reconnaissance|lunar prospector|clementine|lcross|ladee"
     r"|artemis|luna\b", "moon"),
    (r"juno|galileo", "jupiter"),
    (r"cassini|huygens", "saturn"),
    (r"magellan", "venus"),
    (r"messenger", "mercury"),
    (r"landsat|terra\b|aqua\b|suomi|nimbus|goes\b|noaa|aura\b|calipso|grace|icesat|smap", "earth"),
]

# Missions that legitimately turn up anywhere: flyby probes cross the solar system, and a
# telescope images whatever it is pointed at. Voyager at Jupiter, Cassini's probe at Titan and
# Hubble's view of Jupiter are all correct, and flagging them would be the error.
FREE_MISSIONS = (
    r"voyager|pioneer|new horizons|hubble|webb|spitzer|chandra|kepler|tess\b|swift|fermi"
    r"|soho|solar dynamics|\bsdo\b|stereo|parker|osiris|stardust|deep impact|dawn\b|hayabusa"
)

# Earth is where the archive is made and the void tags say nothing about a target, so neither
# can contradict a mission. A body inside its primary's system does not contradict it either.
NEUTRAL_BODIES = {"earth", "earth_orbit", "ground", "unknown", "deep_space"}
SYSTEM_OF = {"titan": "saturn", "moon": "earth"}


def in_system(body: str, target: str | None) -> bool:
    """Whether a moment counts as being about the world asked for.

    A moon belongs to the system it orbits: asked about Saturn and its moons, a Titan
    descent is the answer rather than a digression, and ranking it as off-topic pushed
    Cassini's Huygens footage out of a question that named it.
    """
    if target is None:
        return False
    return body == target or SYSTEM_OF.get(body) == target


def resolve_mission(mission: str | None, body: str) -> tuple[str | None, str]:
    """Drop a mission label that belongs to a different world than the scene is set on.

    The label is shown on the hover card, burned into the reel caption and, now, chooses the
    hardware that flies in the scene. Wrong, it makes lunar footage read as a Mars mission,
    which is exactly what a viewer notices first. Dropping is the honest repair: the correct
    mission is not recoverable from what the extractor returned, and "mission unknown" is
    already what the interface shows when there is none.
    """
    if not mission:
        return mission, "none"
    if body in NEUTRAL_BODIES or re.search(FREE_MISSIONS, mission, re.I):
        return mission, "scene"

    home = next((b for pattern, b in BOUND_MISSIONS if re.search(pattern, mission, re.I)), None)
    if home is None or home == body or SYSTEM_OF.get(body) == home:
        return mission, "scene"
    return None, "dropped"


# When a mission could have been doing anything at all. Bounds are deliberately generous: the
# point is to catch a date that is impossible, not to insist on the exact operating period. The
# upper bound is open for anything still flying.
OPEN = 2030
MISSION_WINDOWS: list[tuple[str, int, int]] = [
    (r"\bnaca\b", 1915, 1958), (r"\bx-\s?15\b", 1959, 1970),
    (r"explorer 1|explorer i\b", 1958, 1965), (r"\bmercury\b", 1958, 1963),
    (r"\bgemini\b", 1961, 1966), (r"apollo", 1961, 1975), (r"skylab", 1973, 1979),
    (r"mariner 4|mariner iv", 1964, 1967), (r"mariner 9|mariner ix", 1971, 1973),
    (r"mariner 10", 1973, 1975), (r"\bmariner\b", 1962, 1975),
    (r"\branger\b", 1961, 1965), (r"surveyor", 1966, 1968),
    (r"viking", 1975, 1983), (r"voyager", 1977, OPEN), (r"pioneer", 1958, 2003),
    (r"space shuttle|columbia|challenger|discovery|atlantis|endeavour|sts-", 1981, 2011),
    (r"magellan", 1989, 1994), (r"galileo", 1989, 2003),
    (r"hubble", 1990, OPEN), (r"soho", 1995, OPEN), (r"cassini|huygens", 1997, 2017),
    (r"mars global surveyor", 1996, 2007), (r"chandra", 1999, OPEN),
    (r"stardust", 1999, 2011), (r"terra\b", 1999, OPEN),
    (r"mars odyssey|\bodyssey\b", 2001, OPEN), (r"aqua\b", 2002, OPEN),
    (r"spirit\b|opportunity", 2003, 2019), (r"deep impact", 2005, 2013),
    (r"mars reconnaissance", 2005, OPEN), (r"new horizons", 2006, OPEN),
    (r"phoenix", 2007, 2009), (r"dawn\b", 2007, 2018),
    (r"lunar reconnaissance|\blro\b", 2009, OPEN), (r"kepler", 2009, 2018),
    (r"\bwise\b|neowise", 2009, OPEN), (r"\bsdo\b|solar dynamics", 2010, OPEN),
    (r"curiosity|mars science laboratory", 2011, OPEN), (r"juno", 2011, OPEN),
    (r"maven", 2013, OPEN), (r"osiris", 2016, OPEN), (r"artemis", 2017, OPEN),
    (r"perseverance|ingenuity", 2020, OPEN), (r"webb|jwst", 2021, OPEN),
    (r"international space station", 1998, OPEN), (r"landsat", 1972, OPEN),
]

# The date came from the scene's own content, so it outranks anything inferred about it.
FIRM_ERA_AXIS = "scene"


def mission_window(mission: str | None) -> tuple[int, int] | None:
    if not mission:
        return None
    for pattern, low, high in MISSION_WINDOWS:
        if re.search(pattern, mission, re.I):
            return low, high
    return None


def resolve_era(era_start: int | None, era_axis: str | None,
                mission: str | None) -> tuple[int | None, str | None, str | None]:
    """Correct a date that its own mission could not have been part of.

    `era_start` is only sometimes read from what a scene says. When the extractor found no
    date it falls back to the clip as a whole, and a compilation dated once at the top carries
    that year into every scene under it: a Curiosity segment came back as 1990, which put a
    2012 rover before Hubble on the timeline. The mission's operating window is firmer than
    that fallback, so it wins, and the axis says so.

    A date the scene itself stated is never overruled. Archive footage is full of retrospect,
    and a Perseverance clip recounting Viking is not a mistake to fix.
    """
    span = mission_window(mission)
    if era_start is None or span is None or era_axis == FIRM_ERA_AXIS:
        return era_start, era_axis, None
    low, high = span
    if low <= era_start <= high:
        return era_start, era_axis, None
    corrected = low if era_start < low else high
    return corrected, "mission", f"{era_start} is outside {mission}'s {low}-{high}"


def attach_era(evidence: Evidence, lookup: dict[str, list[dict]]) -> Evidence:
    """Join a retrieved moment to the mission_meta row covering it.

    Rows are scene aligned, so the row whose window contains the shot start is the
    right one. Falls back to the nearest row rather than dropping the evidence.
    """
    rows = lookup.get(evidence.nasa_id) or []
    if not rows:
        return evidence

    match = next((r for r in rows if r["start"] <= evidence.start < r["end"]), None)
    if match is None:
        match = min(rows, key=lambda r: abs(r["start"] - evidence.start))

    evidence.era_start = match.get("era_start")
    evidence.era_axis = match.get("era_axis")
    evidence.era_basis = match.get("era_basis")
    evidence.mission = match.get("primary_mission")
    evidence.title = match.get("title") or ""
    evidence.published_year = match.get("published_year")
    evidence.event_type = match.get("event_type") or "other"

    dominant, share, counts = body_profile(rows)
    evidence.celestial_body, evidence.body_axis = resolve_body(
        match.get("celestial_body") or "unknown", dominant, share, counts
    )
    # After the world is settled, because that is what the mission is checked against.
    evidence.mission, evidence.mission_axis = resolve_mission(
        evidence.mission, evidence.celestial_body
    )
    # And after the mission, because a label dropped as belonging elsewhere must not then be
    # used to date the moment it was just found not to describe.
    evidence.era_start, evidence.era_axis, correction = resolve_era(
        evidence.era_start, evidence.era_axis, evidence.mission
    )
    if correction:
        evidence.era_basis = correction
    return evidence


# ------------------------------------------------------------------ decompose

DECOMPOSE_PROMPT = """You are planning retrieval over an archive of NASA video.

The archive is narrated in NASA's own institutional language. A researcher's phrasing
often does not match it: an archive clip says "the first of two rovers" where a
researcher says "twin rovers". Your job is to bridge that gap.

Question: {question}

Return JSON only:
{{
  "sub_questions": ["2 to 4 distinct aspects this question breaks into"],
  "phrasings": ["4 to 7 search strings, mixing the researcher's wording with the",
                "plain declarative style a NASA narrator would actually use"],
  "visual_phrasings": ["2 to 4 strings describing what would be VISIBLE on screen,",
                       "for searching visual scene descriptions rather than speech"],
  "needs_chronology": true,
  "answerable": true,
  "target_body": null,
  "rationale": "one sentence on how you decomposed it"
}}

Rules:
- Phrasings must be statements the narration could plausibly contain, not questions.
- Do not invent mission names or dates that the question does not imply.
- needs_chronology is true when the question is about change over time.
- answerable is false only when the question is unintelligible, or is about nothing to
  do with spaceflight, astronomy or Earth observation. Set it false rather than reading a
  topic into words that carry none: gibberish decomposed into plausible-sounding spacecraft
  operations retrieves real launch footage at full confidence and answers a question nobody
  asked. If the subject is real but the archive may simply not cover it, answerable is still
  true: that is for the evidence to settle, not you.
- When answerable is false, return empty lists and say why in rationale.
- target_body is where the footage should be SET, not the subject it discusses, and must be one
  of: mars, moon, sun, venus, mercury, jupiter, saturn, titan, comet_asteroid, deep_space.
  "Missions to explore the moon" is moon. "How did our understanding of water change" is null,
  because the answer spans several worlds. Work carried out on Earth about another world is
  null: rehearsals in a Mars yard, mission control simulations, hardware testing and briefings
  are all filmed here, and a question about them wants that footage rather than the surface it
  prepares for. Guessing narrows the search for no reason; leaving it null when the question
  does name one setting lets material about somewhere else take a place in the answer.
"""

SYNTHESIS_PROMPT = """You are answering a research question using only the evidence below.

Each item is a real moment from NASA archival video, with the year of the events it
discusses and how that year was determined.

Question: {question}

Evidence ({count} moments, numbered [1] to [{count}]):
{evidence}

Return JSON only:
{{
  "answer": "4 to 8 sentences. Cite evidence inline as [1], [2]. Say something the",
  "citations": [1, 2],
  "chronology": [{{"era": 1965, "claim": "what the archive shows about this period", "citations": [1]}}],
  "caveats": "what the evidence does not establish, or empty string"
}}

Rules:
- Account for every one of the {count} moments. Each is cut into a reel the reader watches
  beside your answer, so a moment you never cite plays as footage nothing explains. Group
  related moments on one claim rather than writing a sentence each. If a moment genuinely does
  not bear on the question, cite it once in caveats saying what it shows instead. Answers that
  used 2 of 8 moments and left six unexplained on screen are the failure to avoid.
- Every factual claim must carry a citation, the opening sentence included. A sentence that
  summarises the answer is still asserting it, and carries the citations of everything it
  summarises.
- The answer must state something no single clip states on its own.
- chronology carries the dated spine of the answer and is drawn as a timeline, so one point
  is not a chronology. Give a point for each distinct era the evidence covers, in order,
  whenever the moments span more than one.
- If evidence dates rest on `era_axis: video` or `published`, say so in caveats
  rather than presenting them as certain.
- Evidence set on one world is not evidence about another. If the question asks about a
  particular world and a clip is set somewhere else, do not reason from what that footage
  implies or suggests about the world asked for. Say plainly that the archive does not show
  it. An answer that concedes "neither clip shows Venus" and then describes Venus exploration
  anyway is worse than a short answer that stops at what the clips hold.
- Do not use knowledge beyond the evidence.
"""


def _parse_json(raw: Any) -> dict:
    """`generate_text` returns {"output": ...} on the hosted path, and the payload can
    still be a JSON string, sometimes fenced."""
    payload = raw.get("output") if isinstance(raw, dict) and "output" in raw else raw
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


def decompose(coll, question: str, trace: Trace) -> dict:
    raw = coll.generate_text(
        prompt=DECOMPOSE_PROMPT.format(question=question),
        model_name="pro",
        response_type="json",
    )
    plan = _parse_json(raw)

    phrasings = [p for p in (plan.get("phrasings") or []) if isinstance(p, str) and p.strip()]
    visual = [p for p in (plan.get("visual_phrasings") or []) if isinstance(p, str) and p.strip()]
    if question not in phrasings:
        phrasings.insert(0, question)

    answerable = bool(plan.get("answerable", True))
    target = str(plan.get("target_body") or "").strip().lower() or None
    # Earth is the archive's default backdrop: 473 of 1,484 scenes, plus 139 `ground` and 114
    # `earth_orbit`. Preferring it sorts nothing into order and quietly promotes whatever
    # happens to be filmed here, so a question about rehearsing Mars operations on Earth took
    # X-15 flight-test footage at 0.639 over the mission control rehearsal it was asking for.
    # Those runs rank on score alone.
    if target not in schema.CELESTIAL_BODIES or target in NEVER_TARGETED:
        target = None

    plan = {
        "sub_questions": plan.get("sub_questions") or [],
        "phrasings": phrasings[:8],
        "visual_phrasings": visual[:4],
        "needs_chronology": bool(plan.get("needs_chronology", True)),
        "answerable": answerable,
        "target_body": target,
        "rationale": plan.get("rationale") or "",
    }
    summary = (
        f"{len(plan['sub_questions'])} sub-questions, "
        f"{len(plan['phrasings'])} spoken phrasings, {len(plan['visual_phrasings'])} visual"
        if answerable
        else "question is not answerable from this archive, stopping before retrieval"
    )
    trace.add("decompose", summary, **plan)
    return plan


# ------------------------------------------------------------------- retrieve

def _matched_text(shot) -> str:
    """The words a hit actually matched on.

    `Shot.text` is documented as the matched text but comes back `None` from every index in
    this collection; the text is in `metadata["embedded_text"]`. Reading only the attribute
    meant every answer was synthesised from titles, dates and identifiers with no transcript
    and no scene description under it, and the hover cards that exist to let a viewer catch a
    bad tag showed nothing. Both are checked, attribute first, so this keeps working if the
    SDK starts populating it.
    """
    text = (getattr(shot, "text", None) or "").strip()
    if text:
        return text
    metadata = getattr(shot, "metadata", None) or {}
    return str(metadata.get("embedded_text") or metadata.get("on_screen_text") or "").strip()


def _search(coll, query: str, index_names: list[str], top_k: int,
            threshold: float) -> tuple[list[Evidence], list[dict]]:
    kept: list[Evidence] = []
    rejected: list[dict] = []
    try:
        result = coll.semantic_search(query=query, index_names=index_names, top_k=top_k)
    except Exception as exc:  # noqa: BLE001
        return [], [{"reason": "search_error", "detail": f"{type(exc).__name__}: {exc}",
                     "query": query, "index": index_names[0]}]

    for shot in result.get_shots():
        score = float(shot.search_score or 0.0)
        item = Evidence(
            nasa_id="", video_id=shot.video_id, start=float(shot.start), end=float(shot.end),
            score=round(score, 4), index=index_names[0], query=query,
            text=_matched_text(shot),
        )
        if score < threshold:
            rejected.append({"reason": "below_threshold", "score": round(score, 4),
                             "threshold": threshold, "video_id": shot.video_id,
                             "start": round(float(shot.start), 1), "index": index_names[0]})
            continue
        kept.append(item)
    return kept, rejected


def retrieve(coll, plan: dict, trace: Trace, top_k: int, threshold: float,
             id_by_video: dict[str, str]) -> tuple[list[Evidence], list[dict]]:
    """Query each index separately, once per phrasing, then merge.

    Never a single multi-index call: scores across indexes are not comparable and the
    union ranking silently drops whole indexes.
    """
    found: dict[tuple[str, float], Evidence] = {}
    all_rejects: list[dict] = []
    per_index: dict[str, int] = {}

    passes = [(plan["phrasings"], TRANSCRIPT_INDEXES),
              (plan["visual_phrasings"], VISUAL_INDEXES),
              (plan["visual_phrasings"][:2], TEXT_ON_SCREEN_INDEXES)]

    for queries, index_names in passes:
        name = index_names[0]
        # Per-index floor, scaled from the caller's baseline so --threshold still works.
        floor = THRESHOLD_BY_INDEX.get(name, threshold)
        if threshold != DEFAULT_THRESHOLD:
            floor = floor * (threshold / DEFAULT_THRESHOLD)
        for query in queries:
            kept, rejects = _search(coll, query, index_names, top_k, floor)
            all_rejects += rejects
            for item in kept:
                item.nasa_id = id_by_video.get(item.video_id, item.video_id)
                existing = found.get(item.key)
                # The same moment can surface for several phrasings. Keep the best
                # score, and remember it was corroborated.
                if existing is None or item.score > existing.score:
                    found[item.key] = item
                per_index[name] = per_index.get(name, 0) + 1

    evidence = sorted(found.values(), key=lambda e: -e.score)
    trace.add(
        "retrieve",
        f"{len(evidence)} distinct moments from {len(set(e.nasa_id for e in evidence))} clips",
        queries_run=sum(len(q) for q, _ in passes),
        hits_by_index=per_index,
        rejected_below_threshold=len(all_rejects),
        thresholds={name: THRESHOLD_BY_INDEX.get(name, threshold) for name in per_index},
    )
    return evidence, all_rejects


# ------------------------------------------------------------------ diversify

def diversify(evidence: list[Evidence], trace: Trace, cap: int = PER_VIDEO_CAP,
              limit: int = MAX_EVIDENCE,
              target_body: str | None = None) -> tuple[list[Evidence], list[dict]]:
    """Cap how much any one clip can contribute.

    Without this, a broad question returns everything from whichever clip is densest
    on the topic, and a chronology assembled from one source is fiction.
    """
    # Round-robin by clip rather than a single pass down the score ranking. A plain
    # score walk with a cap still front-loads the densest clips: they fill their quota
    # before a thinly covered decade gets its first slot at all. Taking one shot from
    # every clip before anyone gets a second maximises how much of the archive is
    # represented, which is the whole point of the chronology.
    # A question about one world prefers moments set on it. Asked about missions to the Moon,
    # nine lunar clips were passed over so that a Titan passage at 0.659 and a Mars passage at
    # 0.632 could take the last two slots, because the ranking only ever looked at the score.
    # This is a preference and not a filter: when there is not enough on-topic material the
    # slots still fill, rather than the answer quietly shrinking.
    def rank(item: Evidence) -> tuple[int, float]:
        return (0 if in_system(item.celestial_body, target_body) else 1, -item.score)

    by_clip: dict[str, list[Evidence]] = {}
    for item in evidence:
        by_clip.setdefault(item.nasa_id, []).append(item)
    for shots in by_clip.values():
        shots.sort(key=rank)

    # Each clip offers up to `cap` shots, ranked. A shot is chosen on three things in order:
    # whether it is set on the world asked about, how many shots its clip has already given
    # (so breadth still beats depth), and its score. Ordering the rounds ahead of the target
    # was wrong: asked about Saturn and its moons, two ring passages at 0.731 and 0.730 were
    # dropped as second shots while off-topic clips contributed first shots at lower scores.
    candidates = [
        (0 if in_system(shot.celestial_body, target_body) else 1, round_index, -shot.score,
         nasa_id, shot)
        for nasa_id, shots in by_clip.items()
        for round_index, shot in enumerate(shots[:cap])
    ]
    candidates.sort(key=lambda c: c[:3])

    per_video: dict[str, int] = {}
    kept: list[Evidence] = []
    for _, _, _, nasa_id, shot in candidates[:limit]:
        kept.append(shot)
        per_video[nasa_id] = per_video.get(nasa_id, 0) + 1

    chosen = {item.key for item in kept}
    # The body travels with the drop so it can be checked afterwards that nothing set on the
    # world asked about was passed over for something that was not. Without it a preference
    # that silently stopped working would look identical to one with nothing on-topic to find.
    dropped = [
        {"reason": "per_video_cap" if per_video.get(item.nasa_id, 0) >= cap else "evidence_limit",
         "nasa_id": item.nasa_id, "start": round(item.start, 1), "score": item.score, "cap": cap,
         "celestial_body": item.celestial_body}
        for item in evidence if item.key not in chosen
    ]
    kept.sort(key=lambda e: -e.score)

    trace.add(
        "diversify",
        f"kept {len(kept)} across {len(per_video)} clips, dropped {len(dropped)}"
        + (f", preferring {target_body}" if target_body else ""),
        per_video_cap=cap,
        **({"target_body": target_body,
            "on_target": sum(1 for k in kept if in_system(k.celestial_body, target_body))}
           if target_body else {}),
        kept_per_clip=per_video,
        dropped=dropped[:12],
    )
    return kept, dropped


# ----------------------------------------------------------------- passages

# A moment longer than this stops being a moment and becomes the clip. Runs of matching cells go
# well past it: one Curiosity clip returned seventeen touching cells, 170 seconds unbroken.
MAX_PASSAGE_SECONDS = 40.0
# Cells are ten seconds on a grid, so touching cells differ by ten. Allow a little slack for the
# ragged 6% and for a single missing cell in the middle of an otherwise continuous run.
CELL_GAP_TOLERANCE = 12.0


def build_passages(evidence: list[Evidence], trace: Trace,
                   max_seconds: float = MAX_PASSAGE_SECONDS) -> list[Evidence]:
    """Join consecutive matching cells from one clip into a single passage.

    Retrieval works on ten-second cells, and when a clip really covers a subject it returns a
    run of them. The diversity cap then kept exactly one cell per clip and discarded the rest,
    so an answer was fourteen unrelated ten-second fragments: nothing long enough to develop a
    point, and consecutive shots from unrelated productions.

    Merging first means the cap chooses between *passages*. Breadth across the archive is
    unchanged, because a passage still counts as one contribution from one clip; what changes is
    that the contribution is long enough to say something.
    """
    by_clip: dict[str, list[Evidence]] = {}
    for item in evidence:
        by_clip.setdefault(item.nasa_id, []).append(item)

    passages: list[Evidence] = []
    merged_cells = 0

    for items in by_clip.values():
        items.sort(key=lambda e: e.start)
        run: list[Evidence] = []

        def flush(run: list[Evidence]) -> None:
            nonlocal merged_cells
            if not run:
                return
            # The strongest cell carries the passage's identity: its score is what the cap ranks
            # on, and its index is the one that found it.
            best = max(run, key=lambda e: e.score)
            head = run[0]
            head.end = run[-1].end
            head.score = best.score
            head.index = best.index
            head.query = best.query
            head.cells = len(run)
            head.text = " ".join(dict.fromkeys(e.text for e in run if e.text)).strip()
            if len(run) > 1:
                merged_cells += len(run)
            passages.append(head)

        for item in items:
            if not run:
                run = [item]
                continue
            touching = item.start - run[-1].end <= CELL_GAP_TOLERANCE
            within_budget = item.end - run[0].start <= max_seconds
            if touching and within_budget:
                run.append(item)
            else:
                flush(run)
                run = [item]
        flush(run)

    passages.sort(key=lambda e: -e.score)

    lengths = [round(p.end - p.start) for p in passages if p.cells > 1]
    trace.add(
        "passages",
        f"{len(evidence)} cells joined into {len(passages)} passages, "
        f"{sum(1 for p in passages if p.cells > 1)} of them continuous runs",
        cells_merged=merged_cells,
        longest_seconds=max(lengths) if lengths else 0,
    )
    return passages


# --------------------------------------------------------------- clip windows

def refine_windows(coll, evidence: list[Evidence], trace: Trace) -> list[Evidence]:
    """Move each moment's bounds off the indexing grid and onto sentence boundaries.

    Retrieval works on ten-second cells because that is what the corpus was segmented into.
    Playback should not: a cell opens wherever ten seconds happened to land, so clips began
    mid-clause and carried whatever else shared the cell. `speech.sentence_window` reads the
    word timings and returns the sentences the cell sits in.

    Transcripts are fetched concurrently. Fourteen sequential round trips would add most of a
    minute to a run that already takes ninety seconds.
    """
    if not evidence:
        return evidence

    def fetch(video_id: str):
        try:
            video = coll.get_video(video_id)
            return video_id, video, speech.load_words(video)
        except Exception:  # noqa: BLE001 - one unreadable source must not lose the answer
            return video_id, None, []

    video_ids = list({item.video_id for item in evidence})
    with ThreadPoolExecutor(max_workers=min(8, len(video_ids))) as pool:
        fetched = {vid: (video, words) for vid, video, words in pool.map(fetch, video_ids)}

    counts: dict[str, int] = {}
    widened = 0
    for item in evidence:
        video, words = fetched.get(item.video_id, (None, []))
        length = 0.0
        if video is not None:
            try:
                length = float(video.length or 0.0)
            except (TypeError, ValueError):
                length = 0.0

        # The ceiling is the passage budget plus room to finish the sentence it lands in,
        # not the single-cell clip length.
        start, end, axis, spoken = speech.sentence_window(
            words, item.start, item.end,
            min_seconds=reel.MIN_CLIP_SECONDS,
            max_seconds=MAX_PASSAGE_SECONDS + speech.MAX_REACH_FORWARD,
            source_length=length,
        )
        if axis == "sentence":
            if end - start > item.end - item.start:
                widened += 1
            item.start, item.end = start, end
            item.spoken = spoken
        item.clip_axis = axis
        counts[axis] = counts.get(axis, 0) + 1

    trace.add(
        "window",
        f"{counts.get('sentence', 0)} of {len(evidence)} cut to sentence bounds, "
        f"{counts.get('scene', 0)} left on the grid",
        clip_axis_counts=counts,
        widened=widened,
    )
    return evidence


# -------------------------------------------------------------------- ordering

def order_chronologically(evidence: list[Evidence], trace: Trace) -> list[Evidence]:
    ordered = sorted(
        evidence,
        key=lambda e: (e.era_start if e.era_start else 9999, e.nasa_id, e.start),
    )
    axes: dict[str, int] = {}
    for item in ordered:
        axes[item.era_axis or "unknown"] = axes.get(item.era_axis or "unknown", 0) + 1

    dropped_missions = sum(1 for o in ordered if o.mission_axis == "dropped")

    span = [o.era_start for o in ordered if o.era_start]
    trace.add(
        "order",
        f"ordered by era {min(span) if span else '-'}-{max(span) if span else '-'}"
        + (f", {dropped_missions} mission label(s) dropped as belonging elsewhere"
           if dropped_missions else ""),
        era_axis_counts=axes,
        **({"missions_dropped": dropped_missions} if dropped_missions else {}),
        note="era_axis 'scene' is stated in the footage; 'video' is inferred from clip "
             "context; 'published' is the upload date and carries no historical claim",
    )
    return ordered


def timeline_histogram(coll, trace: Trace) -> list[dict]:
    """Decade distribution across the whole archive, computed server-side."""
    try:
        rows = coll.aggregate(index_name=indexing.MISSION_META,
                              group_by="era_start", metric="count")
    except Exception as exc:  # noqa: BLE001
        trace.add("aggregate", f"histogram unavailable: {type(exc).__name__}")
        return []

    rows = rows.get("results", []) if isinstance(rows, dict) else rows
    decades: dict[int, int] = {}
    for row in rows:
        try:
            year = int(float(row.get("era_start")))
        except (TypeError, ValueError):
            continue
        decades[year // 10 * 10] = decades.get(year // 10 * 10, 0) + int(row.get("value", 0))

    histogram = [{"decade": d, "scenes": n} for d, n in sorted(decades.items())]
    trace.add("aggregate", f"archive spans {len(histogram)} decades", histogram=histogram)
    return histogram


# ------------------------------------------------------------------ synthesis

def format_evidence(evidence: list[Evidence]) -> str:
    lines = []
    for i, item in enumerate(evidence, 1):
        era = f"{item.era_start} ({item.era_axis})" if item.era_start else "undated"
        # `spoken` is what the clip actually says once its bounds were snapped to sentences: the
        # matched text plus whatever was cut off mid-clause by the grid. It is a superset of
        # `text`, so it is the better thing to reason over when it exists.
        body = item.spoken or item.text
        # `set on` is here so the rule against reasoning across worlds has something to read.
        # Without it the model had to infer the setting from the title, and inferred wrongly.
        lines.append(
            f"[{i}] {item.title or item.nasa_id} | {item.nasa_id} | {item.start:.0f}-{item.end:.0f}s "
            f"| era {era} | mission {item.mission or 'unknown'} | set on {item.celestial_body} "
            f"| {item.event_type} | via {item.index} score {item.score}\n"
            f"     {body[:700] or '(no transcript text; visual match)'}"
        )
    return "\n".join(lines)


def _clean_citations(raw: Any, count: int) -> list[int]:
    """Keep only citations that point at a real evidence item.

    The numbers come back from a language model, so they can be strings, floats, repeats,
    or an index past the end of the list. The UI turns a citation straight into a seek and
    a camera move, so an out-of-range number would play the wrong clip rather than fail
    loudly. Order is preserved: it is the reading order of the answer.
    """
    cleaned: list[int] = []
    for value in raw or []:
        try:
            n = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= count and n not in cleaned:
            cleaned.append(n)
    return cleaned


def synthesize(coll, question: str, evidence: list[Evidence], trace: Trace) -> dict:
    if not evidence:
        trace.add("synthesize", "no evidence, refusing to answer")
        return {"answer": "", "citations": [], "chronology": [],
                "caveats": "No evidence passed the relevance threshold."}

    raw = coll.generate_text(
        prompt=SYNTHESIS_PROMPT.format(question=question, evidence=format_evidence(evidence),
                                       count=len(evidence)),
        model_name="pro",
        response_type="json",
    )
    result = _parse_json(raw)
    answer = str(result.get("answer") or "")
    count = len(evidence)

    citations = _clean_citations(result.get("citations"), count)
    chronology = []
    for point in result.get("chronology") or []:
        if not isinstance(point, dict):
            continue
        chronology.append({**point, "citations": _clean_citations(point.get("citations"), count)})

    dropped = len(result.get("citations") or []) - len(citations)
    # Every moment is cut into the reel, so one the answer never refers to plays as footage
    # nothing explains. Counting it here makes that visible in the trace instead of only
    # showing up as a viewer wondering why a clip is there.
    referenced = set(citations)
    for point in chronology:
        referenced.update(point["citations"])
    uncited = [n for n in range(1, count + 1) if n not in referenced]
    trace.add(
        "synthesize",
        f"{len(answer.split())} words, {len(referenced)} of {count} moments cited"
        + (f", {len(uncited)} unexplained" if uncited else ""),
        chronology_points=len(chronology),
        caveats=result.get("caveats") or "",
        cited_moments=sorted(referenced),
        uncited_moments=uncited,
        **({"dropped_citations": dropped} if dropped > 0 else {}),
    )
    return {
        "answer": answer,
        "citations": citations,
        "chronology": chronology,
        "caveats": result.get("caveats") or "",
    }


# ------------------------------------------------------------------------ run

def ask(question: str, *, top_k: int = DEFAULT_TOP_K, threshold: float = DEFAULT_THRESHOLD,
        cap: int = PER_VIDEO_CAP, coll=None, id_by_video: dict[str, str] | None = None) -> dict:
    coll = coll or vc.get_collection()
    trace = Trace()
    trace.add("question", question)

    if id_by_video is None:
        import manifest
        id_by_video = {e["video_id"]: n for n, e in manifest.load().items() if e.get("video_id")}

    lookup = load_era_lookup()

    plan = decompose(coll, question, trace)

    def unsearched(caveats: str) -> dict:
        return {
            "question": question,
            "plan": plan,
            "answer": {"answer": "", "citations": [], "chronology": [], "caveats": caveats},
            "evidence": [],
            "rejected": {"below_threshold": [], "diversity": [],
                         "counts": {"below_threshold": 0, "diversity": 0}},
            "timeline": timeline_histogram(coll, trace),
            "trace": trace.to_list(),
        }

    if not plan["answerable"]:
        # Retrieval always returns something. Nonsense decomposed into plausible spacecraft
        # operations matched real launch footage at higher scores than a genuine question
        # about hurricanes did, and the answer read as authoritative. Refusing here is the
        # only place the distinction can still be made honestly.
        return unsearched(
            "This question was not searched: "
            + (plan["rationale"] or "it does not describe anything this archive holds.")
        )

    # A real subject the archive simply does not hold. `answerable` cannot catch this: Venus is
    # plainly spaceflight, so the plan is right to proceed, and the target-body preference in
    # `diversify` is a preference rather than a filter, so with nothing on the target it falls
    # back to score. Asked how NASA explored Venus, the archive returned Artemis reentry and
    # Mars descent footage and the synthesis reasoned from it that entry-and-descent engineering
    # was used "for other planetary missions, including Venus". Saying there is nothing here is
    # the honest answer, and only the corpus can say so.
    target = plan["target_body"]
    if target:
        coverage = body_coverage(lookup)
        if not coverage.get(target):
            held = ", ".join(
                f"{body} ({count})"
                for body, count in sorted(coverage.items(), key=lambda kv: -kv[1])
                if body not in ("unknown", "ground") and count
            )
            trace.add(
                "coverage",
                f"archive holds no scenes set on {target}, refusing before retrieval",
                target_body=target,
                bodies_held=coverage,
            )
            return unsearched(
                f"This archive holds no footage set on {target}, so the question was not "
                f"searched: any clips returned would have been about somewhere else. "
                f"The 87 clips cover {held}."
            )

    evidence, rejects = retrieve(coll, plan, trace, top_k, threshold, id_by_video)
    # Join runs of touching cells before the cap sees them, so what it chooses between is
    # passages rather than isolated ten-second fragments.
    evidence = build_passages(evidence, trace)
    evidence = [attach_era(e, lookup) for e in evidence]
    kept, dropped = diversify(evidence, trace, cap=cap, target_body=plan["target_body"])
    # After the era join, which matches a moment to the scene row containing its start: snapping
    # first could move a start into the previous cell and take that cell's date with it.
    kept = refine_windows(coll, kept, trace)
    ordered = order_chronologically(kept, trace)
    histogram = timeline_histogram(coll, trace)
    answer = synthesize(coll, question, ordered, trace)

    return {
        "question": question,
        "plan": plan,
        "answer": answer,
        "evidence": [asdict(e) for e in ordered],
        "rejected": {"below_threshold": rejects[:20], "diversity": dropped[:20],
                     "counts": {"below_threshold": len(rejects), "diversity": len(dropped)}},
        "timeline": histogram,
        "trace": trace.to_list(),
    }
