/** How a moment's date was decided. `mission` means the extracted date fell outside the
 *  operating window of the mission the scene is about, so the window decided it instead. */
export type EraAxis = "scene" | "video" | "published" | "mission" | null;

/** Where a moment is set. Drives spatial placement in the orrery view.
 *  `ground` is terrestrial testing (a Mars-yard rig, an Arctic drill site): about Mars,
 *  filmed on Earth, and worth distinguishing from both. */
export type CelestialBody =
  | "mars"
  | "moon"
  | "earth"
  | "earth_orbit"
  | "sun"
  | "venus"
  | "mercury"
  | "jupiter"
  | "saturn"
  | "titan"
  | "comet_asteroid"
  | "deep_space"
  | "ground"
  | "unknown";

export type EventType =
  | "launch"
  | "landing"
  | "surface_ops"
  | "instrument_readout"
  | "briefing"
  | "data_visualization"
  | "animation"
  | "eva"
  | "other";

export interface Evidence {
  nasa_id: string;
  video_id: string;
  start: number;
  end: number;
  score: number;
  index: string;
  query: string;
  text: string;
  era_start: number | null;
  era_axis: EraAxis;
  era_basis: string | null;
  mission: string | null;
  title: string;
  published_year: number | null;
  celestial_body: CelestialBody;
  event_type: EventType;
  /** Where `celestial_body` came from: the scene's own extraction, or the clip as a whole when
   *  the scene said nowhere or contradicted everything around it. Absent on older answers. */
  body_axis?: "scene" | "video";
  /** The words inside the played window once it was snapped to sentence bounds. A superset of
   *  `text`, which is only the part the search matched. Empty when the moment has no speech. */
  spoken?: string;
  /** Whether speech or the ten-second indexing grid decided this clip's bounds. */
  clip_axis?: "sentence" | "scene";
  /** `dropped` when the extracted mission named a world this moment is not set on, so the
   *  label was removed rather than shown over footage of somewhere else. */
  mission_axis?: "scene" | "dropped" | "none";
  /** Durable public master for the original NASA footage. Live runs use this
   *  timestamped fallback when the borrowed VideoDB collection cannot compile
   *  a new reel under the public account. */
  source_url?: string;
  source_title?: string;
}

export interface TraceStep {
  n: number;
  kind: string;
  summary: string;
  at: number;
  sub_questions?: string[];
  phrasings?: string[];
  visual_phrasings?: string[];
  rationale?: string;
  queries_run?: number;
  hits_by_index?: Record<string, number>;
  thresholds?: Record<string, number>;
  rejected_below_threshold?: number;
  kept_per_clip?: Record<string, number>;
  per_video_cap?: number;
  era_axis_counts?: Record<string, number>;
  note?: string;
  histogram?: { decade: number; scenes: number }[];
  caveats?: string;
  chronology_points?: number;
}

export interface Answer {
  answer: string;
  citations: number[];
  chronology: { era: number | string; claim: string; citations: number[] }[];
  caveats: string;
}

export interface Shot {
  at: number;
  duration: number;
  /** Which evidence item this shot is. Absent on answers compiled before the field existed,
   *  where shot order and evidence order are the same thing. Always read it through
   *  `lib/reel.ts` rather than assuming shot i is evidence i. */
  evidence_index?: number;
  /** The source timestamp had to move back to land inside the clip. */
  clamped?: boolean;
  nasa_id: string;
  era_start: number | null;
  era_axis: EraAxis;
  mission: string | null;
  source_start: number;
  caption: string;
}

export interface Reel {
  stream_url: string | null;
  player_url?: string | null;
  total_seconds?: number;
  error?: string;
  /** Evidence that produced no footage, with the reason. */
  dropped?: { evidence_index: number; nasa_id: string; reason: string }[];
  shots: Shot[];
}

export interface Rejected {
  counts: { below_threshold: number; diversity: number };
  below_threshold: {
    reason: string;
    score?: number;
    threshold?: number;
    index?: string;
    video_id?: string;
    start?: number;
    detail?: string;
  }[];
  diversity: {
    reason: string;
    nasa_id: string;
    start: number;
    score: number;
    cap?: number;
  }[];
}

/** One run saved under `data/answers`. Declared here rather than beside the file-reading code
 *  so a client component can name the type without pulling `node:fs` into the browser bundle. */
export interface SavedAnswer {
  id: string;
  question: string;
  saved: string;
  moments: number;
  shots: number;
  answered: boolean;
  /** The run did not complete. Distinct from a run that completed and found nothing to say:
   *  one is a broken pipeline, the other is the archive answering honestly. */
  failed?: boolean;
}

export interface AskResult {
  question: string;
  /** Set by `/api/ask` on a live run: the id the result was saved under. */
  saved_id?: string;
  plan: {
    sub_questions: string[];
    phrasings: string[];
    visual_phrasings: string[];
    needs_chronology: boolean;
    rationale: string;
  };
  answer: Answer;
  evidence: Evidence[];
  rejected: Rejected;
  timeline: { decade: number; scenes: number }[];
  trace: TraceStep[];
  reel?: Reel;
}
