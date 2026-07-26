"use client";

import type { Answer as AnswerData } from "@/lib/types";

/** Turn inline [n] markers into buttons that scroll to the evidence they cite. */
function withCitations(text: string, onCite: (n: number) => void) {
  const parts = text.split(/(\[\d+\])/g);
  return parts.map((part, i) => {
    const match = /^\[(\d+)\]$/.exec(part);
    if (!match) return <span key={i}>{part}</span>;
    const n = Number(match[1]);
    return (
      <button key={i} className="cite" onClick={() => onCite(n)} title={`Jump to evidence ${n}`}>
        {n}
      </button>
    );
  });
}

export function Answer({
  answer,
  onCite,
}: {
  answer: AnswerData;
  onCite: (n: number) => void;
}) {
  if (!answer.answer) {
    return (
      <section className="panel">
        <h2>Answer</h2>
        <div className="err">
          No evidence cleared the relevance threshold, so no answer was produced.
        </div>
      </section>
    );
  }

  return (
    <section className="panel">
      <div className="answer">{withCitations(answer.answer, onCite)}</div>

      {answer.chronology?.length > 0 && (
        <>
          <h2>Chronology</h2>
          <div className="chrono">
            {answer.chronology.map((point, i) => (
              <div className="chrono-row" key={i}>
                <span className="chrono-era">{point.era}</span>
                <span>
                  {point.claim}{" "}
                  {point.citations?.map((n) => (
                    <button key={n} className="cite" onClick={() => onCite(n)}>
                      {n}
                    </button>
                  ))}
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      {answer.caveats && <div className="caveats">{answer.caveats}</div>}
    </section>
  );
}
