# Mission Control

A research agent over NASA's archival video: ask a question in plain English, get a
cited answer plus an auto-edited evidence reel stitched from the exact moments that
support it, every clip timestamped and sourced.

Built on VideoDB for the VideoDB "Unlock the Footage" hackathon. All footage is real
NASA public-domain video pulled live from the
[NASA Image and Video Library](https://images-api.nasa.gov). Nothing is synthetic and
no output is mocked.

## Why this is not a search box

A search box takes a query and returns clips. This takes a question, decomposes it,
retrieves across five indexes and two time axes, orders the evidence chronologically,
and returns a synthesised answer that no single clip contains, together with the reel
that proves it.

Corpus: **87 NASA clips, 240 minutes, 1,484 scenes**, spanning **1957-2025** by extracted
era, across Mars, the Moon, human spaceflight, the outer planets, Earth science, the Sun,
astronomy and aeronautics. Retrieval quality gate: **36/36, recall 0.941**, graded against
NASA's own published captions.

The distinction shows up in what the corpus can answer. "Show me Mars footage" is
retrieval. "Trace how our understanding of water on Mars changed over time" requires
reasoning across missions and decades, and it is the query the whole system is built
around.

## How VideoDB is used

| Layer | VideoDB surface |
|---|---|
| Ingest | `coll.upload(url=...)` straight from NASA asset URLs |
| Understanding | `video.understand()` with a chained analyzer graph |
| Cross-modal fusion | `vlm` with `inputs=["transcript","ocr"]` and `{{inputs.*}}` in its prompt |
| Structured extraction | `vlm` `config.schema` with enums, so scenes carry typed fields |
| Artifact reuse | one VLM artifact backing **two** indexes with different `use_for` |
| Custom index | `video.index(source=[records])` for NASA metadata VideoDB never saw |
| Retrieval | `semantic_search`, `query`, `aggregate`, `ask`, `search(mode="deepsearch")` |
| Field-level search | `index_names=["scene_semantic.scene_description"]` |
| Synthesis | `coll.generate_text(response_type="json")` |
| Evidence streams | `generate_stream(timeline=[...])`, `SearchResult.compile()` |

Reasoning runs on VideoDB's own LLM rather than a second provider, so the project
needs exactly one API key.

### The analyzer graph

```
spoken_words ──┐
               ├──> vlm  (inputs, schema, prompt interpolation)
ocr ───────────┘
```

The VLM describes each scene while reading what was said and what was printed during
it, so fusion happens at ingestion rather than as a merge of three separate searches
at query time.

`ocr` is load-bearing rather than decorative. NASA footage carries burned-in speaker
lower-thirds, mission clocks and caption text, and OCR recovers it. On clips where
narration is sparse it is the only textual signal there is.

### The indexes

| Index | Source | `use_for` | Answers |
|---|---|---|---|
| `transcript` | `spoken_words` | semantic + fts | what was said |
| `scene_semantic` | `vlm` | semantic | what is visible |
| `scene_facets` | **same** `vlm` artifact | query, aggregate | what kind of scene it is |
| `ocr` | `ocr` | semantic, query, aggregate | what is printed on screen |
| `mission_meta` | custom records | query, aggregate, sort | who, where, and when |

`scene_semantic` and `scene_facets` come from a single VLM pass. One model call, two
retrieval surfaces, no extra inference cost.

### Two time axes

NASA's video library holds essentially nothing published before 2000, so ordering
evidence by publication date cannot express how understanding changed across earlier
missions. A 2015 explainer may discuss a 1976 result.

Every scene therefore carries a date resolved through three tiers, and records which
tier won:

| `era_axis` | Source | Trust |
|---|---|---|
| `scene` | the scene states a year in speech or on screen | highest |
| `video` | the clip as a whole is anchored to an era (`src/era.py`) | medium |
| `published` | NASA's publication date | always correct, rarely interesting |

`era_basis` records *how* the year was determined (`stated_in_speech`,
`on_screen_text`, `inferred_from_mission`, `video_context`, `not_determinable`). That
is checkable against the transcript and OCR indexes in a way a bare confidence score
is not, and the agent surfaces it so an inferred chronology is never presented as
metadata.

## Asking a question

```bash
python scripts/ask.py --preset water-mars
python scripts/ask.py "How did the instruments used to look for water on Mars change?"
python scripts/ask.py --preset water-mars --json out.json --cap 2 --threshold 0.4
```

Output is the reasoning trace, the cited answer, the evidence in era order, everything
that was **discarded and why**, the archive's decade histogram, and one compiled reel.

### The loop

| Step | What happens |
|---|---|
| decompose | `generate_text` produces sub-questions **and alternate phrasings** |
| retrieve | each index queried separately, once per phrasing |
| join | every moment joined to its `mission_meta` row for date and mission |
| diversify | per-clip cap applied before ordering |
| order | sorted by the era each moment discusses |
| aggregate | decade histogram computed server-side |
| synthesize | cited answer plus a chronology, with caveats |
| compile | one reel, era order, provenance burned into the frame |

Three design choices are forced by measurements in
[docs/quality-gate.md](docs/quality-gate.md), not by preference:

**Query expansion is load bearing.** Asking for "twin rovers landing in 2004 to search
for signs of a watery history" retrieves nothing, because the archive says "the first
of two rovers". The same claim in the archive's wording hits rank 1 at 0.783. So
decomposition must produce alternate phrasings, and it does: on the lead question it
generated *"The first of two rovers examined layered rocks interpreted as formed in
water"* unprompted.

**Indexes are queried one at a time.** Scores across indexes are not comparable, and a
combined call let one index crowd out another so badly that a 0.6899 transcript hit
vanished from 20 results.

**Diversity is enforced, not assumed.** Collection search concentrates on whichever
clip is densest on the topic. On the lead question, 95 retrieved moments collapse to 14
across 9 clips under a per-clip cap of 3; without it the chronology would be built from
one source and would be fiction.

### The trace shows rejects

Anything can render a spinner and call it reasoning. The trace records the sub-questions
issued, the phrasings tried, hits per index, and every moment that was dropped with the
reason: `below_threshold` with its score, or `per_video_cap` with the cap that excluded
it. Rejects are what make the loop checkable.

### The reel

`src/reel.py` uses the **v2 editor** exclusively. Matched moments are laid out on an
integer-second timeline in era order, each with a `TextAsset` lower-third carrying the
year, how that year was determined, the mission, and the NASA identifier.

An inferred date is labelled in the burned-in text, not only in the interface: a scene
dated from clip context reads `1965 (from clip context)`, and one dated only by upload
reads `2015 (published)`. The reel is the artefact people keep, so the qualifier travels
with it.

## Interface

```bash
cd web
pnpm install
node scripts/sync-answers.mjs   # copy pipeline output into public/answers
pnpm dev
```

A 3D scene, not a dashboard. Every retrieved moment is a piece of hardware standing in
the place its scene concerns, and the camera flies from moment to moment as the reel
plays. `H` clears the overlay for a clean recording.

The overlay is set like an archive document rather than a control panel: serif for prose
a person reads, mono for every machine-produced value (ids, scores, timecodes, years),
ruled sheets instead of cards, one accent colour reserved for citations and the active
state. The era axis is a measuring ruler with decade labels and two-year ticks, one
needle per retrieved moment coloured by date provenance, and the whole archive's decade
density behind it.

- **Bodies are textured from mission data**: the Viking/MOLA Mars mosaic with its
  elevation map as relief, Blue Marble Earth with a cloud layer and an inverted specular
  mask so the ocean catches a sun glint, the Clementine Moon. One light at the Sun, so
  every body carries a real terminator. See `web/public/textures/CREDITS.md`.
  Relative sizes are true; distances are not and cannot be.
- **Each `event_type` gets a craft built from primitives**: a six-wheel rover with a
  camera mast for `surface_ops`, a foil bus with two cell-textured arrays and a
  high-gain dish for `instrument_readout`, a dish-and-pad ground station for `briefing`,
  a legged lander, a launch vehicle with a plume, a crewed capsule with a tethered
  astronaut for `eva`, a wireframe panel for `data_visualization`.
- **The camera follows the reel.** Era mode, the default, flies stage to stage as the
  reel advances through the decades. Space mode frames the body each shot concerns and
  is often still, because the archive is mostly Mars. Manual orbit suspends the follow
  and says so.
- Before playback the camera holds a wide shot with Earth and Mars both in frame,
  rather than snapping to shot 1 before the viewer has seen the layout.
- **Beacon colour is the date's provenance**, and hovering repeats it in words: green
  `scene` (stated in the footage), amber `video` (inferred from clip context), red
  `published` (upload date only). Hover also shows the matched text, so a viewer can
  catch a mistagged scene instead of trusting the placement.
- The era scrubber spans the years the moments **discuss**, with the whole archive's
  decade histogram behind it and undated moments binned rather than dropped.
- Inline `[n]` markers, timeline nodes, shot rows and craft all select the same moment:
  the camera flies, the reel seeks, the highlight follows.
- Trace and discards are collapsible panels, still first-class, not a debug view.
- `prefers-reduced-motion` replaces every camera tween with a cut and stops the pulsing.

Presets serve JSON produced by the real pipeline and copied to `public/answers`. A
custom question calls `/api/ask`, which spawns the Python agent with argv-passed
arguments and no shell, and takes about a minute.

## Results

See [docs/quality-gate.md](docs/quality-gate.md) for the current numbers, the failure
analysis, and the cost model.

Ground truth in `evals/gold.json` comes from NASA's own published `.vtt` caption
files, so the eval does not grade the pipeline against its own output.

```bash
python evals/run.py                 # full gate
python evals/run.py --kind visual_only
python evals/run.py --threshold 0.25
```

## Setup

```bash
uv venv .venv --python 3.12
uv pip install --python .venv "videodb>=0.5.1" python-dotenv requests
```

`.env` at the project root:

```
VIDEO_DB_API_KEY=your-key
VIDEODB_COLLECTION_ID=c-...
```

The collection id is required, not optional. `conn.get_collection()` with no argument
returns the account default, and collection-scoped search fans out over every indexed
video in scope, which would mix unrelated footage into every result.

## Pipeline

```bash
python scripts/discover.py          # rank NASA candidates per domain by historical reach
python scripts/select.py            # balance them into a per-domain quota
python scripts/ingest.py --from-selection
python scripts/build.py --workers 6 --vlm-model basic --no-ocr
python scripts/repair_indexes.py --apply   # rebuild anything a schema change dropped
python scripts/dump_era.py          # cache mission_meta rows for the agent join
python scripts/dump_bodies.py       # per-body corpus facts for the interface
python scripts/corpus_report.py     # era coverage, body spread, index health
python evals/run.py                 # quality gate
python scripts/ask.py --preset water-elsewhere
```

`repair_indexes.py` exists because an index name is a schema contract across the whole
collection: change the record structure and every video carrying the old structure has
its index dropped. Rebuilding is free, since understanding artifacts survive index
deletion, but something has to do it.

Every step is idempotent. Understanding ids and index names are recorded in
`data/manifest.json`, so a re-run resumes rather than repeating paid work.

Diagnostics, run once each:

```bash
python scripts/recon.py             # observed field names, docs/field-schema.md
python scripts/probe_segmentation.py
```

## Layout

```
src/
  nasa.py            NASA Image and Video Library client, .vtt parsing
  videodb_client.py  connection and collection helpers
  manifest.py        local record of uploads and artifacts
  schema.py          VLM output contract and prompt
  understanding.py   analyzer graph, segmentation, safe polling
  indexing.py        the five index definitions
  era.py             clip-level era extraction
  mission_meta.py    custom records and the three-tier date resolution
  agent.py           decompose, retrieve, diversify, order, synthesize, trace
  reel.py            v2 editor timeline with burned-in provenance
scripts/             discover, ingest, build, ask, recon, probes, reporting
evals/               gold.json ground truth, run.py scorer
docs/                field-schema.md, quality-gate.md
NOTES.md             verified VideoDB API behaviour and doc mismatches
PLAN.md              product thesis and build order
```

## Notes on VideoDB behaviour

[NOTES.md](NOTES.md) records what was verified against the live API rather than taken
from documentation, including several places where the two disagree. Findings that
cost real debugging time:

- `object_detection` has no hosted model and requires a sandbox
  (`No active sandbox compatible with model 'rtdetr-v2-r50vd'`).
- A VLM schema field declared `"required": False` that the model omits is absent from
  scene data entirely, and absent fields cannot be indexed or filtered at all.
- Shot segmentation is erratic on archival footage: threshold 30 found 2 boundaries in
  a clip where threshold 10 found 13.
- Numeric fields default to `filter`+`sort` but **not** `aggregate`, so a histogram
  over a year field needs the group declared explicitly.
- There are two Editor APIs, `videodb.timeline` and `videodb.editor`, with different
  constructors and different keyword names for the same concept.
