"use client";

import type { Evidence } from "@/lib/types";

const AXIS_LABEL: Record<string, string> = {
  scene: "stated in this scene",
  video: "inferred from clip context",
  published: "upload date only",
  mission: "corrected to the mission's dates",
};

export function EvidenceList({
  evidence,
  cited,
}: {
  evidence: Evidence[];
  cited: number[];
}) {
  return (
    <section className="panel">
      <p className="note">In the order the reel plays them: earliest era first.</p>
      {evidence.map((item, i) => {
        const n = i + 1;
        const axis = item.era_axis ?? "published";
        return (
          <div className="ev" id={`ev-${n}`} key={`${item.nasa_id}-${item.start}`}
               data-cited={cited.includes(n)}>
            <div className="ev-head">
              <span className="ev-num">[{n}]</span>
              <span className="ev-era">{item.era_start ?? "undated"}</span>
              <span className={`tag ${axis}`} title={AXIS_LABEL[axis]}>
                {axis}
              </span>
              <span style={{ color: "var(--ink-dim)" }}>{item.mission ?? "unknown mission"}</span>
              <span className="tag">{item.index}</span>
              <span className="tag">{item.score.toFixed(3)}</span>
            </div>

            {/* What the clip says, which is what plays. `text` is only the fragment the search
                matched, and on the indexing grid that fragment usually begins mid-clause. */}
            {(item.spoken || item.text) && (
              <div className="ev-text">{item.spoken || item.text}</div>
            )}

            <div className="ev-meta">
              {item.nasa_id} · {item.start.toFixed(0)}–{item.end.toFixed(0)}s
              {item.clip_axis === "sentence" ? " · cut to sentence" : ""}
              {item.published_year ? ` · published ${item.published_year}` : ""}
              {item.era_basis ? ` · basis ${item.era_basis}` : ""}
            </div>
            {item.source_url && (
              <a
                className="evidence-source"
                href={`${item.source_url}#t=${Math.max(0, item.start).toFixed(1)},${Math.max(item.start, item.end).toFixed(1)}`}
                target="_blank"
                rel="noreferrer"
                style={{ display: "inline-block", marginTop: 8 }}
                aria-label={`Play evidence ${n} in the original NASA footage`}
              >
                Play NASA source at {Math.floor(item.start / 60)}:{String(Math.floor(item.start % 60)).padStart(2, "0")}
              </a>
            )}
          </div>
        );
      })}
    </section>
  );
}
