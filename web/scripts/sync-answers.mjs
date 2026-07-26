/** Copy pipeline output into public/answers so the deployed page serves real results.
 *
 *  These files are produced by `python scripts/ask.py --preset <id> --json ...`.
 *  Nothing here is hand-written or mocked; this script only moves files. */

import { copyFile, mkdir, readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const web = resolve(here, "..");
const root = resolve(web, "..");

const MAP = {
  "water-mars": "answer_water_mars.json",
  "first-images": "answer_first_images.json",
  "water-elsewhere": "answer_water_elsewhere.json",
  "apollo-surface": "answer_apollo_surface.json",
  "telescopes": "answer_telescopes.json",
};

const outDir = join(web, "public", "answers");
await mkdir(outDir, { recursive: true });

for (const [id, file] of Object.entries(MAP)) {
  const from = join(root, "data", file);
  const to = join(outDir, `${id}.json`);
  try {
    const parsed = JSON.parse(await readFile(from, "utf8"));
    const shots = parsed.reel?.shots?.length ?? 0;
    await copyFile(from, to);
    console.log(
      `${id.padEnd(14)} ${parsed.evidence?.length ?? 0} evidence, ${shots} reel shots` +
        `${parsed.reel?.stream_url ? "" : "  (no reel stream)"}`,
    );
  } catch (error) {
    console.error(`${id.padEnd(14)} FAILED: ${error.message}`);
    process.exitCode = 1;
  }
}
