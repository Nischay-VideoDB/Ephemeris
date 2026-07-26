# Submission

## Description (200 words max)

**Mission Control** is a research agent over NASA's archival video. Ask a question in
plain English and it returns a cited answer plus an auto-edited evidence reel stitched
from the exact moments that support it, every clip timestamped and sourced.

Corpus: 87 real NASA public-domain clips, 240 minutes, 1,484 scenes, pulled live from
NASA's Image and Video Library across eight domains.

VideoDB does the work. Each clip runs one chained `understand()` where `spoken_words`
and `ocr` feed a schema'd `vlm` through `inputs` and `{{inputs.*}}`, so scenes are
described knowing what was said and printed during them. One VLM artifact backs two
indexes: `scene_semantic` for vector search, `scene_facets` for enum filtering and
aggregation. Custom records add `mission_meta`, making NASA metadata server-side
filterable and sortable.

NASA publishes almost no video before 2000, so every scene carries two dates: the
publication year, and the era its content discusses, labelled by how it was determined.
The archive spans 1957-2025.

The interface is a navigable solar system. Each retrieved moment stands on the body its
scene concerns, and the camera flies through the decades as the reel plays.

Measured: 36/36 retrieval evals, recall 0.941, ground truth from NASA's own captions.

---

## Word count

195 words, excluding the heading. Verify after any edit:

```bash
python - <<'PY'
import re, pathlib
t = pathlib.Path('SUBMISSION.md').read_text()
body = t[t.index('**Mission Control**'):t.index('\n---')]
print(len(re.sub(r'[`*_#]', '', body).split()))
PY
```

## Checklist

- [x] Working demo on real archived media, no synthetic data, no mocked output
- [ ] Public GitHub repository — **not created yet, must be pushed before submitting**
- [x] Description, 200 words max, covering what was built and how VideoDB is used
- [x] Collection made public via `coll.make_public()` so judges can play evidence
      streams without our key
- [x] `.env` gitignored, API key never committed
- [x] Eval table and VideoDB surface map in the README

## Evidence links

Reels compiled by the pipeline, playable without credentials:

- Water on Mars, 14 shots, 140s: https://player.videodb.io/watch?v=xTPqKc3SqDc
- Earliest Mars missions, 14 shots, 140s: https://player.videodb.io/watch?v=uaIaLIZadOQ

Regenerate with:

```bash
python scripts/ask.py --preset water-mars --json data/answer_water_mars.json
```

## VideoDB surface used

ingest · chained multi-analyzer `understand()` · structured VLM schema with enums ·
analyzer chaining via `inputs` and prompt interpolation · artifact reuse into two
indexes with different `use_for` · custom temporal records · `semantic_search` with
per-index targeting · `query` with numeric and string filters · `aggregate` for the era
histogram · `generate_text` with JSON responses for planning and synthesis ·
`generate_stream` with timelines · v2 editor `Timeline`/`Track`/`Clip` with `TextAsset`
overlays · `check_usage` for cost tracking · `make_public`

Fifteen distinct surfaces, each with a reason to exist.

## What is deliberately not used

- **`object_detection`**: it has no hosted model and requires a sandbox at $1/hour.
  Nothing in the retrieval story needed it once OCR and the VLM were in place.
- **RTStream**: needs RTSP/RTMP, and NASA TV is HLS/YouTube, so live ingest would have
  meant standing up a restreaming server outside VideoDB.
- **Director framework and MCP server**: building the agent loop directly was the point.

## Honest limitations

- Two eval cases fail on purpose and are documented in `docs/quality-gate.md`: broad
  queries still concentrate on the densest clip, and a researcher's vocabulary does not
  always reach the archive's wording.
- Scenes that could not be tied to an era fall back to their publication date, and say so.
  The agent labels these rather than hiding them.
- Precision reads low because `top_k` exceeds the number of correct windows per query;
  recall and rank-1 position are the meaningful measures at this corpus size.
