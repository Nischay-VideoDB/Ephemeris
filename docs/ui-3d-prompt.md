# Prompt: 3D interface for Mission Control

**Status: built.** This was the handoff spec; the interface described here now lives in
`web/`, so read it as the design record rather than as work to do. Two requirements changed
during the build and the text below reflects the change:

- The flat list view was removed outright. Evidence, trace and discards live in overlay
  panels instead, and `H` hides every panel.
- Marker cards are fixed screen size, not distance-scaled: at a two-unit standoff a
  distance-scaled card fills the viewport.

Copy everything below the line into your AI coding tool (v0, Cursor, Claude Code, etc).

---

Build a 3D "archive orrery" interface for an existing Next.js app. The app is a research
agent over NASA's archival video: you ask a question, it returns a cited answer plus an
auto-edited evidence reel stitched from real NASA footage. The current interface is a
flat dashboard. Replace it with a spatial one where the solar system *is* the navigation.

## What already exists (do not rebuild)

- Next.js 15 App Router, React 19, TypeScript, pnpm. Directory `web/`.
- `hls.js` installed. The reel is an HLS `.m3u8` stream.
- `web/lib/types.ts` defines the data contract.
- `web/app/api/ask/route.ts` runs the agent and returns the JSON below.
- Preset answers are static JSON at `/answers/water-mars.json` and
  `/answers/first-images.json`.
- Existing components you may reuse or discard: `Trace.tsx`, `Answer.tsx`,
  `EvidenceList.tsx`, `Reel.tsx`, `Sidebar.tsx`.

Add three.js via `@react-three/fiber` and `@react-three/drei`. No other new runtime deps.

## The data contract

One fetch returns this. Assume it is already correct and complete.

```ts
interface Evidence {
  nasa_id: string;          // "JPL-20250710-MARINRs-0001-Mariner_4_Media_Reel"
  video_id: string;
  start: number;            // seconds into the source clip
  end: number;
  score: number;            // 0..1 retrieval score
  index: string;            // "transcript" | "scene_semantic" | "ocr"
  text: string;             // matched transcript or scene description, may be ""
  title: string;            // human title of the source clip
  era_start: number | null; // year of the events this moment DISCUSSES, e.g. 1965
  era_axis: "scene" | "video" | "published" | null;
  era_basis: string | null;
  mission: string | null;   // "Mariner 4", "Viking", "Perseverance", "unknown"
  published_year: number | null;
  celestial_body: "mars" | "moon" | "earth" | "earth_orbit" | "sun"
                | "deep_space" | "ground" | "unknown";
}

interface ReelShot {
  at: number;               // start second WITHIN the compiled reel
  duration: number;
  nasa_id: string;
  era_start: number | null;
  era_axis: string | null;
  mission: string | null;
  caption: string;          // already includes era, mission, nasa_id
}

interface AskResult {
  question: string;
  answer: {
    answer: string;         // prose with inline [1] [2] citation markers
    citations: number[];
    chronology: { era: number | string; claim: string; citations: number[] }[];
    caveats: string;
  };
  evidence: Evidence[];     // 1-indexed by position: evidence[0] is citation [1]
  reel?: { stream_url: string | null; shots: ReelShot[]; total_seconds?: number };
  timeline: { decade: number; scenes: number }[];  // archive-wide histogram
  trace: { n: number; kind: string; summary: string; at: number; [k: string]: any }[];
  rejected: {
    counts: { below_threshold: number; diversity: number };
    diversity: { nasa_id: string; start: number; score: number }[];
    below_threshold: { index?: string; score?: number; threshold?: number }[];
  };
}
```

`reel.shots[i]` corresponds to `evidence[i]`. Index alignment is guaranteed.

## Read this before designing the layout

`celestial_body` is a **subject** tag, not a camera location. It answers "what body does
this scene concern", so in an archive about Mars almost everything is `mars`. Measured on
real answers: a typical result set is 13 `mars` and 1 `moon`, even for a question
explicitly about Earth-based preparation. Across the whole 386-scene corpus it is
`mars` 210, `earth` 94, `moon` 21, `earth_orbit` 18, `deep_space` 17, `unknown` 17,
`sun` 5, `ground` 4, but retrieval concentrates hard on `mars`.

