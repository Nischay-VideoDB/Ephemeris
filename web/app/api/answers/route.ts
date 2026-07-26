import { listAnswers } from "@/lib/answers";

/** Runs saved by `/api/ask`, newest first. Without this the files in `data/answers` would be
 *  write-only as far as the interface is concerned. */

export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  const requested = Number(new URL(request.url).searchParams.get("limit"));
  const limit = Number.isFinite(requested) ? Math.min(Math.max(requested, 1), 50) : 12;

  try {
    return Response.json({ answers: await listAnswers(limit) });
  } catch (error) {
    return Response.json(
      { error: error instanceof Error ? error.message : String(error) },
      { status: 500 },
    );
  }
}
