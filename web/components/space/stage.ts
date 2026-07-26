import * as THREE from "three";
import type { CelestialBody, EventType, Evidence } from "@/lib/types";

/** Scene layout. Not to scale and deliberately so: Mars at true distance from Earth is a
 *  pixel. Relative body sizes are kept honest (Earth is 1.9x Mars, the Moon 0.27 of Earth)
 *  because that part costs nothing to get right. */

export const SUN_POSITION = new THREE.Vector3(180, 70, 90);
export const SUN_RADIUS = 30;

export const MARS_CENTER = new THREE.Vector3(0, 0, 0);
export const MARS_RADIUS = 3;
export const EARTH_CENTER = new THREE.Vector3(-34, 2, -6);
export const EARTH_RADIUS = 5.6;
export const MOON_CENTER = EARTH_CENTER.clone().add(new THREE.Vector3(-11.5, 1.5, 6));
export const MOON_RADIUS = 1.5;
export const DEEP_SPACE_CENTER = new THREE.Vector3(44, 18, -78);
export const UNKNOWN_CENTER = new THREE.Vector3(4, -26, 16);

/* Outer solar system. Laid out along one arc heading away from the Sun so the eye reads an
 * order, with sizes ranked correctly (Jupiter largest, Mercury smallest) but compressed:
 * true relative size would make Mercury invisible next to Jupiter. */
export const VENUS_CENTER = new THREE.Vector3(-58, -6, 26);
export const VENUS_RADIUS = 5.3;
export const MERCURY_CENTER = new THREE.Vector3(-74, 4, 48);
export const MERCURY_RADIUS = 2.1;
export const JUPITER_CENTER = new THREE.Vector3(52, 10, -46);
export const JUPITER_RADIUS = 11;
export const SATURN_CENTER = new THREE.Vector3(96, -6, -92);
export const SATURN_RADIUS = 9.2;
export const TITAN_CENTER = SATURN_CENTER.clone().add(new THREE.Vector3(-17, 3, 9));
export const TITAN_RADIUS = 1.9;
export const COMET_CENTER = new THREE.Vector3(22, 26, -34);

export interface Stage {
  /** Point the stage orbits or rests on. */
  anchor: THREE.Vector3;
  /** Radius of the body at that anchor, or a notional radius for void regions. */
  surface: number;
  label: string;
}

/** One stage per `celestial_body`. `earth_orbit` and `ground` share Earth's anchor: they are
 *  the same place seen from different altitudes, which is exactly what the tags mean. */
export const STAGES: Record<CelestialBody, Stage> = {
  mars: { anchor: MARS_CENTER, surface: MARS_RADIUS, label: "Mars" },
  earth: { anchor: EARTH_CENTER, surface: EARTH_RADIUS, label: "Earth" },
  moon: { anchor: MOON_CENTER, surface: MOON_RADIUS, label: "the Moon" },
  earth_orbit: { anchor: EARTH_CENTER, surface: EARTH_RADIUS + 1.8, label: "Earth orbit" },
  ground: { anchor: EARTH_CENTER, surface: EARTH_RADIUS, label: "Earth, ground site" },
  sun: { anchor: SUN_POSITION, surface: SUN_RADIUS, label: "the Sun" },
  venus: { anchor: VENUS_CENTER, surface: VENUS_RADIUS, label: "Venus" },
  mercury: { anchor: MERCURY_CENTER, surface: MERCURY_RADIUS, label: "Mercury" },
  jupiter: { anchor: JUPITER_CENTER, surface: JUPITER_RADIUS, label: "Jupiter" },
  saturn: { anchor: SATURN_CENTER, surface: SATURN_RADIUS, label: "Saturn" },
  titan: { anchor: TITAN_CENTER, surface: TITAN_RADIUS, label: "Titan" },
  comet_asteroid: { anchor: COMET_CENTER, surface: 1.1, label: "small bodies" },
  deep_space: { anchor: DEEP_SPACE_CENTER, surface: 0.8, label: "deep space" },
  unknown: { anchor: UNKNOWN_CENTER, surface: 0.8, label: "unplaced" },
};

/** Direction out from the anchor, plus how far above the surface the moment sits.
 *  A briefing about Mars is not on Mars, so it gets Earth's near side at ground level;
 *  a data visualisation is not anywhere physical, so it floats off the pole. */
interface EventPlacement {
  dir: THREE.Vector3;
  alt: number;
  label: string;
}