So **do not build planet-hopping as the primary camera motion.** It would sit still.

Use `event_type` for spatial variety instead. It implicitly encodes setting, and it does
vary within a single answer:

| `event_type` | stage to place it in |
|---|---|
| `surface_ops`, `landing` | Martian surface, low camera, terrain horizon |
| `launch` | Earth launch pad, ground level looking up |
| `briefing` | Earth, an interior "mission control" volume |
| `instrument_readout` | an instrument/data volume near the relevant body |
| `data_visualization`, `animation` | an abstract chart space off the ecliptic |
| `eva` | orbital space near the body |
| `other` | nearest neutral stage |

The scene is therefore a set of **stages**, positioned around a stylised solar system,
not a literal orrery. Bodies still render (`sun`, `earth`, `earth_orbit`, `moon`, `mars`,
`deep_space`) as anchors and destinations, non-to-scale so all stay visible and
clickable. Never real orbital mechanics: Mars at true distance is a pixel.

A stage is chosen by combining the two fields: `mars` + `surface_ops` is the Martian
surface, `mars` + `briefing` is a scientist on Earth talking about Mars, and those must
look different. Mars owns the centre of the composition; Earth is a genuine second
subject because much of this archive is Earth-based work *about* Mars.

### One camera mode: era

The camera travels along the era axis as the reel plays, 1958 → 2022, moving between stages
as the era advances. This matches the project's actual claim, which is reasoning across
decades, and it produces continuous motion on every question.

> **Since built:** this section originally specified a second mode, a toggle that framed the
> `celestial_body` of the active shot rather than the moment. It shipped, and the prediction
> two paragraphs above was right: retrieval concentrates so hard on a few worlds that
> consecutive shots usually share one, so the camera sat still through most of a reel. It has
> been removed. Clicking a body still frames that body, which is where the pose was actually
> wanted.

Textures: use NASA public-domain surface maps if you can load them at build time,
otherwise generate procedurally (noise-based rust for Mars, blue/white for Earth). Do
not hotlink from a source that may block cross-origin requests. Ship a procedural
fallback so the scene never renders as untextured black spheres.

## Evidence markers

Every evidence item becomes a marker placed in the stage implied by its
`celestial_body` + `event_type`, distributed within that stage so markers do not overlap.

**Show the source text on hover.** The tags are model-extracted and imperfect: a 1961
Mariner 9 scene in the corpus is tagged `celestial_body: moon`, `event_type: eva`, which
is wrong. Surfacing `text` and `title` on hover lets a viewer catch a bad tag instead of
treating the placement as authoritative. Do not present tags as ground truth.

- Marker size scales with `score`.
- Marker colour encodes `era_axis`: green for `scene`, amber for `video`, red for
  `published`. This is a truth signal, not decoration: green means the date was stated
  in the footage, red means it is only the upload date. Keep the encoding consistent
  everywhere in the UI and label it in a legend.
- Cited markers (indices in `answer.citations`) pulse slowly. Uncited ones sit dim.
- Hovering shows a compact card: era, mission, source clip, matched text.
- Clicking seeks the reel to that shot and selects the marker.

## Camera behaviour, the core requirement

The camera follows the reel, automatically.

1. When the reel is playing, watch `video.currentTime`. Determine the active shot from
   `reel.shots` (the last shot whose `at <= currentTime`).
2. When the active shot changes, tween the camera to frame that shot's **stage** (in era
   mode), and highlight the matching marker.
3. Tween over 900-1200ms with an ease-in-out curve. Never cut. The movement is the
   narrative: watching the camera travel Earth → Mars → Earth as the reel walks through
   the decades is the point of the whole interface.
4. If consecutive shots share a body, do not re-fly. Nudge slightly toward the new
   marker instead, so repeated Mars shots do not cause a jarring loop.
5. Clicking a marker or a timeline node flies the camera there and seeks the reel.
6. Manual orbit/zoom is allowed and must temporarily suspend auto-follow. Show a small
   "resume follow" affordance. Auto-follow resumes on the next user-initiated seek.
