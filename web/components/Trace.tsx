"use client";

import type { TraceStep } from "@/lib/types";

/** Archive-style phrasings are highlighted, because bridging the researcher's
 *  vocabulary to the archive's is the step that makes retrieval work at all. */
const ARCHIVE_HINTS = [
  "the first of two",
  "twin rovers",
  "orbiter",
  "rover",
  "detected",
  "revealed",
  "examined",
  "found evidence",
];

function looksArchival(phrase: string) {
  const lower = phrase.toLowerCase();
  return ARCHIVE_HINTS.some((h) => lower.includes(h)) && !phrase.trim().endsWith("?");
}

export function Trace({ steps }: { steps: TraceStep[] }) {
  return (
    <section className="panel">
      {steps.map((step) => (
        <div key={step.n}>
          <div className="trace-step">
            <span className="n">{step.n}</span>
            <span className="kind">{step.kind}</span>
            <span>{step.summary}</span>
            <span className="at">{step.at.toFixed(2)}s</span>
          </div>

          {step.kind === "decompose" && (
            <div className="trace-detail">
              {step.rationale && <div style={{ marginBottom: 6 }}>{step.rationale}</div>}
              {step.sub_questions?.map((q) => (
                <span className="phr" key={q}>
                  {q}
                </span>
              ))}
              {step.phrasings?.map((p) => (
                <span className={looksArchival(p) ? "phr archive" : "phr"} key={p}>
                  {p}
                  {looksArchival(p) && (
                    <em style={{ color: "var(--accent-warm)", fontStyle: "normal" }}>
                      {" "}
                      · archive phrasing
                    </em>
                  )}
                </span>
              ))}
              {step.visual_phrasings?.map((p) => (
                <span className="phr" key={p} style={{ color: "var(--ink-faint)" }}>
                  visual: {p}
                </span>
              ))}
            </div>
          )}

          {step.kind === "retrieve" && (
            <div className="trace-detail">
              {step.queries_run} queries run, one index at a time.{" "}
              {step.hits_by_index &&
                Object.entries(step.hits_by_index).map(([k, v]) => (
                  <code key={k}>
                    {k} {v}
                  </code>
                ))}
              {step.thresholds && (
                <div style={{ marginTop: 4 }}>
                  thresholds{" "}
                  {Object.entries(step.thresholds).map(([k, v]) => (
                    <code key={k}>
                      {k} ≥ {v}
                    </code>
                  ))}
                </div>
              )}
            </div>
          )}

          {step.kind === "diversify" && step.kept_per_clip && (
            <div className="trace-detail">
              round-robin by clip, cap {step.per_video_cap} ·{" "}
              {Object.keys(step.kept_per_clip).length} clips represented
            </div>
          )}

          {step.kind === "order" && (
            <div className="trace-detail">
              {step.era_axis_counts &&
                Object.entries(step.era_axis_counts).map(([k, v]) => (
                  <code key={k}>
                    {k} {v}
                  </code>
                ))}
              {step.note && <div style={{ marginTop: 4 }}>{step.note}</div>}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}
