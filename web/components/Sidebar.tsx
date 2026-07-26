"use client";

import { useMemo } from "react";

import type { AskResult, Reel } from "@/lib/types";

import { indexReel } from "@/lib/reel";
import { useStore } from "@/lib/store";

/** The era axis: the year each moment *discusses*, which is not the upload date and differs from
 *  it by decades. Faint bars behind the nodes are the whole archive's decade histogram, so it is
 *  visible how much of the corpus sits in a decade versus how much this answer drew from it. */
export function Timeline({
  timeline,
  evidence,
  reel,
}: {
  timeline: AskResult["timeline"];
  evidence: AskResult["evidence"];
  reel?: Reel;
}) {
  const { activeEvidenceIndex, selectMoment } = useStore();
  const reelIndex = useMemo(() => indexReel(reel, evidence.length), [reel, evidence.length]);

  const decades = timeline.map((b) => b.decade);
  const maxScenes = Math.max(1, ...timeline.map((b) => b.scenes));
  const archiveScenes = timeline.reduce((sum, b) => sum + b.scenes, 0);
  const dated = evidence.filter((e) => e.era_start !== null);
  const undated = evidence.filter((e) => e.era_start === null);

  // Pad to whole decades so the ruler ticks land on round years.
  const lo = Math.floor(Math.min(...decades, ...dated.map((e) => e.era_start as number)) / 10) * 10;
  const hi = Math.ceil((Math.max(...decades.map((d) => d + 9), ...dated.map((e) => e.era_start as number)) + 1) / 10) * 10;
  const span = Math.max(hi - lo, 10);
  const pct = (year: number) => ((year - lo) / span) * 100;

  // Decade labels, with an unlabelled tick every two years between them: a ruler you can read a
  // date off, rather than a bar with dots on it.
  const decadeTicks: number[] = [];
  for (let y = lo; y <= hi; y += 10) decadeTicks.push(y);
  const minorTicks: number[] = [];
  for (let y = lo; y <= hi; y += 2) if (y % 10 !== 0) minorTicks.push(y);

  const activeYear = evidence[activeEvidenceIndex]?.era_start ?? null;

  function seek(index: number) {
    selectMoment(index, reelIndex.shotFor(index)?.at ?? null);
  }

  return (
    <section className="ruler">
      <div className="ruler-head">
        <span className="ruler-title">Era discussed</span>
        <span className="ruler-note">
          the year each moment is <em>about</em>. NASA uploaded most of this footage decades later ·
          faint bars are all {archiveScenes} archive scenes by decade
        </span>
        <span className="ruler-range">
          {lo}–{hi}
        </span>
      </div>

      <div className="ruler-track">
        {/* Archive density: how many of the corpus's scenes sit in each decade. */}
        {timeline.map((bucket) => (
          <span
            key={bucket.decade}
            className="ruler-density"
            style={{
              left: `${pct(bucket.decade)}%`,
              width: `${(10 / span) * 100}%`,
              height: `${8 + (bucket.scenes / maxScenes) * 52}%`,
            }}
            title={`${bucket.decade}s · ${bucket.scenes} of ${archiveScenes} archive scenes`}
          />
        ))}

        {minorTicks.map((year) => (
          <span key={year} className="ruler-tick minor" style={{ left: `${pct(year)}%` }} />
        ))}
        {decadeTicks.map((year) => (
          <span key={year} className="ruler-tick major" style={{ left: `${pct(year)}%` }}>
            <b>{year}</b>
          </span>
        ))}

        {dated.map((ev) => {
          const index = evidence.indexOf(ev);
          const isActive = index === activeEvidenceIndex;
          return (
            <button
              key={`${ev.nasa_id}-${ev.start}`}
              className={`needle ${ev.era_axis ?? "published"}`}
              data-active={isActive}
              style={{ left: `${pct(ev.era_start as number)}%` }}
              onClick={() => seek(index)}
              title={`[${index + 1}] ${ev.era_start} · ${ev.mission ?? "mission unknown"} · ${ev.title}`}
              aria-label={`evidence ${index + 1}, era ${ev.era_start}, ${ev.title}`}
            >
              <span className="needle-flag">
                {index + 1} · {ev.era_start}
              </span>
            </button>
          );
        })}

        {activeYear !== null && (
          <span className="ruler-playhead" style={{ left: `${pct(activeYear)}%` }} />
        )}
      </div>

      {undated.length > 0 && (
        <div className="ruler-foot">
          undated, kept anyway
          {undated.map((ev) => {
            const index = evidence.indexOf(ev);
            return (
              <button key={index} className="cite" onClick={() => seek(index)}>
                {index + 1}
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}

export function Discarded({ rejected }: { rejected: AskResult["rejected"] }) {
  const { counts } = rejected;
  return (
    <section className="panel">
      <p className="note">
        {counts.diversity} dropped by coverage policy, {counts.below_threshold} below threshold.
        High-scoring shots are dropped on purpose once a clip has contributed its share, otherwise
        a chronology gets built from one source.
      </p>
      <div className="rej">
        {rejected.diversity.slice(0, 14).map((row, i) => (
          <div className="r" key={`d-${i}`}>
            <span>coverage</span>
            <span>{row.nasa_id}</span>
            <span>{row.score.toFixed(3)}</span>
          </div>
        ))}
        {rejected.below_threshold.slice(0, 10).map((row, i) => (
          <div className="r" key={`t-${i}`}>
            <span>weak</span>
            <span>{row.index ?? row.detail ?? "—"}</span>
            <span>{row.score !== undefined ? row.score.toFixed(3) : "—"}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