7. Respect `prefers-reduced-motion`: replace tweens with instant cuts and stop marker
   pulsing.

## The timeline

A horizontal era scrubber across the bottom, spanning the minimum to maximum
`era_start` present in `evidence`. Note this axis is the year each moment **discusses**,
not when the video was published, and the two differ by decades. Label it explicitly:
"era discussed", not "date".

- One node per evidence item at its `era_start`, coloured by `era_axis`.
- Behind the nodes, render `timeline` (the archive-wide decade histogram) as faint bars,
  so the user sees how much of the whole archive sits in each decade versus how much
  this answer drew from.
- A playhead tracks the active shot.
- Clicking a node seeks the reel and flies the camera.
- Items with `era_start === null` go in a separate "undated" bin at the far right. Do not
  silently drop them.

## Overlay panels

Panels float over the 3D scene, glassy and dismissible, never blocking Mars.

- **Query bar**, top: text input, two preset buttons, loading state. Posts to `/api/ask`
  for custom questions (takes about 60 seconds, show real progress from `trace` if you
  stream it, otherwise an honest indeterminate state).
- **Answer**, left: prose with inline `[n]` markers rendered as buttons. Clicking one
  flies the camera to that evidence marker and seeks the reel. Render `chronology` as a
  compact era list. Render `caveats` in a visibly distinct block, not hidden.
- **Reel player**, bottom right, compact: the HLS video plus the shot list. This is the
  playback source of truth that drives the camera. Do not duplicate playback state.
- **Trace**, collapsible: the agent's steps. Keep it available, not shouting.
- **Discarded**, collapsible: `rejected` counts and rows. Do not remove this. Showing
  what the agent rejected and why is a deliberate honesty feature.

## Constraints

- Server-render nothing three.js. Dynamic-import the canvas with `ssr: false`.
- Target 60fps on integrated graphics. Instanced meshes for markers, one shared geometry.
  No per-frame allocation. No postprocessing beyond a cheap bloom on the Sun.
- Bundle: lazy-load the 3D canvas so first paint does not wait on three.js.
- Mobile: single-finger orbit, pinch zoom, panels become bottom sheets. The scene must be
  usable at 380px wide.
- Accessibility: every marker and timeline node reachable by keyboard with a visible
  focus ring. The reel, answer, evidence, trace and discards all stay reachable as text
  in the overlay panels, so nothing is available only through the 3D scene.
- Colour is never the only signal. Pair the `era_axis` colours with shape or a text tag.

## Do not

- Do not invent evidence, captions, dates, or missions. Every visible fact comes from the
  JSON. If a field is `null` or `"unknown"`, display that honestly.
- Do not use real orbital scale or real ephemerides.
- Do not add a second video player or re-implement HLS.
- Do not remove the discarded-evidence or caveats sections to make the design cleaner.
- Do not smooth over `era_axis`. A red marker must be visibly less trustworthy than green.

## If you need a field that is not in the contract

Do not derive it in the browser from `nasa_id` or from the matched text. Ask for it to be
added to the pipeline instead.

`celestial_body` and `event_type` were added to the backend specifically for this
interface. Guessing "this looks like a Mars clip" from a filename would have been wrong
often: the corpus contains Earth-based drill tests in a Mars yard, Arctic analogue
fieldwork, and launch coverage, all of which are *about* Mars while being *set* on Earth.
The VLM already made that distinction per scene; the browser has no way to.

## Acceptance criteria

1. Loading a preset renders the scene with all evidence markers on the correct bodies.
2. Pressing play walks the camera through the eras without a single hard cut, and the
   highlighted marker, timeline playhead and burned-in reel caption always agree.
3. Clicking a citation in the answer flies the camera and seeks the reel to that moment.
4. Manual orbit suspends auto-follow; the resume affordance restores it.
5. `prefers-reduced-motion` removes all tweening and pulsing.
6. Every fact in the scene is also readable as text in a panel.
7. No console errors, no dropped frames while a tween is in flight on integrated GPU.
