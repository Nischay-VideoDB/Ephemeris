"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { Answer } from "@/components/Answer";
import { BodyPanel } from "@/components/BodyPanel";
import { EvidenceList } from "@/components/EvidenceList";
import { Reel } from "@/components/Reel";
import { Discarded, Timeline } from "@/components/Sidebar";
import { Trace } from "@/components/Trace";
import type { AskResult, SavedAnswer } from "@/lib/types";
import { indexReel } from "@/lib/reel";
import { useStore } from "@/lib/store";

const Orrery = dynamic(() => import("@/components/Orrery"), { ssr: false });

/* Chosen to span the archive rather than to flatter one subject. Mars is 14% of the corpus
   and Earth 31%, so leading with two Mars questions made a multi-domain archive look
   Mars-only. The cross-body question loads first for the same reason. */
const PRESETS = [
  { id: "water-elsewhere", label: "Where else NASA looked for water and ice" },
  { id: "apollo-surface", label: "What Apollo astronauts did on the lunar surface" },
  { id: "telescopes", label: "How space telescopes changed what we could see" },
  { id: "water-mars", label: "How understanding of water on Mars changed" },
];

export default function Page() {
  const { result, setResult, autoFollow, setAutoFollow, selectMoment, activeEvidenceIndex, resetView } =
    useStore();
  const [preset, setPreset] = useState("water-elsewhere");
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hud, setHud] = useState(true);
  // Live reasoning steps for a question in flight. A run takes about ninety seconds, so
  // the loop has to be visible while it works.
  const [progress, setProgress] = useState<{ n: number; kind: string; summary: string; at: number }[]>([]);
  const [elapsed, setElapsed] = useState(0);
  // A finished run used to change nothing but the text inside one panel, ninety seconds after
  // the button was pressed and usually below the fold. It was indistinguishable from a run that
  // had silently failed. The answer sheet is scrolled to and flashed, and this receipt says the
  // run landed.
  const [landed, setLanded] = useState<{ seconds: number; moments: number; id?: string } | null>(null);
  const answerRef = useRef<HTMLElement | null>(null);
  // Runs saved to data/answers. Reloading one costs a file read instead of ninety seconds.
  const [saved, setSaved] = useState<SavedAnswer[]>([]);

  const loadSavedList = useCallback(async () => {
    try {
      const response = await fetch("/api/answers", { cache: "no-store" });
      if (!response.ok) return;
      const payload = await response.json();
      setSaved(payload.answers ?? []);
    } catch {
      // A missing history is not worth an error banner over the answer itself.
    }
  }, []);

  useEffect(() => {
    void loadSavedList();
  }, [loadSavedList]);

  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    setElapsed(0);
    const timer = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500);
    return () => clearInterval(timer);
  }, [busy]);

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
    void loadPreset("water-elsewhere");
  }, [loadPreset]);

  const loadSaved = useCallback(
    async (id: string) => {
      setBusy(true);
      setError(null);
      setLanded(null);
      try {
        const response = await fetch(`/api/answers/${id}`, { cache: "no-store" });
        if (!response.ok) throw new Error(`could not reload "${id}"`);
        setResult((await response.json()) as AskResult);
        setPreset("");
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setBusy(false);
      }
    },
    [setResult],
  );

  // Bring the new answer to the eye. The left column scrolls independently and the sheet is
  // often out of view by the time a run finishes.
  useEffect(() => {
    if (!landed) return;
    const sheet = answerRef.current;
    sheet?.scrollIntoView({ behavior: "smooth", block: "start" });
    sheet?.classList.add("landed");
    const clear = setTimeout(() => sheet?.classList.remove("landed"), 2400);
    return () => clearTimeout(clear);
  }, [landed]);

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

  async function runLive() {
    const q = question.trim();
    if (!q) return;
    setBusy(true);
    setError(null);
    setProgress([]);
    setLanded(null);
    const started = Date.now();

    try {
      const response = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: q }),
      });

      // A validation failure still comes back as plain JSON.
      if (!response.ok && !response.headers.get("content-type")?.includes("event-stream")) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error ?? `request failed (${response.status})`);
      }
      if (!response.body) throw new Error("no response body");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let answered = false;

      // Minimal SSE reader: events are separated by a blank line, each carrying one
      // `event:` name and one `data:` payload.
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let split = buffer.indexOf("\n\n");
        while (split !== -1) {
          const chunk = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);
          split = buffer.indexOf("\n\n");

          const name = /^event: (.*)$/m.exec(chunk)?.[1];
          const raw = /^data: (.*)$/m.exec(chunk)?.[1];
          if (!name || !raw) continue;
          const data = JSON.parse(raw);

          if (name === "progress") {
            setProgress((steps) => [...steps, data]);
          } else if (name === "error") {
            throw new Error(data.error ?? "agent failed");
          } else if (name === "result") {
            const answerResult = data as AskResult;
            setResult(answerResult);
            setPreset("");
            setLanded({
              seconds: Math.round((Date.now() - started) / 1000),
              moments: answerResult.evidence?.length ?? 0,
              id: answerResult.saved_id,
            });
            answered = true;
            void loadSavedList();
          }
        }
      }

      if (!answered) throw new Error("the agent produced no answer");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

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

  // The camera has one mode now, so the strip states what it is doing rather than offering a
  // choice: the years this answer travels through, taken from the moments themselves.
  const eraSpan = useMemo(() => {
    const years = evidence.map((e) => e.era_start).filter((y): y is number => y !== null);
    if (!years.length) return null;
    const [lo, hi] = [Math.min(...years), Math.max(...years)];
    return lo === hi ? `${lo}` : `${lo} → ${hi}`;
  }, [evidence]);

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
            <h1>Mission Control</h1>
            <p className="standfirst">A research agent over NASA&rsquo;s archival video.</p>
            <dl className="colophon">
              <div>
                <dt>corpus</dt>
                <dd>87 clips · 240 min · 1,484 scenes</dd>
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
            <div className="query-line">
              <label htmlFor="q">Ask</label>
              <input
                id="q"
                value={question}
                placeholder="how did the instruments for finding water change?"
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !busy && void runLive()}
                disabled={busy}
              />
              <button className="run" onClick={() => void runLive()} disabled={busy || !question.trim()}>
                {busy ? "running…" : "→"}
              </button>
            </div>
            {error && <div className="err">{error}</div>}

            {busy && (
              <div className="running">
                <div className="running-head">
                  <span className="spin" aria-hidden="true" />
                  searching 1,484 scenes · {elapsed}s
                  <span className="running-note">usually about 90s</span>
                </div>
                <ol className="running-steps">
                  {progress.map((step) => (
                    <li key={step.n}>
                      <b>{step.kind}</b> {step.summary}
                    </li>
                  ))}
                  {progress.length === 0 && <li className="waiting">planning the search…</li>}
                  {/* Retrieval reports in a burst, then synthesis runs for half a minute with
                      nothing to say. Without this the list looks stalled at the last step. */}
                  {progress.length > 0 && progress[progress.length - 1].kind !== "synthesize" && (
                    <li className="waiting">
                      {progress[progress.length - 1].kind === "aggregate" ||
                      progress[progress.length - 1].kind === "order"
                        ? "reading the moments and writing the answer…"
                        : "working…"}
                    </li>
                  )}
                </ol>
              </div>
            )}

            {!busy && landed && (
              <div className="landed-note">
                answered in {landed.seconds}s · {landed.moments} moments · reel compiled
                {landed.id && <span className="landed-file"> · saved as {landed.id}.json</span>}
              </div>
            )}

            {/* Every live run is kept, so a question asked once never has to be paid for twice. */}
            {saved.length > 0 && (
              <div className="saved-row">
                <span className="saved-label">saved runs</span>
                {saved.map((row) => (
                  <button
                    key={row.id}
                    className="ask-link"
                    disabled={busy}
                    onClick={() => void loadSaved(row.id)}
                    title={`${row.question} · ${row.moments} moments · ${new Date(row.saved).toLocaleString()}`}
                  >
                    {row.answered ? row.question : `${row.question} (no answer)`}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="camera-strip">
            <span className="strip-label">camera</span>
            <span className="strip-mode">{eraSpan ? `era · ${eraSpan}` : "era"}</span>
            <span className="strip-sep" />
            <span className="strip-state" data-on={autoFollow}>
              {autoFollow ? "following reel" : "manual orbit"}
            </span>
            {!autoFollow && (
              <button className="ask-link" onClick={() => setAutoFollow(true)}>
                resume
              </button>
            )}
          </div>

          {/* Navigation lives at the bottom left rather than in the top bar: the top bar already
              carries the masthead and the question, and three clusters at that width collided. */}
          <div className="nav-strip">
            <button className="ask-link" onClick={resetView}>
              system view
            </button>
            <span className="strip-sep" />
            <span className="strip-keys">
              <kbd>W</kbd><kbd>A</kbd><kbd>S</kbd><kbd>D</kbd> fly · <kbd>R</kbd>/<kbd>F</kbd> up, down ·
              drag to orbit · click a body
            </span>
            <span className="strip-sep" />
            <button className="ask-link" onClick={() => setHud(false)}>
              hide notes <kbd>H</kbd>
            </button>
          </div>

          {result && (
            <>
              <div className="column left">
                <section className="sheet" ref={answerRef}>
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

                <section className="sheet key">
                  <h2>Where each date came from</h2>
                  <ul className="keylist">
                    <li>
                      <i className="swatch scene" />
                      <b>stated in the scene</b>
                      <span>spoken or on screen in that shot</span>
                    </li>
                    <li>
                      <i className="swatch video" />
                      <b>from clip context</b>
                      <span>the clip is about that year, the shot does not say so</span>
                    </li>
                    <li>
                      <i className="swatch published" />
                      <b>upload date only</b>
                      <span>weakest: when NASA posted the file, not when it happened</span>
                    </li>
                  </ul>
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
