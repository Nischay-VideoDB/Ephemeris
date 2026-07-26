# VideoDB Findings

Working notes for Mission Control. Everything here was verified against the installed SDK
(`videodb==0.5.1`, Python 3.12 in `.venv`) or read from the bundled skill docs at
`.agents/skills/videodb/` plus `docs.videodb.io`.

Treat the reference docs as a strong prior, not ground truth. Confirmed mismatches are listed below.

---

## Environment

| Item | Value |
|---|---|
| SDK | `videodb==0.5.1` (needs >=0.5.0 for v2, >=0.5.1 for sandbox) |
| Python | 3.12 in `.venv` (3.14 wheel support unproven) |
| Capture extra | skipped, desktop capture is macOS only |
| Collection | `c-9e6ed4ba-1016-46d3-ab43-1ef08f8741b1` "Mission Control - NASA Archive" |
| Default collection | `c-23947926-f744-4b90-b6de-e29c1b848727` "Trace", 8 unrelated videos |

Always target the collection explicitly. `conn.get_collection()` with no argument returns the
default one, and `search`/`ask`/`aggregate` fan out across every indexed video in scope, which
would mix the unrelated videos into results.

```python
coll = conn.get_collection(os.environ["VIDEODB_COLLECTION_ID"])
```

---

## Docs vs reality: confirmed mismatches

| Claim in docs | Reality | Fix |
|---|---|---|
| `from videodb import SandboxModel` | **Confirmed wrong.** `ImportError`, not in 0.5.1. Only `SandboxTier` exists (`small`, `medium`) | Pass model IDs as exact strings |
| `create_collection()` is plan-gated | **Confirmed wrong.** Works on this account | Ignore the warning |
| `object_detection` runs on the hosted path | **Confirmed wrong.** `InvalidRequestError: No active sandbox compatible with model 'rtdetr-v2-r50vd'`. It is sandbox-only, undocumented anywhere | Create a `small` sandbox, or drop the analyzer |
| VLM description field is `outputs.description` | **Confirmed wrong.** Under a declared schema the fields are exactly the schema keys, at top level: `scene_description`, `celestial_body`, ... | Use your own schema key names |
| `ocr` emits `combined_text`, `text`, `words`, `language` | **Confirmed wrong.** Emits only `text` | Index `text` |
| `spoken_words` emits `text`, `chunks`, `words`, `language`, `speaker` | **Partly wrong.** Top level is `text` and `words` only. `speaker` and `confidence` live on each entry inside `words` | Index `text`; read speakers from `words` |
| `aggregate()` returns `{"results": [...]}` | Observed live as a bare `list` with no `results` key | `rows = agg.get("results", []) if isinstance(agg, dict) else agg` |
| One Editor API | Two, see below | Use `videodb.editor` only |
| `generate_text()` returns `dict` with `output` key | Hosted path does. Sandbox example prints the response directly | Normalize in one helper |

Observed field names live, via `scripts/recon.py` (full output in `docs/field-schema.md`):

| analyzer | `analyzer.type` reported | top-level fields in scene `data` |
|---|---|---|
| `spoken_words` | `speech_transcription` | `text`, `words` |
| `ocr` | `ocr` | `text` |
| `vlm` (with schema) | `vlm` | exactly the declared schema keys |

`index()` validates fields **synchronously** and the error enumerates the real field names.
One deliberate bad call is faster than reading docs:

```
fields.filter names not present in any scene's data (dotted paths are resolved, e.g.
score.weight): ['__does_not_exist__']. Available top-level fields: [...]
```

### Optional schema fields silently vanish

A VLM schema field declared `"required": False` that the model chooses not to emit is **absent
from scene data entirely**, not null. Absent fields cannot be indexed or filtered, so an optional
field is unusable for `query()` and `aggregate()`.

Declare every field required and give it an explicit sentinel instead (`"unknown"`, `0`), and say
so in the prompt. A declared "unknown" is indexable; a missing field is not.

