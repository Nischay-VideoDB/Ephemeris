/** Which hardware each moment flies.
 *
 *  The mission is extracted, indexed in `mission_meta`, shown on the hover card and burned into
 *  the reel caption, but for a long time it never reached the scene: 86 distinct missions all
 *  rendered as one of eight shapes chosen by `event_type` alone, so the Shuttle flew as a
 *  generic launch vehicle and Hubble as a generic bus.
 *
 *  What this guards is the restraint, not the substitution. A mission may change what the craft
 *  *is*; it must never change where it stands. Putting a Shuttle on the Martian surface because
 *  a clip mentioned one would be a lie the placement itself tells.
 *
 *  Run with:  npm run check:craft
 */
import assert from "node:assert";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const root = resolve(import.meta.dirname, "..");
const out = mkdtempSync(join(root, ".tmp-craft-"));

function compile() {
  writeFileSync(
    join(out, "tsconfig.json"),
    JSON.stringify({
      extends: "../tsconfig.json",
      compilerOptions: {
        noEmit: false, outDir: ".", module: "esnext", target: "es2020",
        skipLibCheck: true, rootDir: "..",
      },
      include: ["../components/space/stage.ts", "../lib/types.ts"],
    }),
  );
  execFileSync("npx", ["tsc", "-p", join(out, "tsconfig.json")], { cwd: root, stdio: "inherit" });
}

const GROUNDED = ["rover", "lander", "station"];

async function main() {
  compile();
  const { craftFor, placeEvidence, CRAFT_BY_EVENT } = await import(
    pathToFileURL(join(out, "components/space/stage.js")).href
  );

  // The archive's most-filmed hardware gets its own shape.
  assert.equal(craftFor("launch", "Space Shuttle Discovery"), "shuttle");
  assert.equal(craftFor("eva", "STS-125"), "shuttle");
  assert.equal(craftFor("instrument_readout", "Hubble Space Telescope"), "telescope");
  assert.equal(craftFor("other", "Voyager 2"), "deepprobe");
  assert.equal(craftFor("instrument_readout", "Mariner 4"), "deepprobe");
  assert.equal(craftFor("launch", "X-15"), "rocketplane");
  // A rover stays a rover wherever the clip catches it.
  assert.equal(craftFor("instrument_readout", "Curiosity"), "rover");

  // Restraint: a mission never moves a craft off the ground it was placed on.
  for (const event of ["surface_ops", "landing", "briefing"]) {
    const generic = CRAFT_BY_EVENT[event];
    assert.ok(GROUNDED.includes(generic), `${event} should be grounded`);
    assert.equal(craftFor(event, "Space Shuttle Atlantis"), generic,
      `${event} must not be overridden by a mission`);
  }

  // A depiction is not a placement. `data_visualization` and `animation` were grounded here
  // alongside the surface events, on the reading that a mission must never move a craft. But a
  // visualisation is a picture *of* a spacecraft, not ground it stands on, and every telescope
  // moment in the archive is one: with these pinned, the five shipped answers flew no mission
  // hardware between them and Hubble appeared as a generic hologram in a preset about telescopes.
  assert.equal(craftFor("data_visualization", "Hubble Space Telescope"), "telescope");
  assert.equal(craftFor("animation", "Voyager 1"), "deepprobe");
  assert.equal(craftFor("data_visualization", null), "holo");
  assert.equal(craftFor("animation", "SOLRAD"), "holo");

  // No mission, or one nothing matches, falls back to the event's craft.
  assert.equal(craftFor("launch", null), "rocket");
  assert.equal(craftFor("launch", "SOLRAD"), "rocket");
  assert.equal(craftFor("eva", "Gemini"), "capsule");
  console.log("OK  mapping: mission chooses the hardware, never the ground it stands on");

  // Against the saved answers: report coverage rather than assert a number, since it depends
  // entirely on which moments a question happens to retrieve.
  const dir = join(root, "public", "answers");
  let total = 0, eligible = 0, mission = 0;
  const kinds = new Map();
  for (const file of readdirSync(dir).filter((f) => f.endsWith(".json"))) {
    const answer = JSON.parse(readFileSync(join(dir, file), "utf8"));
    for (const p of placeEvidence(answer.evidence ?? [])) {
      total += 1;
      kinds.set(p.craft, (kinds.get(p.craft) ?? 0) + 1);
      const generic = CRAFT_BY_EVENT[p.ev.event_type] ?? "probe";
      if (GROUNDED.includes(generic)) continue;
      eligible += 1;
      if (p.craft !== generic) mission += 1;
    }
  }
  const shapes = [...kinds.entries()].sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `${k} ${n}`).join(", ");
  console.log(`OK  coverage: ${total} moments · ${eligible} eligible · ${mission} fly mission hardware`);
  console.log(`    shapes in use: ${shapes}`);
}

try {
  await main();
} finally {
  rmSync(out, { recursive: true, force: true });
}
