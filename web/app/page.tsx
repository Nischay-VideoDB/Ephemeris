"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { Answer } from "@/components/Answer";
import { BodyPanel } from "@/components/BodyPanel";
import { EvidenceList } from "@/components/EvidenceList";
import { Reel } from "@/components/Reel";
import { Discarded, Timeline } from "@/components/Sidebar";
import { Trace } from "@/components/Trace";
import type { AskResult } from "@/lib/types";
import { indexReel } from "@/lib/reel";
import { useStore } from "@/lib/store";

const Orrery = dynamic(() => import("@/components/Orrery"), { ssr: false });

/* Ordered strongest first, on what each answer actually contains rather than on subject.
   `water-mars` leads: eight chronology points, the widest citation spread, and the only one
   carrying a mission-corrected date, so the provenance key has all four colours to explain.
   `water-elsewhere` is second because it is the only question that puts moments on three
   different worlds, which is what stops a multi-domain archive reading as Mars-only.
   `telescopes` is last: the widest era span of the four, but every moment sits in deep space,
   so the orrery barely moves. */
const PRESETS = [
  { id: "water-mars", label: "How understanding of water on Mars changed" },
  { id: "water-elsewhere", label: "Where else NASA looked for water and ice" },
  { id: "apollo-surface", label: "What Apollo astronauts did on the lunar surface" },
  { id: "telescopes", label: "How space telescopes changed what we could see" },
];

