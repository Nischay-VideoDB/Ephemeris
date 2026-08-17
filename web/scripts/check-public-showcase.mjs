import { constants } from "node:fs";
import { access, readdir, readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const web = resolve(here, "..");
const apiDirectory = join(web, "app", "api");

try {
  await access(apiDirectory, constants.F_OK);
  throw new Error("public showcase must not include Next API routes");
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}

const page = await readFile(join(web, "app", "page.tsx"), "utf8");
if (page.includes("/api/")) {
  throw new Error("public showcase page must not call an API route");
}

const answerDirectory = join(web, "public", "answers");
const answerFiles = (await readdir(answerDirectory)).filter((file) => file.endsWith(".json"));
if (answerFiles.length === 0) {
  throw new Error("public showcase needs at least one prepared answer");
}

const sensitiveKey = /api[_-]?key|token|secret|password|authorization|cookie/i;
const sensitiveValue = /(?:sk-|vdb_|bearer\s+|eyJ[A-Za-z0-9_-]{16,})/i;

function inspect(value, path) {
  if (Array.isArray(value)) {
    value.forEach((item, index) => inspect(item, `${path}[${index}]`));
  } else if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      if (sensitiveKey.test(key)) throw new Error(`credential-shaped key at ${path}.${key}`);
      inspect(item, `${path}.${key}`);
    }
  } else if (typeof value === "string" && sensitiveValue.test(value)) {
    throw new Error(`credential-shaped value at ${path}`);
  }
}

for (const file of answerFiles) {
  inspect(JSON.parse(await readFile(join(answerDirectory, file), "utf8")), file);
}

console.log(`OK public showcase: ${answerFiles.length} prepared answers; no API surface or credentials`);