---

## Two Editor APIs

Both live, both documented, never distinguished.

| | v1 | v2 (use this) |
|---|---|---|
| Import | `videodb.timeline`, `videodb.asset` | `videodb.editor` |
| Model | `add_inline()` / `add_overlay(start, asset)` | `Timeline` / `Track` / `Clip` |
| Asset id kwarg | `asset_id=` | `id=` |
| Text styling | `TextStyle(fontsize, fontcolor, boxcolor)` | `Font`, `Background`, `Alignment` objects |

`editor.md` uses v2. `generative.md` uses v1. `api-reference.md` documents both silently.

Only v1-exclusive feature: `AudioAsset(disable_other_tracks=True)` hard-mutes source audio.
v2 equivalent is `volume=0.0` on the video clip.

### v2 editor gotchas

- `track.add_clip(start, clip)` start is **whole seconds**. Sub-second precision is lost.
- `Clip(duration=X)` must not exceed the asset's `.length` or it errors.
- `.length` can come back as a **string**. Cast with `float()`.
- Floor durations with `math.floor(l * 100) / 100`, never `round()`, which can round up past the real length.
- Validate `start >= 0` before building a `VideoAsset`. Negative silently produces a broken stream.
- Tracks added later render on top. Audio tracks mix.
- `generate_stream()` returns HLS instantly, no render wait. `timeline.player_url` is shareable.
- No speed control, no region crop/zoom, no keyframe animation, no video-on-video PiP.

---

## v2 pipeline: understand → index → retrieve

v1 (`index_spoken_words`, `index_scenes`, `legacy_search`) still works and is not deprecated,
but only gives semantic search. v2 gives five retrieval modes. Use v2.

One place v1 is still required: `add_subtitle()` and `CaptionAsset(src="auto")` read the **v1**
spoken-word index. A v2 `spoken_words` artifact does not substitute. `ask()` reads **v2 only**.
If you want both burned-in captions and grounded answers, run both.

### Analyzers

| type | artifact | fields emitted |
|---|---|---|
| `spoken_words` | `transcript` | `text`, `chunks`, `words`, `language`, `speaker` |
| `vlm` | `scene` | `scene_description`, `action`, `activity`, `location`, `setting`, `shot_type`, `outputs`, `full_text`, ... |
| `object_detection` | `objects` | `summary`, `frames`, `detections`, `objects` |
| `ocr` | `ocr` | `combined_text`, `text`, `words`, `language` |
| `brand_detection` | `brands` | `brand_names`, `brands`, `summary`, `detections` |
| `activity_recognition` | `activity` | `labels`, `activity`, `actions`, `detections` |
| `location_detection` | `location` | `location_type`, `setting`, `time_of_day`, `location` |
| `faces` | `faces` | `identities`, `detections`, `faces` |
| `audio_event_detection` | `audio_events` | `events`, `labels`, `audio_events` |

Plain strings, no SDK enum. Do not write `from videodb import AnalyzerType`.

### Naming rule

Name every analyzer, or name none. Mixing breaks things: an unnamed analyzer gets a generated
name like `vlm-3f2a91bc`, so `video.index(source=a, name=a.name)` creates an index called
`vlm-3f2a91bc` and `index_names=["scene"]` stops matching. Unnamed also makes
`understanding.get_analyzer("scene")` raise `ValueError`.

### Polling

A run reports `done` only when **every** analyzer succeeded. One failure or skip makes it
`partial`, which the SDK does **not** treat as terminal, so `wait_until_complete()` polls to
`TimeoutError`. Poll analyzers instead, and guard the empty list because `all([])` is `True`:

```python
deadline = time.time() + 3600
while time.time() < deadline:
    analyzers = understanding.refresh().list_analyzers()
    if analyzers and all(a.is_complete for a in analyzers):
        break
    time.sleep(15)
```

