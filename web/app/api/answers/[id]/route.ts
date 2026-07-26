import { readFile } from "node:fs/promises";

import { answerPath } from "@/lib/answers";

/** One saved run, by the id `/api/ask` reported. The id is validated against the pattern this
 *  server generates and the resolved path is checked to be inside the answers directory, so a
 *  crafted id cannot read a file elsewhere on disk. */

export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  const path = answerPath(id);
  if (!path) return Response.json({ error: "unknown answer" }, { status: 400 });

  try {
    return new Response(await readFile(path, "utf8"), {
      headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
    });
  } catch {
    return Response.json({ error: `no saved answer "${id}"` }, { status: 404 });
  }
}
