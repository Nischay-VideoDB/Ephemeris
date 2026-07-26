<div align="center">

# Ephemeris

**A research agent over NASA's archival video.**
Ask a question in plain English. Get a cited answer, ordered by when things actually happened,
plus an auto-edited evidence reel cut from the exact seconds that support it.

[![VideoDB](https://img.shields.io/badge/built%20on-VideoDB-5b4ee9?style=flat-square)](https://videodb.io)
[![Python](https://img.shields.io/badge/python-3.12-3776ab?style=flat-square&logo=python&logoColor=white)](https://www.python.org)
[![Next.js](https://img.shields.io/badge/next.js-15-000000?style=flat-square&logo=nextdotjs&logoColor=white)](https://nextjs.org)
[![Three.js](https://img.shields.io/badge/three.js-r3f-049ef4?style=flat-square&logo=threedotjs&logoColor=white)](https://docs.pmnd.rs/react-three-fiber)
[![Licence](https://img.shields.io/badge/licence-MIT-16a34a?style=flat-square)](LICENSE)

</div>

---

## Why this is not a search box

A search box takes a query and returns clips. Ephemeris takes a **question**, decomposes it,
retrieves across five indexes and two time axes, orders the evidence by the era each moment
discusses, and returns an answer no single clip contains, together with the reel that proves it.
"Show me Mars footage" is retrieval; "trace how our understanding of water on Mars changed over
time" is the query the whole system is built around.

Built for VideoDB's "Unlock the Footage" hackathon. All footage is real NASA public-domain video
pulled live from the [NASA Image and Video Library](https://images-api.nasa.gov). Nothing is
synthetic and no output is mocked.

**Corpus:** 87 clips, 240 minutes, 1,484 scenes, 1957 to 2025. Earth 473 scenes, mars 227, deep
space 199, ground 139, earth orbit 114, sun 107, moon 99, then comets, saturn, jupiter, titan.
Venus and mercury are **zero**, and the agent knows it: see [refusing to answer](#refusing-to-answer).

## How VideoDB is used

| Layer | Surface |
|---|---|
| Ingest | `coll.upload(url=...)` straight from NASA asset URLs |
| Understanding | `video.understand()` with a chained analyzer graph |
| Cross-modal fusion | `vlm` with `inputs=["transcript","ocr"]` and `{{inputs.*}}` in its prompt |
| Structured extraction | `vlm` `config.schema` with enums, so scenes carry typed fields |
| Artifact reuse | one VLM artifact backing **two** indexes with different `use_for` |
| Custom index | `video.index(source=[records])` for NASA metadata VideoDB never saw |
| Retrieval | `semantic_search`, `query`, `aggregate` |
| Field-level search | `index_names=["scene_semantic.scene_description"]` |
| Synthesis | `coll.generate_text(response_type="json")` |
| Word timings | `video.get_transcript()` on v1, deliberately |
| Evidence reels | v2 editor `Timeline` / `Track` / `Clip` / `TextAsset`, `generate_stream()` |
| Sharing | `coll.make_public()` so reels play without a key |

Reasoning runs on VideoDB's own LLM, so the project needs exactly one API key.

### The analyzer graph

```
spoken_words ──┐
               ├──> vlm   (inputs · schema · {{inputs.*}})
ocr ───────────┘
```

The VLM describes each scene while reading what was said and printed during it, so fusion happens
at ingestion rather than as a merge of three searches at query time. `ocr` is load-bearing: NASA
footage carries burned-in lower-thirds and mission clocks, and where narration is sparse it is the
only textual signal there is.

### The indexes

| Index | Source | `use_for` | Answers |
|---|---|---|---|
| `transcript` | `spoken_words` | semantic + fts | what was said |
| `scene_semantic` | `vlm` | semantic | what is visible |
| `scene_facets` | **same** `vlm` artifact | query, aggregate | what kind of scene it is |
| `ocr` | `ocr` | semantic, query, aggregate | what is printed on screen |
| `mission_meta` | custom records | query, aggregate, sort | who, where, and when |

One VLM pass, two retrieval surfaces, no extra inference cost.

## Four ways to know a date

NASA's library holds almost nothing published before 2000, so publication date cannot express how
understanding changed across earlier missions: a 2015 explainer routinely discusses a 1976 result.
Every scene carries a date **and a record of how it was known**.

| `era_axis` | Source | Trust |
|---|---|---|
| `scene` | the scene states a year, in speech or on screen | highest |
| `mission` | the year was impossible for the mission, so its operating window decided | corrected |
| `video` | the clip as a whole is anchored to an era | medium |
| `published` | NASA's publication date | always correct, rarely interesting |

A compilation dated once at the top hands that year to every scene beneath it; a Curiosity segment
came back as 1990, twenty-one years before launch. **20.7%** of dated scenes with a known mission
fell outside its window, and **15.7%** of the archive is re-dated. A date the scene stated itself
is never overruled, because archive footage is full of retrospect. Three more provenance axes work
the same way: `body_axis`, `clip_axis` and `mission_axis`.

## Asking a question

```bash
python scripts/ask.py --preset water-mars
python scripts/ask.py "How did the instruments used to look for water on Mars change?"
python scripts/ask.py "..." --json out.json --cap 2 --threshold 0.4 --no-stream
```

Output is the reasoning trace, the cited answer, the evidence in era order, everything discarded
and why, the archive's decade histogram, and one compiled reel.

| Step | What happens |
|---|---|
| decompose | `generate_text` produces sub-questions **and alternate phrasings** |
| gate | is the question answerable at all |
| gate | does the corpus hold the world it names |
| retrieve | each index queried separately, once per phrasing |
| passages | runs of touching cells joined, so the cap chooses between passages |
| era join | every moment joined to its `mission_meta` row, date resolved four ways |
| diversify | two per clip, preferring the world the question named |
| refine | windows snapped to sentence bounds using word-level timings |
| order | sorted by the era each moment discusses |
| aggregate | decade histogram computed server-side |
| synthesize | cited answer plus a chronology, with caveats |
| compile | one reel, era order, provenance burned into the frame |

Choices forced by measurement, not preference:

- **Query expansion is load bearing.** "Twin rovers landing in 2004..." retrieves nothing; the
  archive says "the first of two rovers", and that phrasing hits rank 1 at 0.783.
- **Indexes are queried one at a time.** Scores are not comparable across indexes, and a combined
  call dropped a 0.6899 transcript hit out of 20 results.
- **Diversity is enforced.** Without a per-clip cap the chronology comes from one dense clip.
- **Clips are cut to sentences.** Indexing uses a ten-second grid that cuts speech mid-word; v1
  `get_transcript()` word timings are what land a clip on a boundary.

The trace records every moment dropped with its reason, `below_threshold` with the score or
`per_video_cap` with the cap. Rejects are what make the loop checkable.

### Refusing to answer

Retrieval always returns something, so two gates run first. **Answerability:** given `zxqw
plorbnak fleeming vootrix` the planner once split the gibberish into plausible sub-questions and
answered with confidence; it now reports answerability, and a false ends the run. **Coverage:**
asked how NASA explored Venus, the agent once reasoned from Artemis reentry footage while
conceding no clip showed Venus. There are zero Venus scenes, and the check now ends the run in
**19 seconds** with what the archive does cover.

### The reel

`src/reel.py` uses the **v2 editor** exclusively. Moments are laid out on an integer-second
timeline in era order, each with a `TextAsset` lower-third carrying the citation number, the year,
how that year was determined, the mission and the NASA identifier. Provenance is burned into the
frame, so it survives an export.

## Interface

A navigable solar system. Each retrieved moment stands on the body its scene concerns, rendered as
the hardware the mission actually flew, and the camera moves through the decades as the reel plays.

- **One `activeEvidenceIndex` is the entire sync bus**, shared by inline `[n]` markers, timeline
  needles, shot rows, craft in the scene and the reel's playhead.
- **Beacon colour is the date's provenance**, repeated in words on hover.
- **The era scrubber** spans the years the moments *discuss*, over the archive's decade histogram.
  Undated moments are binned, not dropped.
- **Every question asked is kept**, answered or refused, and reloads from a file read.

## Quality gates

**Retrieval**, `evals/run.py`, against ground truth in `evals/gold.json` built from NASA's own
published `.vtt` captions, so the eval does not grade the pipeline on its own output.

```
35 / 36 cases · mean recall 0.909
```

| kind | n | recall | | kind | n | recall |
|---|---:|---:|---|---|---:|---:|
| spoken_only | 12 | 1.000 | | historical | 8 | 0.812 |
| visual_only | 4 | 1.000 | | cross_modal | 1 | 0.667 |
| filter | 5 | 0.900 | | vocabulary_gap | 1 | 0.500 |

An earlier run recorded 36/36 at 0.941 and does not reproduce: the index is intact and the
expected windows are present, but ANN ranking has drifted. The number above reproduces today.

**Answers**, `evals/answers.py`, grades saved runs without spending an API call. Seven checks,
each from a failure seen in a real run: `cited`, `grounded`, `on_setting`, `snapped`,
`varied_lengths`, `chronology`, and that a refusal explains itself and shows nothing.

```bash
python evals/run.py                        # retrieval gate
python evals/answers.py data/answers       # answer gate
python tests/test_era.py                   # and six more suites
cd web && npm test                         # scene placement, craft mapping
```

## Setup

```bash
uv venv .venv --python 3.12
uv pip install --python .venv "videodb>=0.5.1" python-dotenv requests
cd web && npm install && npm run dev       # http://localhost:3000
```

`.env` at the project root:

```
VIDEO_DB_API_KEY=your-key
VIDEODB_COLLECTION_ID=c-...
```

The collection id is required. `conn.get_collection()` with no argument returns the account
default, and collection-scoped search then fans out over every indexed video in scope.

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
python scripts/refresh_answers.py --saved  # regenerate shipped answers after a pipeline change
```

An index name is a schema contract across the collection: change the record structure and every
video carrying the old one loses its index, which is what `repair_indexes.py` rebuilds. Presets are
generated output, not source, which is what `refresh_answers.py` keeps current. Every step is
idempotent; understanding ids and index names live in `data/manifest.json`, so a re-run resumes
rather than repeating paid work.

## Layout

```
src/     nasa, videodb_client, manifest, schema, understanding, indexing,
         era, mission_meta, speech, agent, reel
web/     Next.js app, react-three-fiber orrery, SSE progress
scripts/ discover, ingest, build, ask, refresh, probes, reporting
evals/   gold.json, run.py retrieval gate, answers.py answer gate
tests/   body, mission, era, coverage, passages, speech, reel
docs/    architecture.svg, field-schema.md, quality-gate.md
```

## Architecture

![Architecture](docs/architecture.svg)

Three bands: build it once, query it per question, show it. Purple is a VideoDB call, green is
this project's own logic, blue is data, grey is a local cache, yellow is the browser, and red is
the path a refused question takes.

## Notes on VideoDB behaviour

Verified against the live API rather than taken from the docs, including where the two
disagree: `object_detection` has no hosted model, VLM schema fields
declared `"required": False` vanish from scene data when omitted, shot segmentation is erratic on
archival footage, numeric fields are not aggregatable by default, there are two Editor APIs, and
`Shot.text` is always `None` (the match lives in `metadata["embedded_text"]`).

## Licence

[MIT](LICENSE). The NASA footage is public domain, from the
[NASA Image and Video Library](https://images.nasa.gov). NASA does not endorse this project.