`list_analyzers()` reads a local cache, no network call. Call `refresh()` first.
Gate on `analyzer.is_successful` before indexing each artifact.
Never match on `analyzer.type`: a `spoken_words` analyzer reports `.type == "speech_transcription"`.

### Structured schema

The unlock. Enums make `query()` and `aggregate()` produce clean buckets instead of free-text noise.

```python
"schema": {
    "scene_description": "text",
    "activity": {"type": "enum", "values": ["conversation", "walking", "other"]},
    "setting": {"type": "object", "fields": {
        "location_type": {"type": "enum", "values": ["office", "outdoor"]}}},
}
```

Nested paths are addressed with dots downstream: `setting.location_type`, in `fields`,
in `filter`, and in `index_names`.

Extra config keys: `schema_mode` (`auto` | `native_required` | `prompt_only`), `schema_max_retries`.

### Chaining

An analyzer reads earlier artifacts via `inputs`, interpolated with `{{inputs.<name>}}`.
Order in the list does not matter, `inputs` declares the dependency.

```python
{"type": "vlm", "name": "scene", "inputs": ["objects", "transcript"],
 "config": {"prompt": "Describe using frames as primary evidence.\n"
                      "Spoken:\n{{inputs.transcript}}\nObjects:\n{{inputs.objects}}"}}
```

### Indexing one artifact into several indexes

Explicitly supported and is what the VideoDB team highlighted. One VLM pass, two retrieval
surfaces, no extra model cost.

```python
video.index(source=scene, name="scene_semantic", use_for=["semantic"],
            fields={"semantic": ["scene_description"]})
video.index(source=scene, name="scene_facets", use_for=["query", "aggregate"],
            fields={"filter": [...], "aggregate": [...]})
```

`use_for` defaults to all three and **degrades gracefully** when omitted: an artifact with no
embeddable top-level text quietly drops `semantic`. Requesting `semantic` explicitly on the same
artifact raises instead. Omitting is forgiving, requesting is strict. Check `index.use_for` after.

### Custom records, no understanding run needed

```python
video.index(name="mission_meta", source=[
    {"start": 0.0, "end": 240.0, "mission": "Viking 1", "year": 1976, "nasa_id": "..."},
])
```

Requires `start` and `end`. `scene_id` and `metadata` optional, any other key is indexable.
This makes mission and year server-side filter/sort/aggregate fields.

### Index names are a schema contract, collection-wide

Reuse the same name across videos and retrieval fans out over all of them. Indexes sharing a
name must have **identical field structures** or creation fails.

The contract is scoped to the **whole collection**, not to one video. Confirmed live: adding a
single field to custom records made every create fail, because other videos still carried older
indexes under that name.

```
InvalidRequestError: index name 'mission_meta' already exists in this collection with a
different scene structure: existing [...,'title'], incoming [...,'title','water_relevance'].
Use a different name or match the existing structure.
```

Deleting the index on the video being rebuilt is **not enough**. The failure mode is nasty
because it is order-dependent: the last videos processed succeed, since by then every stale copy
has been dropped, so a run half-works and looks like a flake. Either drop the name across every
video in the collection before rebuilding, or version the name while iterating
(`f"scene_{ts}"`). `scripts/build.py` catches `different scene structure` and self-heals.

### Field groups

`semantic` (vector), `filter` (query conditions), `aggregate` (grouping), `sort` (ordering).
Server also recognizes `fts`, `hydrate`, `return`, which the `FieldGroup` enum does not name.
`fts` is applied automatically to `text` and `combined_text`.

Defaults derive from data shape: booleans → filter+aggregate; numbers → filter+aggregate+sort;
strings → filter+aggregate, plus semantic when prose-like; nested objects and lists of objects
get **no** group and are readable only via `return_fields`.
An explicit empty list opts out rather than triggering derivation.

### Status

`Understanding.is_successful` means `done`. `Index.is_successful` means `ready`.
`building` means rows may be landing; `query()` and `aggregate()` work once rows land,
only semantic needs `ready`.

