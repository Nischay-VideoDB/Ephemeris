import { listAnswers } from "@/lib/answers";

/** Runs saved by `/api/ask`, newest first. Without this the files in `data/answers` would be
 *  write-only as far as the interface is concerned. */

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  // `searchParams.get` returns null when the parameter is absent, and `Number(null)` is 0,
  // which is finite. Reading it straight into the guard below sent every default request
  // through the clamp and pinned it to one result, so the interface listed a single saved run
  // and looked like it was discarding the rest.
  const raw = new URL(request.url).searchParams.get("limit");
  const requested = raw === null || raw.trim() === "" ? NaN : Number(raw);
  // The ceiling is a guard against a pathological directory, not a policy about how many runs
  // are worth keeping: every question asked stays reachable.
  const limit = Number.isFinite(requested)
    ? Math.min(Math.max(Math.trunc(requested), 1), 500)
    : 12;

  try {
    return Response.json(await listAnswers(limit));
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 500 },
    );
  }
}
