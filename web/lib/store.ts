import { create } from 'zustand';
import type { AskResult, CelestialBody } from './types';

interface StoreState {
  result: AskResult | null;
  setResult: (result: AskResult | null) => void;
  /** The selected moment, as an index into `result.evidence`. Evidence is the canonical
   *  ordering: the reel can be shorter than it when a source yields no usable footage, so a
   *  shot index would drift out of step with the beacons, the needles and the citations. */
  activeEvidenceIndex: number;
  setActiveEvidenceIndex: (i: number) => void;
  cameraMode: "era" | "space";
  setCameraMode: (m: "era" | "space") => void;
  autoFollow: boolean;
  setAutoFollow: (f: boolean) => void;
  seekTarget: number | null;
  setSeekTarget: (t: number | null) => void;
  /** Pick a moment: highlights it, flies the camera, and seeks the reel. The index is set here
   *  rather than waiting for the video's timeupdate, so a click still moves the camera when the
   *  stream is slow to load or paused. `at` is null for a moment with no footage in the reel:
   *  the camera still flies to it, there is just nothing to seek to. */
  selectMoment: (evidenceIndex: number, at: number | null) => void;
  /** False until the reel plays or the user picks a moment. Until then the camera holds a wide
   *  establishing shot instead of snapping to shot 1, which would hide the rest of the scene
   *  before the viewer has seen what is in it. */
  engaged: boolean;
  setEngaged: (v: boolean) => void;
  /** A body the viewer clicked. The camera parks in orbit around it and the panel describes
   *  what the archive holds there. Independent of the reel: exploring the scene should not
   *  hijack playback, and playback should not yank the camera away mid-read. */
  focusBody: CelestialBody | null;
  setFocusBody: (body: CelestialBody | null) => void;
  /** Back to the opening wide shot. Free flight can leave the camera anywhere, including
   *  outside the solar system looking at empty sky, so there has to be a way home. */
  resetView: () => void;
}

export const useStore = create<StoreState>((set) => ({
  result: null,
  setResult: (result) =>
    set({ result, activeEvidenceIndex: 0, autoFollow: true, seekTarget: null, engaged: false,
          focusBody: null }),
  activeEvidenceIndex: 0,
  setActiveEvidenceIndex: (i) => set({ activeEvidenceIndex: i }),
  cameraMode: "era",
  setCameraMode: (cameraMode) => set({ cameraMode, autoFollow: true }),
  autoFollow: true,
  setAutoFollow: (autoFollow) => set({ autoFollow }),
  seekTarget: null,
  setSeekTarget: (seekTarget) => set({ seekTarget, autoFollow: true, engaged: true }),
  selectMoment: (evidenceIndex, at) =>
    set({ activeEvidenceIndex: evidenceIndex, seekTarget: at, autoFollow: true, engaged: true,
          focusBody: null }),
  engaged: false,
  setEngaged: (engaged) => set({ engaged }),
  focusBody: null,
  // Focusing a body is a deliberate detour, so it stops the reel following. Clearing focus
  // hands the camera back.
  setFocusBody: (focusBody) => set({ focusBody, autoFollow: focusBody === null }),
  resetView: () => set({ focusBody: null, engaged: false, autoFollow: true }),
}));