`Index` is not a top-level export: `from videodb.index import Index, IndexRecord, RecordPage, FieldSchema`.

---

## Retrieval

| Goal | Method | Returns |
|---|---|---|
| Find moments, let VideoDB plan | `search(query)` | `SearchResponse` |
| Multi-step investigation | `search(query, mode="deepsearch")` | `SearchResponse` + `session_id` |
| Written answer with evidence | `ask(q, include_sources=True)` | `AskResponse` |
| Vector search on named index | `semantic_search(q, index_names=[...])` | `SearchResult` |
| Exact structured filtering | `query(index_name=..., filter=[...])` | `SearchResult` |
| Counts, groups, facets | `aggregate(index_name=..., group_by=...)` | `dict` or `list[dict]` |

All exist on both `Video` and `Collection` with identical signatures. Creation is video-scoped,
`Collection` has no `understand()` or `index()`.

### Never search several indexes in one call and rank by raw score

Scores from different indexes are **not calibrated against each other**. Omitting `index_names`
searches every semantic index in scope and sorts the union by score, which lets one index crowd
out another entirely.

Measured live on a 386-scene collection: a transcript hit scoring **0.6899**, whose text nearly
restates the query verbatim, was **absent from a 20-result multi-index search**, because
`scene_semantic` results occupied every slot. Restricting to `index_names=["transcript"]` put the
same shot at rank 1.

Two further symptoms of the same call:

- `shot.text` comes back **empty** on multi-index results, but is correctly populated when a
  single index is named.
- `return_fields` hydration returned empty `shot.metadata["indexes"]` in the same test, so
  `shot.text` from a single-index search is the reliable way to read matched text.

Query each index separately and merge with an explicit policy, per-video caps included.

### Retrieval depth has to scale with corpus size

`top_k` is an absolute cut, so the same query degrades as the corpus grows. Going from 58 to 386
scenes, unchanged queries fell from recall 0.956 to 0.767; restoring depth to 15-20 recovered it.
Precision falls mechanically as `top_k` rises when a case has one correct window, so precision is
only meaningful read alongside the depth it was measured at.

### Field-level semantic targeting

Sharpest tool in the API. Append a dotted path to the index name to search one field's embeddings:

```python
video.semantic_search(query="inside a home", index_names=["scene.setting.location_type"])
```

### Router traps

- `search()` raises `ValueError` on `index_name` / `index_names` / `index_ids`. Use `semantic_search()`.
- `score_threshold` and `filter` route to **v2**, not legacy, despite being v1 patterns.
- Any positional argument routes to `legacy_search()`.
- Mixing legacy and v2 keywords raises before routing is decided.
- v2 returns an empty response when nothing matches. Only `legacy_search()` raises `InvalidRequestError`.
- `compile()` raises `SearchError` on an empty response **and** on an aggregate response.
  Guard on both `len(response)` and `response.response_type`.
- `SearchResponse` has no `.stream_url` / `.player_url` / `.collection_id`. Use `.compile()`.

### Deepsearch limits

Supports only `top_k`, `session_id`, `return_fields`. Not supported: filters, sorting,
score thresholds, index selectors, **and planner traces**.

`response.clarification` is a dict `{question_id, text, mode, options}`, prose is in `["text"]`.

### `.trace`

`SearchResponse.trace` holds planner debugging info, available in default mode only, not deepsearch.
Consequence: the agent's visible reasoning trace must be built from our own logged calls
(sub-queries, scores, rejects), not from a single response object.

### `return_fields`

Hydrates stored index rows onto each result under `shot.metadata["indexes"]`. Does not change
which results match. Accepts `None`, `"all"` / `"*"`, one name, a list, or a dict of index → fields.
This is the data source for the provenance panel, alongside `shot.search_score`.

### Streams from results

```python
stream_url = response.compile()                  # all matches concatenated
shot.generate_stream()                           # one moment
video.generate_stream(timeline=[(10, 30), (60, 90)])   # hand-picked ranges
```

