import type { Reel, Shot } from "./types";

/** The reel is not always one shot per evidence item.
 *
 *  A moment whose source video is too short to cut from is dropped by the compiler, so the
 *  shot list can be shorter than the evidence list. Everything the viewer clicks is an
 *  evidence item: citation [n], a timeline needle, a beacon in the orrery, a row in a body
 *  panel. Treating shot i as evidence i silently plays the wrong clip, flies the camera to
 *  the wrong world and labels it with the wrong year, from the first dropped moment onward.
 *
 *  So the shot carries `evidence_index` and every lookup goes through here.
 *
 *  Answers compiled before that field existed fall back to the identity mapping, which is
 *  what they were built on and is correct for them: they contain no dropped moments. */

/** Evidence index a shot belongs to. */
export function evidenceIndexOfShot(shot: Shot | undefined, shotIndex: number): number {
  return shot?.evidence_index ?? shotIndex;
}

export interface ReelIndex {
  /** Shot for an evidence index, or undefined when that moment has no footage. */
  shotFor: (evidenceIndex: number) => (Shot & { shotIndex: number }) | undefined;
  /** Evidence index the shot at this position belongs to. */
  evidenceFor: (shotIndex: number) => number;
  /** Evidence indices with no compiled shot. */
  missing: Set<number>;
}

export function indexReel(reel: Reel | undefined, evidenceCount: number): ReelIndex {
  const byEvidence = new Map<number, Shot & { shotIndex: number }>();

  (reel?.shots ?? []).forEach((shot, shotIndex) => {
    byEvidence.set(evidenceIndexOfShot(shot, shotIndex), { ...shot, shotIndex });
  });

  const missing = new Set<number>();
  for (let i = 0; i < evidenceCount; i += 1) if (!byEvidence.has(i)) missing.add(i);

  return {
    shotFor: (evidenceIndex) => byEvidence.get(evidenceIndex),
    evidenceFor: (shotIndex) => evidenceIndexOfShot(reel?.shots?.[shotIndex], shotIndex),
    missing,
  };
}

/** Which shot is on screen at `seconds`. Shots are laid out in ascending `at`, so this is the
 *  last one that has started. Returns -1 before the first shot. */
export function shotIndexAt(reel: Reel | undefined, seconds: number): number {
  const shots = reel?.shots ?? [];
  let index = -1;
  for (let i = 0; i < shots.length; i += 1) {
    if (seconds >= shots[i].at) index = i;
    else break;
  }
  return index;
}
