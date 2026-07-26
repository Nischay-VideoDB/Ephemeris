/** The two invariants the interface rests on, checked without a browser.
 *
 *  1. Evidence to shot mapping. The reel can hold fewer shots than the answer holds evidence,
 *     because a moment whose source yields no usable clip is dropped. Everything the viewer
 *     clicks is an evidence item, so a single dropped moment used to shift every citation,
 *     needle, beacon and camera move after it by one, with no error anywhere. `lib/reel.ts`
 *     is the only place that mapping lives.
 *
 *  2. Placement. Every marker has to sit on the world its own evidence names, clear of its
 *     neighbours, with the camera framing the moment. A camera that flies to the right
 *     coordinates on the wrong world is the same lie as the wrong clip.
 *
 *  Checked against the saved answers in `public/answers`, which are real pipeline output.
 *
 *  Run with:  npm test    (from web/)
 */
import assert from "node:assert";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const root = resolve(import.meta.dirname, "..");

// Emitted inside web/ rather than the system temp dir: `three` is resolved relative to the
// importing file, so a build parked in /tmp cannot find it.
const out = mkdtempSync(join(root, ".tmp-check-"));
const config = join(out, "tsconfig.json");

function compile() {
  writeFileSync(
    config,
    JSON.stringify({
      extends: "../tsconfig.json",
      compilerOptions: {
        noEmit: false,
        outDir: ".",
        module: "esnext",
        target: "es2020",
        skipLibCheck: true,
        rootDir: "..",
      },
      include: ["../lib/reel.ts", "../lib/types.ts", "../components/space/stage.ts"],
    }),
  );
  execFileSync("npx", ["tsc", "-p", config], { cwd: root, stdio: "inherit" });
}

async function main() {
  compile();
  const load = (path) => import(pathToFileURL(join(out, path)).href);
  const { indexReel, evidenceIndexOfShot, shotIndexAt } = await load("lib/reel.js");
  const { placeEvidence, stageCamera, focusCamera, STAGES } = await load("components/space/stage.js");

  /* 1. Mapping, on a synthetic answer with a hole in it. */

  const reel = {
    stream_url: "x",
    shots: [
      { at: 0, duration: 10, evidence_index: 0, nasa_id: "A", caption: "a" },
      { at: 10, duration: 10, evidence_index: 1, nasa_id: "B", caption: "b" },
      { at: 20, duration: 10, evidence_index: 3, nasa_id: "D", caption: "d" },
      { at: 30, duration: 10, evidence_index: 4, nasa_id: "E", caption: "e" },
      { at: 40, duration: 10, evidence_index: 5, nasa_id: "F", caption: "f" },
    ],
    dropped: [{ evidence_index: 2, nasa_id: "C", reason: "source too short to cut a clip from" }],
  };

  const index = indexReel(reel, 6);
  assert.equal(index.shotFor(3).nasa_id, "D", "citation [4] must play D, not the next clip along");
  assert.equal(index.shotFor(5).nasa_id, "F");
  assert.equal(index.shotFor(2), undefined, "the dropped moment has no shot");
  assert.deepEqual([...index.missing], [2]);

  // Playback at 25s is the third shot, which is the fourth moment.
  assert.equal(shotIndexAt(reel, 25), 2);
  assert.equal(evidenceIndexOfShot(reel.shots[2], 2), 3);
  assert.equal(shotIndexAt(reel, 0), 0);
  assert.equal(shotIndexAt(reel, -1), -1, "before the first shot");
  assert.equal(shotIndexAt(reel, 999), 4, "past the end holds the last shot");

  // Answers compiled before the field existed fall back to identity, correct for them.
  const legacy = { stream_url: "x", shots: [{ at: 0, nasa_id: "A" }, { at: 10, nasa_id: "B" }] };
  const legacyIndex = indexReel(legacy, 2);
  assert.equal(legacyIndex.shotFor(1).nasa_id, "B");
  assert.equal(legacyIndex.missing.size, 0);

  console.log("OK  mapping: a dropped moment does not shift the moments after it");

  /* 2. Placement and camera, on every saved answer. */

  const dir = join(root, "public", "answers");
  const files = readdirSync(dir).filter((f) => f.endsWith(".json"));
  assert.ok(files.length, "no saved answers to check");

  for (const file of files) {
    const answer = JSON.parse(readFileSync(join(dir, file), "utf8"));
    const evidence = answer.evidence ?? [];
    const placements = placeEvidence(evidence);
    assert.equal(placements.length, evidence.length, file);

    let jumps = 0;
    placements.forEach((p, i) => {
      assert.equal(p.index, i, `${file}: placement ${i} carries index ${p.index}`);
      assert.equal(p.ev.nasa_id, evidence[i].nasa_id, file);

      // The marker sits on the world its own evidence names.
      const expected = STAGES[p.ev.celestial_body] ? p.ev.celestial_body : "unknown";
      assert.equal(p.stageKey, expected, `${file}: ${p.ev.nasa_id} placed on ${p.stageKey}`);

      // On or above the surface, and still in that body's neighbourhood. The altitude scales
      // with the body, so the upper bound has to as well: an animation off Jupiter legitimately
      // sits further out than a rover on Mars.
      const r = p.pos.distanceTo(p.stage.anchor);
      assert.ok(r >= p.stage.surface - 1e-6, `${file}: ${p.ev.nasa_id} inside ${p.stageKey}`);
      assert.ok(r < p.stage.surface * 2.5 + 6, `${file}: ${p.ev.nasa_id} adrift from ${p.stageKey}`);

      // The era flight frames the moment itself, and stands off rather than sitting on it.
      const era = stageCamera(p);
      assert.ok(era.lookAt.distanceTo(p.pos) < 1e-6, `${file}: the camera must look at the moment`);
      assert.ok(era.camPos.distanceTo(p.pos) > 0.5, `${file}: camera must stand off the marker`);

      // Clicking a body still frames the body, which is a different pose and must stay one.
      const focus = focusCamera(p.stageKey);
      assert.ok(focus.lookAt.distanceTo(p.stage.anchor) < 1e-6, `${file}: focus must look at the body`);

      if (i > 0 && placements[i - 1].stageKey !== p.stageKey) jumps += 1;
    });

    // Two markers never occupy the same point, or one hides the other for good.
    for (let i = 0; i < placements.length; i += 1) {
      for (let j = i + 1; j < placements.length; j += 1) {
        assert.ok(
          placements[i].pos.distanceTo(placements[j].pos) > 0.2,
          `${file}: markers ${i + 1} and ${j + 1} collide`,
        );
      }
    }

    console.log(`OK  placement: ${file} · ${placements.length} moments · ${jumps} stage changes`);
  }
}

try {
  await main();
} finally {
  rmSync(out, { recursive: true, force: true });
}