Playable in a browser via `https://console.videodb.io/player?url={stream_url}`.

---

## Generation

All on `Collection`.

| Call | Notes |
|---|---|
| `generate_text(prompt, model_name, response_type)` | `basic`/`pro`/`ultra`. `response_type="json"` gives a parsed dict. No access to video, put context in the prompt |
| `generate_voice(text, voice_name)` | TTS |
| `generate_music(prompt, duration)` | May return **shorter** than requested. Check `.length` |
| `generate_sound_effect(prompt, duration)` | |
| `generate_image(prompt, aspect_ratio)` | `.url` may be `None`, use `generate_url()` |
| `generate_video(prompt, duration)` | Plan-gated, may fail |
| `dub_video(video_id, language_code)` | |
| `create_voice_clone(ref_audio_id, name, ref_text, language)` | Sandbox + OmniVoice |

---

## Sandbox Compute

Create → wait until active → pass `sandbox_id` to a supported job. Omit it and you get the hosted model.

| Field | Understanding analyzers | Generation APIs |
|---|---|---|
| model | `config.model` | `model_name` |
| sandbox | `config.sandbox_id` | `sandbox_id` |

### Catalog

| Model | Category | Min tier |
|---|---|---|
| `google/gemma-4-E2B-it` | text | small |
| `Qwen/Qwen3-4B` | text | small |
| `Qwen/Qwen3.5-9B` | text + vision | small |
| `openai/whisper-large-v3-turbo` | speech-to-text | small |
| `k2-fsa/OmniVoice` | text-to-speech | small |
| `stabilityai/stable-audio-open-1.0` | audio gen | small |
| `rtdetr-v2-r50vd` | object detection | small |
| `google/gemma-4-26B-A4B-it` | text + vision | medium |
| `Qwen/Qwen3.5-27B` | text + vision | medium |
| `black-forest-labs/FLUX.1-dev` | image gen | medium |
| `google/gemma-4-31B-it` | text + vision | medium |

No `-FP8` or any other suffix. Categories accepted instead of exact IDs:
`vlm`, `object_detection`, `speech_to_text`, `text_to_speech`, `image_generation`,
`audio_generation`, `text_generation`.

### Cost and lifecycle

| Tier | Price | Concurrent | Max runtime |
|---|---|---|---|
| small | $1/hr | 5 | 24h |
| medium | $3.50/hr | 3 | 24h |

Billed on runtime, recorded at stop, from `started_at` to `stopped_at`.
`provisioning`, `active`, **and** `alert` all count toward the concurrent limit.
Always `stop()` + `wait_for_stop()` in a `finally` block, including after failures.
`alert` means usable but some requested model may be unavailable, test each workload.
A timed-out `create_sandbox` retry mints a **new** sandbox, recover via `list_sandboxes()` first.

`generate_music()` and `generate_sound_effect()` take no `sandbox_id`. Use hosted.

---

## RTStream (live)

Needs an **RTSP or RTMP** URL. NASA TV is HLS/YouTube, so live ingest would require restreaming
through our own RTMP server, which is infra outside VideoDB. Deprioritized.

v2 rtstream supports **exactly one `vlm` analyzer** with time segmentation, no chaining,
no spoken words. Audio and live transcription remain v1 (`index_audio`, `start_transcript`).
Time window is a string with a unit `{"type": "time", "window": "10s"}`, unlike the video
pipeline's integer `seconds`. `rtstream.list_understanding()` is singular.

---

## Cost and latency

Cost scales with scenes × frames per scene.

| Lever | Cheaper | More thorough |
|---|---|---|
| Segmentation | 30-60s scenes | 5s scenes |
| Sampling | 1 frame/scene | 5-8 frames/scene |
| Model tier | `mini` / `basic` | `pro` / `ultra` |
| Transform | `{"resolution": "480p"}` | native |

