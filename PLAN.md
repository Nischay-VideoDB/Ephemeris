# Mission Control: Project Plan

Submission for VideoDB "Unlock the Footage: Global Media Intelligence Hackathon".
Judging: technical execution 40%, creativity and originality 30%, depth of VideoDB usage 30%.

Technical facts and API gotchas live in [NOTES.md](NOTES.md). This file is the what and why.

---

## Thesis

**A research agent that turns NASA's archive into cited answers and auto-edited evidence reels
by reasoning across decades of footage.**

Not a search box that returns clips. The distinction is the whole submission. A retrieval demo
with a nice skin caps out at runner-up; an agent that reasons over a corpus is what wins.

## User and job

A **documentary researcher assembling archival evidence for a segment.** The reel is their
deliverable, not a byproduct. This framing gives the demo stakes and matches the event's
"actionable intelligence" language. "Search space history" is a toy framing and is rejected.

## The two demo queries

Everything is built to make these two bulletproof. Two flawless queries beat eight flaky ones.

1. **"Trace how our understanding of water on Mars changed over time."**
   Forces cross-mission chronological synthesis. Transcript search physically cannot answer it.
   Output: cited prose answer no single clip contains, plus a ~90s stitched reel ordered by
   mission date, every clip timestamped and sourced.

2. **A visual-only query** (stage separation, EVA, docking) where narration never says the words.
   Demoed side by side: spoken-index search returns nothing, scene-index search returns the exact
   moment. Lets a judge verify multimodal depth in five seconds.

## Dataset

NASA Image and Video Library (`images-api.nasa.gov`). Public domain, no auth, no ToS friction,
direct HD download, 60+ years of footage.

Honest read: NASA is the *default* safe dataset, so it buys near-zero creativity points on its
own. Expect other space submissions. The differentiator is what the agent does, not what it eats.

Scope: one narrow theme (Mars water evidence across missions), roughly 20-30 clips. Not "all of
NASA". Curated so retrieval quality is verifiable.

Known risk: Apollo-era and Viking-era footage is grainy with sparse or absent narration. Scene
descriptions on that material may be mush. **Verify retrieval on the actual curated clips before
building any UI.** If search is weak, no frontend saves the submission.

---

## Architecture

### Ingest
`coll.upload(url=...)` from NASA API direct links, into the dedicated collection
(`VIDEODB_COLLECTION_ID`), never the default one.

### Understand: one chained multi-analyzer run per video

```
object_detection ──┐
spoken_words ──────┼──> vlm (inputs=["objects","transcript"], schema=..., {{inputs.*}} in prompt)
ocr ───────────────┘
```

The VLM describes each scene *while reading* what was said and what was detected. Cross-modal
fusion at ingestion, not just at query. This is a headline line in the writeup.

`ocr` is load-bearing, not decoration: NASA footage carries burned-in **mission elapsed time**.
Extracting MET gives a second, authoritative time axis anchored in mission time rather than video
offset. Technique borrowed from VideoDB's own NFL case study, where OCR of the scoreboard mapped
game-time to video-time.

Segmentation `{"type": "shot", "threshold": 30}`. Sampling per analyzer: ~1 frame/scene for press
briefings, 3-5 for launch and EVA footage.

### Schema (draft, field names to be confirmed empirically)

```python
"schema": {
  "scene_description": "text",
  "celestial_body": {"type": "enum", "values":
      ["moon","mars","earth","earth_orbit","sun","deep_space","ground","unknown"]},
  "event_type": {"type": "enum", "values":
      ["launch","stage_separation","eva","landing","docking","surface_ops",
       "briefing","instrument_readout","other"]},
  "evidence_shown": {"type": "enum", "values":
      ["surface_imagery","data_visualization","instrument","model_animation","none"]},
  "on_screen_text": "text",
}
```

Enums are the point: they make `aggregate(group_by=...)` produce clean buckets instead of
free-text noise, and they auto-tag each *scene* with its celestial body. Scene-level granularity
that manual per-video tagging cannot reach.

### Index layout

| Index | Source | `use_for` | Purpose |
|---|---|---|---|
| `transcript` | `spoken_words` artifact | semantic, fts | Spoken evidence retrieval |
| `scene_semantic` | `vlm` artifact | semantic | Visual evidence retrieval |
| `scene_facets` | **same** `vlm` artifact | query, aggregate | Body/event filtering, analytics, atlas markers |
| `objects` | `object_detection` artifact | query, aggregate | Object-level filtering |
| `ocr` | `ocr` artifact | semantic, fts | Mission elapsed time, on-screen data |
| `mission_meta` | **custom records**, no analyzer | query, aggregate, sort | mission, year, nasa_id, instrument |

Two indexes from one VLM artifact: one model pass, two retrieval surfaces, zero extra cost.
This is exactly the capability the VideoDB team publicly highlighted mid-event.

`mission_meta` is the strongest single move. It makes mission and year **server-side** filter,
sort, and aggregate fields, so temporal reasoning becomes VideoDB retrieval rather than Python
dict sorting in our app. Converts the headline differentiator from "my code sorted results" into
depth of VideoDB usage.

### Agent loop

Hybrid, because deepsearch and precision retrieval are mutually exclusive in one call:

1. **Decompose** the question into sub-queries (`coll.generate_text`, `response_type="json"`).
2. **Explore** with `search(mode="deepsearch")`, carrying `session_id`. Surface
   `response.clarification` as a real interactive beat in the demo.