const EVENTS: Record<EventType, EventPlacement> = {
  surface_ops: { dir: new THREE.Vector3(0.35, -0.15, 0.92), alt: 0.06, label: "surface operations" },
  landing: { dir: new THREE.Vector3(0.1, -0.45, 0.88), alt: 0.06, label: "landing" },
  launch: { dir: new THREE.Vector3(0.55, 0.55, 0.62), alt: 0.3, label: "launch" },
  briefing: { dir: new THREE.Vector3(-0.75, 0.2, 0.63), alt: 0.05, label: "briefing" },
  instrument_readout: { dir: new THREE.Vector3(0.7, 0.35, 0.62), alt: 1.5, label: "instrument readout" },
  data_visualization: { dir: new THREE.Vector3(0.15, 0.95, 0.28), alt: 2.5, label: "data visualisation" },
  animation: { dir: new THREE.Vector3(-0.3, 0.9, 0.32), alt: 2.5, label: "animation" },
  eva: { dir: new THREE.Vector3(0.2, 0.55, 0.81), alt: 1.0, label: "EVA" },
  other: { dir: new THREE.Vector3(0.9, 0.05, 0.44), alt: 0.85, label: "other" },
};

export type CraftKind =
  | "rover"
  | "lander"
  | "rocket"
  | "station"
  | "orbiter"
  | "holo"
  | "capsule"
  | "probe";

export const CRAFT_BY_EVENT: Record<EventType, CraftKind> = {
  surface_ops: "rover",
  landing: "lander",
  launch: "rocket",
  briefing: "station",
  instrument_readout: "orbiter",
  data_visualization: "holo",
  animation: "holo",
  eva: "capsule",
  other: "probe",
};

export interface Placement {
  index: number;
  ev: Evidence;
  /** World position of the craft. */
  pos: THREE.Vector3;
  /** Outward surface normal, used to stand the craft up. */
  normal: THREE.Vector3;
  craft: CraftKind;
  stage: Stage;
  stageKey: CelestialBody;
  /** "Mars, surface operations" */
  stageLabel: string;
  /** True when the craft rests on a body rather than floating. */
  grounded: boolean;
}

function stageOf(body: CelestialBody | null | undefined): [CelestialBody, Stage] {
  const key = (body && STAGES[body] ? body : "unknown") as CelestialBody;
  return [key, STAGES[key]];
}

/** Lay every evidence item out. Items sharing a stage spread on a small disc facing outward
 *  so nothing overlaps, in a deterministic order so a re-render never reshuffles the scene. */
export function placeEvidence(evidence: Evidence[]): Placement[] {
  const used: Record<string, number> = {};

  return evidence.map((ev, index) => {
    const [stageKey, stage] = stageOf(ev.celestial_body);
    const event = (EVENTS[ev.event_type] ? ev.event_type : "other") as EventType;
    const placement = EVENTS[event];

    // Crowding is counted per physical spot, not per tag. `earth`, `ground` and `earth_orbit`
    // are three tags for Earth, and `earth` and `ground` sit at the same anchor at the same
    // altitude: keyed by name, two moments tagged differently but placed identically both took
    // ring 0 and ended up inside each other, one hiding the other and stealing its clicks.
    const key = `${stage.anchor.x},${stage.anchor.y},${stage.anchor.z}:${stage.surface}:${event}`;
    const k = used[key] ?? 0;
    used[key] = k + 1;

    const normal = placement.dir.clone().normalize();
    const distance = stage.surface + placement.alt * (1 + stage.surface * 0.35);

    // Golden-angle disc so successive markers in one stage never line up.
    const tangent = new THREE.Vector3()
      .crossVectors(normal, new THREE.Vector3(0, 1, 0.001))
      .normalize();
    const bitangent = new THREE.Vector3().crossVectors(normal, tangent).normalize();
    const angle = k * 2.399963;
    // Wide enough that neighbours on a busy stage do not crowd into the camera's standoff
    // distance when it flies in on one of them.
    const ring = k === 0 ? 0 : 0.95 * Math.sqrt(k) * (1 + stage.surface * 0.06);

    const pos = stage.anchor
      .clone()
      .add(normal.clone().multiplyScalar(distance))
      .add(tangent.clone().multiplyScalar(Math.cos(angle) * ring))
      .add(bitangent.clone().multiplyScalar(Math.sin(angle) * ring));

    return {
      index,
      ev,
      pos,
      normal,
      craft: CRAFT_BY_EVENT[event],
      stage,
      stageKey,
      stageLabel: `${stage.label}, ${placement.label}`,
      grounded: placement.alt < 0.5 && stage.surface > 1,
    };
  });
}