Indexing is slow: docs cite a 102-second clip with 5s segmentation and three analyzers running
**past 30 minutes**. `wait_until_complete()` defaults to a 1800s timeout, which a modest video
can exceed. Prefer `callback_url` for anything long.

Prompt specificity matters more than frame count. A prompt naming the dimensions you intend to
search on beats "describe this scene" at the same cost.

Per the accuracy guide: static talking-head content wants ~1 frame per scene, action wants 3-5.
Sampling is per-analyzer, so this is a config decision, not extra work.

`conn.check_usage()` returns account usage stats. Use it to track credit burn between runs.

---

## Lessons from VideoDB's own NFL case study

Closest published analog to this project. Reported 80% fewer hallucinations, 70% cost reduction.

1. **Uniform time chunks failed.** Plays spanned 5-10s boundaries and lost context.
2. **OCR of the on-screen clock at 1 fps** mapped game-time to video-time, giving a second
   authoritative time axis. NASA footage has burned-in mission elapsed time, same trick applies.
3. **External domain data drove non-uniform custom segments**, indexed as custom scene records.
   Our equivalent is NASA mission metadata driving segment boundaries.
4. VLMs reason per-frame and struggle without event-level context.

---

## Misc API worth remembering

| Call | Why |
|---|---|
| `video.extract_scenes()` → `SceneCollection` → `Frame.url` | **Only** way to get viewable frame images. v1, no v2 equivalent. Required for UI thumbnails |
| `coll.make_public()` | Judges can play evidence without our key |
| `video.clip(prompt, content_type, model_name)` | Prompt-to-clip, returns a stream URL |
| `conn.youtube_search(query, ...)` | Plus REST-only `search_web` and `search_title` |
| `video.translate_transcript(language, additional_notes)` | `additional_notes` steers tone |
| `video.reframe(start, end, target, mode)` | Slow. Always bound with `start`/`end` or use `callback_url` |
| `conn.transcode(...)` | Server-side, returns a job id, needs `callback_url` |
| `index.field_schema[f].operators` | Authoritative operator list per field. Read it, do not guess |
| `index.records(limit, cursor)` | Paginate raw index rows |

Do **not** use ffmpeg, moviepy, or local encoding. VideoDB handles trimming, concat, audio
overlay, subtitles, overlays, transcode, resolution, aspect ratio, transcription, volume, fades,
and generation server-side.

Director framework and MCP server exist. Not using them: our own agent loop scores higher on
originality and technical execution.

---

## Per-tier hackathon budgets are separate from the credit balance

Found mid-expansion, at 24 of 87 clips. `understand()` started failing:

```
InvalidRequestError: You have reached the Hackathon budget for this model tier (Llm Pro).
This tier has a $20 budget and needs at least $1 remaining to start.
Used: $24.8265875; remaining: $0.
```

At that moment `check_usage()` reported **973 of 1000 credits remaining**. The credit balance
and the per-tier model budget are different meters, and the credit balance is not the one that
stops the work. Anything that quotes remaining capacity from `credit_balance` alone is wrong.

What is actually billed to the exhausted tier, established by running each analyzer alone
against the same clip:

| Analyzer | Result |
|---|---|
| `spoken_words` | accepted |
| `ocr` | **rejected**, bills to Llm Pro |
| `vlm`, `config.model` = `mini` / `basic` / `ultra` | accepted |
| `vlm`, self-hosted model + `sandbox_id` | accepted |

So the blocker was **OCR**, not the VLM, and not the schema. A first attempt to switch tiers
looked like it failed for every tier only because the test still included the OCR analyzer in
the graph. Isolate one analyzer at a time before concluding which one a budget error refers to.

Consequences for the corpus, recorded per clip in the manifest as `vlm_model` and `has_ocr`:

- 19 clips: `pro` VLM with a chained `ocr` input and a separate `ocr` index
- the rest: `basic` VLM, no OCR analyzer, on-screen text captured only into the schema's
  `on_screen_text` field by the VLM reading frames