3. **Pull precise evidence** with `semantic_search(index_names=[...], score_threshold=...)`,
   including field-level targeting like `index_names=["scene_semantic.scene_description"]`.
4. **Filter and order** with `query(index_name="mission_meta", filter=..., sort=...)`.
5. **Quantify** with `aggregate(group_by="event_type")` for the timeline histogram.
6. **Synthesize** with `coll.generate_text(model_name="pro")`.
7. **Compile** the reel on an editor `Timeline`.

Synthesis runs on VideoDB's own LLM rather than an external provider. Same output quality target,
but it moves reasoning inside the 30% depth axis and removes a second API key from the repo.

### Reasoning trace

`SearchResponse.trace` exists but is **not available in deepsearch mode**. So the visible trace is
built from our own logged calls: each sub-query issued, each candidate with `search_score`, which
index matched, and **which candidates were rejected and why**.

Rejects are the point. They prove the loop is real. Judges are agent-infra practitioners and an
animated step list hiding a single search call reads as dishonest.

### Output artifact

Editor v2 `Timeline`:

- video track: matched moments as `VideoAsset(id, start)` clips, chronological by mission year
- audio track: generated narration under the original audio (`volume` mixing)
- text track: `TextAsset` lower-third burning mission, date, and NASA ID **into the pixels**,
  so provenance survives screen recording and export
- `Transition(in_="fade", out="fade")` between eras

`generate_stream()` returns a playable HLS URL instantly, no render wait.

Narration: `coll.generate_text()` writes the script, `coll.generate_voice()` speaks it.

### Sandbox Compute

Three justified uses, none decorative:

1. **`openai/whisper-large-v3-turbo`** for ASR on noisy 1960s-70s mission comms, if hosted
   `spoken_words` transcribes it badly. Retrieval quality starts at the transcript.
2. **Model A/B**: hosted `pro` VLM vs sandboxed `google/gemma-4-31B-it` over the same clips,
   indexed under distinct names, scored against the gold query set, result printed in the README.
   Almost nobody in a hackathon ships a model comparison.
3. **Voice clone via `k2-fsa/OmniVoice`**: narration voice derived from real archival mission
   audio, so the reel's voice comes from the archive itself.

Ethics constraint on 3: NASA announcers are identifiable real people. Clone from generic mission
audio rather than a recognizable individual, and label the narration as synthetic on screen.

Cost discipline: runtime-billed, `stop()` in a `finally` block, always.

### Evaluation

10-15 gold queries with expected clip IDs. Script scores precision and recall, prints a table in
the README. VideoDB's own accuracy guide recommends exactly this. Cheap to build, and it signals
engineering maturity harder than any UI.

---

## UI

Dark dashboard. Reading order top to bottom:

1. **Query bar**, with the two lead queries as one-click presets.
2. **Reasoning trace**, visible by default, not behind a toggle. Steps light up as the agent
   works: decompose, retrieve, rank, order, synthesize. Rejected candidates shown.
3. **Synthesized answer** with inline citation markers; clicking one seeks the reel to that moment.
4. **The reel** as the visual hero, with burned-in timestamp and source.
5. **Timeline** beneath: missions in chronological order, active node highlighted, click to scrub.
   Makes the temporal reasoning physical.
6. **Provenance panel**: which index matched, `search_score`, hydrated row via `return_fields`.

Frame thumbnails for timeline nodes come from `video.extract_scenes()` → `Frame.url`. This is the
only way to get viewable frame images and is a hard dependency for the UI.

**Atlas / 3D globe: optional skin, off the critical path.** It is presentation, not intelligence,
and it competes with everything above for attention. Backend synthesis and reel generation must
work standalone before it starts. The timeline view already carries the temporal story better.

---

## Build order

Strict dependency order, each step gated on the previous working.

1. **Field-name reconnaissance.** One throwaway `index()` call per artifact type to read the real
   field names out of the synchronous validation error. Resolves the doc mismatches in NOTES.md.
2. **Three-clip vertical slice.** Upload → chained understand → dual-index → search → `compile()`.
   Proves the whole pipeline end to end on real footage before scaling.
3. **Retrieval quality gate.** Run gold queries against the 3 clips. If precision is bad here,
   fix schema and prompts now. Do not proceed on a weak foundation.
4. **Full dataset ingest.** 20-30 curated clips, `callback_url` rather than blocking polls.
5. **`mission_meta` custom index.** Mission and year become server-side fields.
6. **Agent loop**, with real trace logging from step one.
7. **Reel compiler.** Timeline, narration, burned-in provenance.
8. **UI.**
9. **Eval harness + README table.**
10. **Sandbox work**: Whisper if needed, model A/B, voice clone.
11. **Atlas globe**, only if everything above is done.

## Submission checklist

All three required or disqualified before judges see it:

- [ ] Working demo on **real** archived media, no synthetic data, no mocked output
- [ ] Public GitHub repo
- [ ] Description, 200 words max, covering what was built and how VideoDB is used

Additional:

- [ ] `coll.make_public()` so judges can play evidence streams without our key
- [ ] `.env` stays gitignored, key never committed
- [ ] README carries the eval table and the VideoDB surface map

## VideoDB surface map (the 30% axis)

ingest · chained multi-analyzer understanding · structured VLM schema · artifact reuse into
split-capability indexes · custom metadata index · deepsearch sessions with clarification ·
ask with sources · field-level semantic search · query · aggregate · sandbox-routed VLM and ASR ·
voice cloning · timeline compilation with burned-in provenance · public collection

Every item has a reason to exist. None are checkbox usage.
