/** Narrow-screen card geometry, checked from the same helper Orrery calls in its render loop.
 *
 * The 390px case is the production regression: a 240px card projected from x=245.75 used to
 * end at x=485.75. The mobile CSS keeps a 16px readable gutter, and the helper supplies only
 * the extra horizontal translation required by the current projected DOM bounds.
 */
import assert from "node:assert";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const root = resolve(import.meta.dirname, "..");
const out = mkdtempSync(join(root, ".tmp-marker-card-"));

function compile() {
  const config = join(out, "tsconfig.json");
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
      include: ["../lib/markerCard.ts"],
    }),
  );
  execFileSync("npx", ["tsc", "-p", config], { cwd: root, stdio: "inherit" });
}

function assertReadable(bounds, viewportWidth, markerCardHorizontalNudge) {
  const nudge = markerCardHorizontalNudge(bounds, viewportWidth);
  assert.ok(bounds.left + nudge >= 16 - 0.001, "card must not leave the left gutter");
  assert.ok(bounds.right + nudge <= viewportWidth - 16 + 0.001, "card must not leave the right gutter");
}

async function main() {
  compile();
  const { markerCardHorizontalNudge } = await import(pathToFileURL(join(out, "lib/markerCard.js")).href);

  // Exact production evidence: x=245.75 to x=485.75 in a 390px viewport.
  assertReadable({ left: 245.75, right: 485.75 }, 390, markerCardHorizontalNudge);
  // A marker near the other edge must receive the corresponding correction.
  assertReadable({ left: -18, right: 222 }, 390, markerCardHorizontalNudge);

  const css = readFileSync(join(root, "app/globals.css"), "utf8");
  const scene = readFileSync(join(root, "components/Orrery.tsx"), "utf8");
  assert.match(css, /width:\s*min\(240px, calc\(100vw - 32px\)\)/);
  assert.match(css, /--marker-card-mobile-nudge/);
  assert.match(scene, /markerCardHorizontalNudge\(card\.getBoundingClientRect\(\), window\.innerWidth\)/);
  console.log("OK  marker card: 390px evidence cards remain inside the 16px viewport gutter");
}

try {
  await main();
} finally {
  rmSync(out, { recursive: true, force: true });
}