## Sandbox Compute is not a drop-in for a structured VLM

`Qwen/Qwen3.5-9B` on a `small` sandbox accepted the run and returned `{"text": "..."}` prose,
ignoring `config.schema` entirely, and its descriptions were wrong in a way that matters:
a lunar flyover was described as "a diamond-cut gold bezel" and "a gold-plated speaker cone".
`google/gemma-4-31B-it` on `medium` failed differently, with the request routed to a Google
endpoint: `400 INVALID_ARGUMENT ... unexpected model name format`.

Structured extraction against a declared schema worked on the managed tiers only. Sandboxes
still cost runtime while provisioning, so both were stopped immediately after the test.

## The VLM prompt was quietly Mars-shaped

With a Mars-only corpus, `celestial_body` looked accurate. On the first non-Mars clip the
`basic` tier labelled a grey, cratered, airless lunar flyover as `mars`. Adding one sentence to
the prompt describing what each body looks like fixed it: 4/4 scenes `moon`, and 13/14 `earth`
on a Black Marble clip. The enum itself was also Mars-shaped: a Titan landing had no correct
value and split across `moon`, `deep_space` and `unknown` within one clip, so `venus`,
`mercury`, `jupiter`, `saturn`, `titan` and `comet_asteroid` were added before the bulk run.

---

## Index names are collection-wide contracts, and parallel builds weaponise that

Known before, but the multi-domain expansion showed how bad it gets at scale. Changing
the record structure (adding `celestial_body` values) invalidates the index name across
**every** video. `build.py`'s self-healing path drops the name everywhere and rebuilds
only the clip it is currently processing, so with `--workers 6` each conflict wiped work
five other workers had just finished. Net result after an 87-clip build: `mission_meta`
present on all 87, and `transcript` / `scene_semantic` / `scene_facets` present on **zero**.

Cheap to recover, because artifacts survive index deletion, but nothing recovers it
automatically. Hence `scripts/repair_indexes.py`: diff wanted names against present ones
per clip and rebuild from the stored artifacts. Run it after any schema change.

Two failure modes it has to distinguish, neither of them a bug:

| Symptom | Cause | Right outcome |
|---|---|---|
| `use_for includes semantic but no scene has embeddable text` | clip is silent, ASR produced empty rows | no `transcript` index; clip stays retrievable visually |
| `different scene structure: existing ['text','words'], incoming ['text']` | same cause, seen from the contract's side: silent clips have no word-level field | same |
| `different scene structure` on `scene_semantic` / `scene_facets` | one or two frames tripped the provider's content-safety filter and returned `{"error": {...}}` in place of the schema fields | rebuild that clip from cleaned custom records, dropping only the error rows |

That last one is worth remembering: **a single failed scene changes an artifact's field
set and makes the whole clip unindexable** under a name other clips already established.
Indexing from records instead of the artifact is the escape hatch.

## Retrieval depth must scale with corpus size, measured three times

| Corpus | Depth needed | Evidence |
|---|---|---|
| 58 scenes | 5 | initial gate passed |
| 386 scenes | 15 | recall fell to 0.767 at depth 5 |
| 1,484 scenes | 30 | `martian-terrain-mesa` sat at rank 26, invisible at 15 |

At depth 30 the 87-clip corpus scores **36/36, recall 0.941**, better than the 19-clip
corpus managed at its own best. Growth does not degrade retrieval if depth tracks it.

## Aggregate and query response shapes

Both cost debugging time, both are undocumented:

- `aggregate(group_by="celestial_body")` returns a bare list of
  `{"celestial_body": "saturn", "value": 9.0}`. The **count** is under `value`; the group
  key is under the field name. Reading `row["value"]` as the key silently yields zeros.
- `query()` on a custom-record index puts the fields on `shot.metadata`, not `shot.data`,
  and `shot.text` is `None`. Record indexes carry structure, not prose.
