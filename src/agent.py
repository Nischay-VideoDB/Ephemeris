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
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import indexing
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
PER_VIDEO_CAP = 3
MAX_EVIDENCE = 14

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
"""

SYNTHESIS_PROMPT = """You are answering a research question using only the evidence below.

Each item is a real moment from NASA archival video, with the year of the events it
discusses and how that year was determined.

Question: {question}

Evidence:
{evidence}

Return JSON only:
{{
  "answer": "3 to 6 sentences. Cite evidence inline as [1], [2]. Say something the",
  "citations": [1, 2],
  "chronology": [{{"era": 1965, "claim": "what the archive shows about this period", "citations": [1]}}],
  "caveats": "what the evidence does not establish, or empty string"
}}

Rules:
- Every factual claim must carry a citation.
- The answer must state something no single clip states on its own.
- If evidence dates rest on `era_axis: video` or `published`, say so in caveats
  rather than presenting them as certain.
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

    plan = {
        "sub_questions": plan.get("sub_questions") or [],
        "phrasings": phrasings[:8],
        "visual_phrasings": visual[:4],
        "needs_chronology": bool(plan.get("needs_chronology", True)),
        "answerable": answerable,
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
              limit: int = MAX_EVIDENCE) -> tuple[list[Evidence], list[dict]]:
    """Cap how much any one clip can contribute.

    Without this, a broad question returns everything from whichever clip is densest
    on the topic, and a chronology assembled from one source is fiction.
    """
    # Round-robin by clip rather than a single pass down the score ranking. A plain
    # score walk with a cap still front-loads the densest clips: they fill their quota
    # before a thinly covered decade gets its first slot at all. Taking one shot from
    # every clip before anyone gets a second maximises how much of the archive is
    # represented, which is the whole point of the chronology.
    by_clip: dict[str, list[Evidence]] = {}
    for item in evidence:
        by_clip.setdefault(item.nasa_id, []).append(item)
    for shots in by_clip.values():
        shots.sort(key=lambda e: -e.score)

    # Clips whose best shot scores highest go first, so ties in coverage break on quality.
    order = sorted(by_clip, key=lambda nid: -by_clip[nid][0].score)

    per_video: dict[str, int] = {}
    kept: list[Evidence] = []

    for round_index in range(cap):
        for nasa_id in order:
            shots = by_clip[nasa_id]
            if round_index >= len(shots) or len(kept) >= limit:
                continue
            kept.append(shots[round_index])
            per_video[nasa_id] = per_video.get(nasa_id, 0) + 1

    chosen = {item.key for item in kept}
    dropped = [
        {"reason": "per_video_cap" if per_video.get(item.nasa_id, 0) >= cap else "evidence_limit",
         "nasa_id": item.nasa_id, "start": round(item.start, 1), "score": item.score, "cap": cap}
        for item in evidence if item.key not in chosen
    ]
    kept.sort(key=lambda e: -e.score)

    trace.add(
        "diversify",
        f"kept {len(kept)} across {len(per_video)} clips, dropped {len(dropped)}",
        per_video_cap=cap,
        kept_per_clip=per_video,
        dropped=dropped[:12],
    )
    return kept, dropped


# -------------------------------------------------------------------- ordering

def order_chronologically(evidence: list[Evidence], trace: Trace) -> list[Evidence]:
    ordered = sorted(
        evidence,
        key=lambda e: (e.era_start if e.era_start else 9999, e.nasa_id, e.start),
    )
    axes: dict[str, int] = {}
    for item in ordered:
        axes[item.era_axis or "unknown"] = axes.get(item.era_axis or "unknown", 0) + 1

    span = [o.era_start for o in ordered if o.era_start]
    trace.add(
        "order",
        f"ordered by era {min(span) if span else '-'}-{max(span) if span else '-'}",
        era_axis_counts=axes,
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
        lines.append(
            f"[{i}] {item.title or item.nasa_id} | {item.nasa_id} | {item.start:.0f}-{item.end:.0f}s "
            f"| era {era} | mission {item.mission or 'unknown'} | via {item.index} "
            f"score {item.score}\n     {item.text[:320] or '(no transcript text; visual match)'}"
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
        prompt=SYNTHESIS_PROMPT.format(question=question, evidence=format_evidence(evidence)),
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
    trace.add(
        "synthesize",
        f"{len(answer.split())} words, {len(citations)} citations",
        chronology_points=len(chronology),
        caveats=result.get("caveats") or "",
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

    if not plan["answerable"]:
        # Retrieval always returns something. Nonsense decomposed into plausible spacecraft
        # operations matched real launch footage at higher scores than a genuine question
        # about hurricanes did, and the answer read as authoritative. Refusing here is the
        # only place the distinction can still be made honestly.
        return {
            "question": question,
            "plan": plan,
            "answer": {
                "answer": "",
                "citations": [],
                "chronology": [],
                "caveats": "This question was not searched: "
                           + (plan["rationale"] or "it does not describe anything this archive holds."),
            },
            "evidence": [],
            "rejected": {"below_threshold": [], "diversity": [],
                         "counts": {"below_threshold": 0, "diversity": 0}},
            "timeline": timeline_histogram(coll, trace),
            "trace": trace.to_list(),
        }

    evidence, rejects = retrieve(coll, plan, trace, top_k, threshold, id_by_video)
    evidence = [attach_era(e, lookup) for e in evidence]
    kept, dropped = diversify(evidence, trace, cap=cap)
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
