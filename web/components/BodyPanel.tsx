"use client";

import { useEffect, useMemo, useState } from "react";
import { indexReel } from "@/lib/reel";
import { useStore } from "@/lib/store";
import type { AskResult, CelestialBody } from "@/lib/types";

/** Corpus-wide facts per body, produced by scripts/dump_bodies.py from real `aggregate()` and
 *  `query()` calls against the mission_meta index. Absent until that script has run, which the
 *  panel handles rather than inventing numbers. */
interface BodyFacts {
  scenes: number;
  clips: number;
  minutes: number;
  era_range: [number, number] | null;
  missions: string[];
  events: Record<string, number>;
}

const LABELS: Partial<Record<CelestialBody, string>> = {
  mars: "Mars",
  earth: "Earth",
  moon: "the Moon",
  earth_orbit: "Earth orbit",
  ground: "Earth, ground sites",
  sun: "the Sun",
  venus: "Venus",
  mercury: "Mercury",
  jupiter: "Jupiter",
  saturn: "Saturn",
  titan: "Titan",
  comet_asteroid: "comets and asteroids",
  deep_space: "deep space",
  unknown: "unplaced",
};

export function BodyPanel({ result }: { result: AskResult | null }) {
  const { focusBody, setFocusBody, selectMoment, activeEvidenceIndex } = useStore();
  const [facts, setFacts] = useState<Record<string, BodyFacts> | null>(null);
  const [factsError, setFactsError] = useState(false);
  const evidence = useMemo(() => result?.evidence ?? [], [result]);
  const reelIndex = useMemo(() => indexReel(result?.reel, evidence.length), [result, evidence.length]);

  useEffect(() => {
    if (facts || factsError) return;
    let cancelled = false;
    fetch("/corpus/bodies.json", { cache: "force-cache" })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("no corpus summary"))))
      .then((data) => !cancelled && setFacts(data.bodies ?? data))
      .catch(() => !cancelled && setFactsError(true));
    return () => {
      cancelled = true;
    };
  }, [facts, factsError]);

  if (!focusBody) return null;

  const fact = facts?.[focusBody];
  const here = evidence
    .map((ev, index) => ({ ev, index }))
    .filter((row) => row.ev.celestial_body === focusBody);

  return (
    <aside className="body-panel">
      <div className="bp-head">
        <h2>{LABELS[focusBody] ?? focusBody}</h2>
        <button className="ask-link" onClick={() => setFocusBody(null)}>
          close
        </button>
      </div>

      {fact ? (
        <>
          <dl className="bp-stats">
            <div>
              <dt>scenes</dt>
              <dd>{fact.scenes}</dd>
            </div>
            <div>
              <dt>clips</dt>
              <dd>{fact.clips}</dd>
            </div>
            <div>
              <dt>footage</dt>
              <dd>{fact.minutes} min</dd>
            </div>
            <div>
              <dt>era</dt>
              <dd>{fact.era_range ? `${fact.era_range[0]}–${fact.era_range[1]}` : "undated"}</dd>
            </div>
          </dl>
          {fact.missions.length > 0 && (
            <p className="bp-missions">
              <span>missions</span> {fact.missions.slice(0, 8).join(" · ")}
            </p>
          )}
        </>
      ) : (
        <p className="note">
          {factsError
            ? "Corpus summary not generated yet: run scripts/dump_bodies.py."
            : "reading corpus summary…"}
        </p>
      )}

      <div className="bp-here">
        <span className="bp-label">in this answer</span>
        {here.length === 0 ? (
          <p className="note">
            Nothing from this answer is set here. The archive may still hold material: ask a
            question about it.
          </p>
        ) : (
          <ul>
            {here.map(({ ev, index }) => (
              <li key={`${ev.nasa_id}-${ev.start}`}>
                <button
                  className="bp-moment"
                  data-active={index === activeEvidenceIndex}
                  onClick={() => selectMoment(index, reelIndex.shotFor(index)?.at ?? null)}
                >
                  <b>[{index + 1}]</b> <span>{ev.era_start ?? "undated"}</span>
                  <em>{ev.mission ?? "mission unknown"}</em>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
