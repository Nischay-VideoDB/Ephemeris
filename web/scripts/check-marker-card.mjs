/** Narrow-screen card geometry, checked from the same helper Orrery calls in its render loop.
 *
 * The 390px case is the production regression: a 240px card projected from x=245.75 used to
 * end at x=485.75. The mobile CSS keeps a 16px readable gutter. Orrery recovers natural bounds
 * from the measured card and its current inline offset, then applies the helper's absolute target.
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

function targetFromMeasured(naturalBounds, appliedNudge, viewportWidth, markerCardHorizontalNudge) {
  const measuredBounds = {
    left: naturalBounds.left + appliedNudge,
    right: naturalBounds.right + appliedNudge,
  };
  return markerCardHorizontalNudge(
    {
      left: measuredBounds.left - appliedNudge,
      right: measuredBounds.right - appliedNudge,
    },
    viewportWidth,
  );
}

function assertReadable(naturalBounds, appliedNudge, viewportWidth, markerCardHorizontalNudge) {
  const targetNudge = targetFromMeasured(naturalBounds, appliedNudge, viewportWidth, markerCardHorizontalNudge);
  assert.ok(naturalBounds.left + targetNudge >= 16 - 0.001, "card must not leave the left gutter");
  assert.ok(naturalBounds.right + targetNudge <= viewportWidth - 16 + 0.001, "card must not leave the right gutter");
  return targetNudge;
}

async function main() {
  compile();
  const { markerCardHorizontalNudge } = await import(pathToFileURL(join(out, "lib/markerCard.js")).href);

  // Exact production evidence: x=245.75 to x=485.75 in a 390px viewport.
  const productionTarget = assertReadable({ left: 245.75, right: 485.75 }, 0, 390, markerCardHorizontalNudge);
  assert.equal(productionTarget, -111.75);

  // A marker near the other edge must receive the corresponding correction.
  assert.equal(assertReadable({ left: -18, right: 222 }, 0, 390, markerCardHorizontalNudge), 34);

  // The measured box can appear inside the viewport only because a previous frame moved it.
  // Recovering its natural bounds makes the new target smaller, then returns it to zero once
  // the camera projection no longer needs a clamp.
  const reducedTarget = assertReadable({ left: 190, right: 430 }, productionTarget, 390, markerCardHorizontalNudge);
  assert.equal(reducedTarget, -56);
  assert.ok(Math.abs(reducedTarget) < Math.abs(productionTarget), "a stale correction must relax");
  assert.equal(
    targetFromMeasured({ left: 80, right: 320 }, reducedTarget, 390, markerCardHorizontalNudge),
    0,
    "a centered natural projection must clear the prior inline nudge",
  );

  // The same 16px gutter applies throughout the mobile range, including its 900px boundary.
  for (const [viewportWidth, bounds] of [
    [320, { left: 100, right: 340 }],
    [390, { left: 245.75, right: 485.75 }],
    [900, { left: 700, right: 940 }],
  ]) {
    assertReadable(bounds, 0, viewportWidth, markerCardHorizontalNudge);
  }

  const css = readFileSync(join(root, "app/globals.css"), "utf8");
  const scene = readFileSync(join(root, "components/Orrery.tsx"), "utf8");
  assert.match(css, /width:\s*min\(240px, calc\(100vw - 32px\)\)/);
  assert.match(css, /--marker-card-mobile-nudge/);
  assert.match(css, /@media \(max-width: 900px\)/);
  assert.match(scene, /window\.innerWidth > 900/);
  assert.match(scene, /left: bounds\.left - appliedNudge/);
  assert.match(scene, /right: bounds\.right - appliedNudge/);
  assert.match(scene, /markerCardHorizontalNudge\(naturalBounds, window\.innerWidth\)/);

  const unchangedGuard = scene.indexOf("if (Math.abs(targetNudge - appliedNudge) < 0.5) return;");
  const styleWrite = scene.indexOf('card.style.setProperty("--marker-card-mobile-nudge", `${targetNudge}px`);');
  assert.ok(unchangedGuard >= 0 && unchangedGuard < styleWrite, "unchanged targets must not write every frame");
  console.log("OK  marker card: absolute mobile offsets stay inside the gutter and relax after projection changes");
}

try {
  await main();
} finally {
  rmSync(out, { recursive: true, force: true });
}