/** Bodies the viewer can click. Void regions (deep space, unplaced) are deliberately absent:
 *  there is nothing there to inspect, and a hit sphere around empty space would swallow clicks
 *  meant for the craft floating in it. */
export const PICKABLE: { key: CelestialBody; center: THREE.Vector3; radius: number; label: string }[] = [
  { key: "mars", center: MARS_CENTER, radius: MARS_RADIUS, label: "Mars" },
  { key: "earth", center: EARTH_CENTER, radius: EARTH_RADIUS, label: "Earth" },
  { key: "moon", center: MOON_CENTER, radius: MOON_RADIUS, label: "the Moon" },
  { key: "venus", center: VENUS_CENTER, radius: VENUS_RADIUS, label: "Venus" },
  { key: "mercury", center: MERCURY_CENTER, radius: MERCURY_RADIUS, label: "Mercury" },
  { key: "jupiter", center: JUPITER_CENTER, radius: JUPITER_RADIUS, label: "Jupiter" },
  { key: "saturn", center: SATURN_CENTER, radius: SATURN_RADIUS, label: "Saturn" },
  { key: "titan", center: TITAN_CENTER, radius: TITAN_RADIUS, label: "Titan" },
  { key: "comet_asteroid", center: COMET_CENTER, radius: 2.6, label: "small bodies" },
  { key: "sun", center: SUN_POSITION, radius: SUN_RADIUS, label: "the Sun" },
];

/** Camera pose for inspecting a body the viewer clicked: far enough out to hold the whole
 *  disc, angled so the terminator is visible rather than looking straight down the sunline. */
export function focusCamera(body: CelestialBody): { camPos: THREE.Vector3; lookAt: THREE.Vector3 } {
  const stage = STAGES[body] ?? STAGES.unknown;
  const radius = Math.max(stage.surface, 1.5);
  const toSun = SUN_POSITION.clone().sub(stage.anchor).normalize();
  const side = new THREE.Vector3().crossVectors(toSun, new THREE.Vector3(0, 1, 0)).normalize();
  if (side.lengthSq() < 0.01) side.set(1, 0, 0);
  const dir = toSun
    .multiplyScalar(0.5)
    .add(side.multiplyScalar(0.75))
    .add(new THREE.Vector3(0, 0.3, 0))
    .normalize();
  return {
    camPos: stage.anchor.clone().add(dir.multiplyScalar(radius * 3.6)),
    lookAt: stage.anchor.clone(),
  };
}

const WORLD_UP = new THREE.Vector3(0, 1, 0);

/** Camera pose that frames one stage: stand off along the surface normal, offset to the side
 *  so the body fills part of the frame instead of sitting dead centre. */
export function stageCamera(p: Placement): { camPos: THREE.Vector3; lookAt: THREE.Vector3 } {
  const outward = p.pos.clone().sub(p.stage.anchor).normalize();
  // Close enough that the craft is the subject and the body is the backdrop. Standing off by a
  // multiple of the body radius instead makes Earth-stage shots frame a sphere with a speck on it.
  const dist = 1.55 + p.stage.surface * 0.18;
  const side = new THREE.Vector3().crossVectors(outward, WORLD_UP).normalize();
  if (side.lengthSq() < 0.01) side.set(1, 0, 0);

  const camPos = p.pos
    .clone()
    .add(outward.multiplyScalar(dist))
    .add(side.multiplyScalar(dist * 0.5))
    .add(WORLD_UP.clone().multiplyScalar(dist * 0.28));

  return { camPos, lookAt: p.pos.clone() };
}

/** Opening wide shot. Framed to hold Mercury through Saturn, so the first thing on screen is the
 *  span of the archive rather than one planet. The camera flies in from here on playback. */
export const ESTABLISHING = {
  camPos: new THREE.Vector3(2, 86, 214),
  lookAt: new THREE.Vector3(6, 0, -26),
};

/* A second camera mode that framed the whole body rather than the moment used to live here.
 * It was honest but nearly static: the corpus concentrates so hard on a few worlds that
 * consecutive shots usually shared one, and the camera sat still through most of a reel. The
 * era flight is the only mode now. Clicking a body still frames it, through `focusCamera`. */
