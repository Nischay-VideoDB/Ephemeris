export type EraAxis = "scene" | "video" | "published" | null;

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

export interface Reel {
  stream_url: string | null;
  player_url?: string | null;
  total_seconds?: number;
  error?: string;
  shots: {
    at: number;
    duration: number;
    nasa_id: string;
    era_start: number | null;
    era_axis: EraAxis;
    mission: string | null;
    source_start: number;
    caption: string;
  }[];
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

export interface AskResult {
  question: string;
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
