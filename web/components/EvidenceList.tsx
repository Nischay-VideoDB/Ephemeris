"use client";

import type { Evidence } from "@/lib/types";

const AXIS_LABEL: Record<string, string> = {
  scene: "stated in this scene",
  video: "inferred from clip context",
  published: "upload date only",
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

            {item.text && <div className="ev-text">{item.text}</div>}

            <div className="ev-meta">
              {item.nasa_id} · {item.start.toFixed(0)}–{item.end.toFixed(0)}s
              {item.published_year ? ` · published ${item.published_year}` : ""}
              {item.era_basis ? ` · basis ${item.era_basis}` : ""}
            </div>
          </div>
        );
      })}
    </section>
  );
}
