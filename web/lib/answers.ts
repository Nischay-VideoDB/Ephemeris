import { readFile, readdir, stat } from "node:fs/promises";
import { join, resolve } from "node:path";

import type { SavedAnswer } from "./types";

/** Where a live run's result is kept.
 *
 *  Runs used to be written to a temp directory, read once, and deleted in a `finally`. Ninety
 *  seconds of retrieval, synthesis and a compiled reel, thrown away on reload. The preset
 *  answers were the only pipeline output that survived, and only because they were generated
 *  from the CLI with `--json`. Live answers now land next to them.
 *
 *  Server-only: imported by route handlers, never by a client component. */

export const ROOT = resolve(process.cwd(), "..");
export const ANSWERS_DIR = join(ROOT, "data", "answers");

/** Ids are generated here and validated on the way back in, so a request can never walk out
 *  of the directory or name a file this did not write. */
const ID_PATTERN = /^[0-9]{4}-[0-9]{2}-[0-9]{2}t[0-9]{2}-[0-9]{2}-[0-9]{2}(-[a-z0-9-]*)?$/;

export function answerId(question: string, now: Date): string {
  const stamp = now.toISOString().slice(0, 19).toLowerCase().replace(/[:.]/g, "-");
  const slug = question
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48)
    .replace(/-+$/, "");
  return slug ? `${stamp}-${slug}` : stamp;
}

export function isAnswerId(id: string): boolean {
  return ID_PATTERN.test(id);
}

/** Absolute path for an id, or null if the id is not one this module would have produced.
 *  Checked against the resolved directory as well, so a pattern slip cannot become a file read
 *  somewhere else on disk. */
export function answerPath(id: string): string | null {
  if (!isAnswerId(id)) return null;
  const path = resolve(ANSWERS_DIR, `${id}.json`);
  return path.startsWith(resolve(ANSWERS_DIR) + "/") ? path : null;
}

/** Newest first. Reads each file because the question and the counts live inside it; capped so
 *  a directory that has been accumulating for months does not turn a page load into a scan. */
export async function listAnswers(limit = 12): Promise<SavedAnswer[]> {
  let names: string[];
  try {
    names = (await readdir(ANSWERS_DIR)).filter((n) => n.endsWith(".json"));
  } catch {
    return [];
  }

  const dated = await Promise.all(
    names.map(async (name) => {
      try {
        return { name, at: (await stat(join(ANSWERS_DIR, name))).mtimeMs };
      } catch {
        return null;
      }
    }),
  );

  const newest = dated
    .filter((row): row is { name: string; at: number } => row !== null)
    .sort((a, b) => b.at - a.at)
    .slice(0, limit);

  const rows = await Promise.all(
    newest.map(async ({ name, at }) => {
      const id = name.replace(/\.json$/, "");
      try {
        const parsed = JSON.parse(await readFile(join(ANSWERS_DIR, name), "utf8"));
        return {
          id,
          question: String(parsed.question ?? id),
          saved: new Date(at).toISOString(),
          moments: parsed.evidence?.length ?? 0,
          shots: parsed.reel?.shots?.length ?? 0,
          answered: Boolean(parsed.answer?.answer),
        };
      } catch {
        // A half-written or corrupt file is listed rather than hidden: silently dropping it
        // would look like the run never happened.
        return { id, question: id, saved: new Date(at).toISOString(), moments: 0, shots: 0, answered: false };
      }
    }),
  );

  return rows;
}