export default function Page() {
  const { result, setResult, autoFollow, setAutoFollow, selectMoment, activeEvidenceIndex } =
    useStore();
  const [preset, setPreset] = useState("water-mars");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hud, setHud] = useState(true);

  const loadPreset = useCallback(
    async (id: string) => {
      setBusy(true);
      setError(null);
      try {
        const response = await fetch(`/answers/${id}.json`, { cache: "no-store" });
        if (!response.ok) throw new Error(`no saved answer for "${id}"`);
        setResult((await response.json()) as AskResult);
        setPreset(id);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [setResult],
  );

  useEffect(() => {
    void loadPreset("water-mars");
  }, [loadPreset]);

  // H clears the sheets off the scene, for demoing or screen-recording the flight.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) return;
      if (e.key === "h" || e.key === "H") setHud((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // A citation [n] is the nth evidence item, not the nth shot. The reel drops a moment whose
  // source yields no usable clip, so the two lists are not interchangeable.
  const evidence = useMemo(() => result?.evidence ?? [], [result]);
  const reelIndex = useMemo(() => indexReel(result?.reel, evidence.length), [result, evidence.length]);

  function handleCite(n: number) {
    const index = n - 1;
    if (index < 0 || index >= evidence.length) return;
    selectMoment(index, reelIndex.shotFor(index)?.at ?? null);
  }

  const cited = result?.answer?.citations ?? [];
  const activeMoment = evidence[activeEvidenceIndex];

  return (
    <main className="stage-shell">
      <div className="stage-canvas">
        {result && <Orrery evidence={result.evidence} reel={result.reel} cited={cited} />}
      </div>

      <div className="vignette" aria-hidden="true" />
      {hud && result && (
        <>
          <div className="wash left" aria-hidden="true" />
          <div className="wash right" aria-hidden="true" />
        </>
      )}

      {!hud && (
        <button className="restore" onClick={() => setHud(true)}>
          show notes <kbd>H</kbd>
        </button>
      )}

      {hud && (
        <>
          <header className="masthead">
            <h1>Ephemeris</h1>
            <p className="standfirst">A research agent over NASA&rsquo;s archival video.</p>
            <dl className="colophon">
              <div>
                <dt>corpus</dt>
                <dd>87 clips · 1,484 scenes</dd>
              </div>
              <div>
                <dt>era covered</dt>
                <dd>1957–2025</dd>
              </div>
              <div>
                <dt>retrieval</dt>
                <dd>VideoDB</dd>
              </div>
            </dl>
          </header>

          <div className="query">
            <div className="query-presets">
              <span className="gutter-label">Start</span>
              {PRESETS.map((p) => (
                <button
                  key={p.id}
                  className="ask-link"
                  data-active={preset === p.id}
                  disabled={busy}
                  onClick={() => void loadPreset(p.id)}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <p className="query-readonly">
              This public showcase contains prepared, reproducible research journeys. Choose a
              question above to explore its cited evidence, reel, and 3D timeline.
            </p>
            {error && <div className="err">{error}</div>}
          </div>

          <div className="camera-strip">
            <span className="strip-state" data-on={autoFollow}>
              {autoFollow ? "following reel" : "manual orbit"}
            </span>
            {!autoFollow && (
              <button className="ask-link" onClick={() => setAutoFollow(true)}>
                resume
              </button>
            )}
          </div>

          {/* Flight controls sit under the camera state at the top right: they describe the same
              thing the camera strip reports on, and as a ruled key/action table they read as a
              legend rather than as a sentence of keys run together. */}
          <dl className="flightkeys">
            <div>
              <dt>
                <kbd>W</kbd>
                <kbd>A</kbd>
                <kbd>S</kbd>
                <kbd>D</kbd>
              </dt>
              <dd>fly</dd>
            </div>
            <div>
              <dt>
                <kbd>R</kbd>
                <kbd>F</kbd>
              </dt>
              <dd>up, down</dd>
            </div>
            <div>
              <dt className="verb">drag</dt>
              <dd>orbit</dd>
            </div>
            <div>
              <dt className="verb">click</dt>
              <dd>a body</dd>
            </div>
          </dl>

          <div className="nav-strip">
            <button className="ask-link" onClick={() => setHud(false)}>
              hide notes <kbd>H</kbd>
            </button>
          </div>

          {result && (
            <>
              <div className="column left">
                <section className="sheet">
                  <h2>Answer</h2>
                  <Answer answer={result.answer} onCite={handleCite} />
                </section>

                <details className="sheet fold">
                  <summary>
                    Agent trace <span className="count">{result.trace.length} steps</span>
                  </summary>
                  <Trace steps={result.trace} />
                </details>

                <details className="sheet fold">
                  <summary>
                    Discarded{" "}
                    <span className="count">
                      {result.rejected.counts.diversity + result.rejected.counts.below_threshold} moments
                    </span>
                  </summary>
                  <Discarded rejected={result.rejected} />
                </details>
              </div>

              <div className="column right">
                <section className="sheet">
                  <h2>Evidence reel</h2>
                  <Reel reel={result.reel} />
                </section>

                <details className="sheet fold">
                  <summary>
                    Evidence <span className="count">{result.evidence.length} moments</span>
                  </summary>
                  <EvidenceList evidence={result.evidence} cited={cited} />
                </details>
              </div>

              {activeMoment && (
                <div className="slug">
                  <i className={`swatch ${activeMoment.era_axis ?? "published"}`} />
                  <b>{activeMoment.era_start ?? "undated"}</b>
                  <span>{activeMoment.mission ?? "mission unknown"}</span>
                  <em>{activeMoment.nasa_id}</em>
                </div>
              )}

              <BodyPanel result={result} />

              <div className="ruler-dock">
                {/* The needle colours are the ruler's only unexplained mark, so the key sits
                    directly above it rather than in the right rail. The gloss on each entry is a
                    tooltip: the words carry the meaning, so colour is still never the only
                    channel. */}
                <ul className="axis-legend">
                  <li title="spoken or on screen in that shot">
                    <i className="swatch scene" />
                    stated in the scene
                  </li>
                  <li title="the extracted year fell outside the mission's operating dates, so those decided it instead">
                    <i className="swatch mission" />
                    from mission dates
                  </li>
                  <li title="the clip is about that year, the shot does not say so">
                    <i className="swatch video" />
                    from clip context
                  </li>
                  <li title="weakest: when NASA posted the file, not when it happened">
                    <i className="swatch published" />
                    upload date only
                  </li>
                </ul>

                <Timeline timeline={result.timeline} evidence={result.evidence} reel={result.reel} />
              </div>
            </>
          )}
        </>
      )}

      {!result && busy && <div className="booting">acquiring archive…</div>}
    </main>
  );
}
