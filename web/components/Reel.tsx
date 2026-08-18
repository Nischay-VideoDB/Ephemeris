"use client";

import { useEffect, useRef, useState } from "react";
import type { Reel as ReelData } from "@/lib/types";
import { evidenceIndexOfShot, shotIndexAt } from "@/lib/reel";
import { useStore } from "@/lib/store";

/** HLS playback. Safari plays .m3u8 natively; everywhere else needs hls.js, which is
 *  imported dynamically so it never runs during server rendering. */
export function Reel({ reel }: { reel?: ReelData }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const { activeEvidenceIndex, setActiveEvidenceIndex, seekTarget, setSeekTarget, setEngaged, selectMoment } =
    useStore();
  const [ready, setReady] = useState(false);
  // A stream that dies mid-playback is reported rather than left as a frozen frame.
  const [streamError, setStreamError] = useState<string | null>(null);

  const url = reel?.stream_url ?? null;

  useEffect(() => setStreamError(null), [url]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video || !url) return;

    let destroy: (() => void) | undefined;

    if (video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = url;
      setReady(true);
    } else {
      let cancelled = false;
      import("hls.js").then(({ default: Hls }) => {
        if (cancelled || !Hls.isSupported()) return;
        const hls = new Hls({ enableWorker: true });
        hls.loadSource(url);
        hls.attachMedia(video);
        hls.on(Hls.Events.MANIFEST_PARSED, () => setReady(true));

        // hls.js does not recover on its own. Only MANIFEST_PARSED was handled here, so any
        // fatal error left the element sitting at the second it failed with nothing logged and
        // nothing shown: a reel stopped dead at 11s every time it was played and looked like a
        // hang. A network error needs the loader restarted, a media error needs the decoder
        // flushed, and each is worth exactly one attempt before saying so out loud.
        let recovered = { network: false, media: false };
        hls.on(Hls.Events.ERROR, (_event, data) => {
          if (!data.fatal) return;
          if (data.type === Hls.ErrorTypes.NETWORK_ERROR && !recovered.network) {
            recovered.network = true;
            hls.startLoad();
          } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR && !recovered.media) {
            recovered.media = true;
            hls.recoverMediaError();
          } else {
            hls.destroy();
            setStreamError(
              `playback stopped at ${video.currentTime.toFixed(0)}s (${data.details}). ` +
              "The compiled reel is still playable at its VideoDB link.",
            );
          }
        });
        destroy = () => hls.destroy();
      });
      return () => {
        cancelled = true;
        destroy?.();
      };
    }
    return () => destroy?.();
  }, [url]);

  // Keep the selection in step with playback so the burned-in caption, the highlighted row
  // and the camera always agree. What is published is the *evidence* index the playing shot
  // belongs to, which is not its position in the shot list once a moment has been dropped.
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !reel?.shots?.length) return;
    const onTime = () => {
      const shotIndex = Math.max(0, shotIndexAt(reel, video.currentTime));
      const index = evidenceIndexOfShot(reel.shots[shotIndex], shotIndex);
      if (useStore.getState().activeEvidenceIndex !== index) {
        setActiveEvidenceIndex(index);
      }
    };
    // Pressing play is what hands the camera over to the reel; before that it holds the wide shot.
    const onPlay = () => setEngaged(true);
    // The element can fail where hls.js reports nothing: a segment that decodes as garbage
    // surfaces here as a MediaError and nowhere else, which is how a reel came to sit frozen
    // mid-shot with an apparently healthy player around it.
    const onError = () => {
      const code = video.error?.code;
      if (code) {
        setStreamError(
          `playback stopped at ${video.currentTime.toFixed(0)}s: the compiled stream has a ` +
          "segment this browser cannot decode. The other shots are still listed below.",
        );
      }
    };
    video.addEventListener("timeupdate", onTime);
    video.addEventListener("play", onPlay);
    video.addEventListener("error", onError);
    return () => {
      video.removeEventListener("timeupdate", onTime);
      video.removeEventListener("play", onPlay);
      video.removeEventListener("error", onError);
    };
  }, [reel, setActiveEvidenceIndex, setEngaged]);

  useEffect(() => {
    if (seekTarget !== null && videoRef.current) {
      videoRef.current.currentTime = seekTarget + 0.05;
      // play() rejects with NotAllowedError when the browser has no user gesture to attribute
      // playback to, which happens whenever a moment is selected from code rather than from a
      // click on the player. The seek itself still lands, so the refusal is nothing to report:
      // left unhandled it surfaced as an uncaught rejection and a dev-overlay issue badge.
      void videoRef.current.play().catch(() => {});
      setSeekTarget(null);
    }
  }, [seekTarget, setSeekTarget]);

  function seekLocal(shotIndex: number, seconds: number) {
    selectMoment(evidenceIndexOfShot(reel?.shots?.[shotIndex], shotIndex), seconds);
  }

  if (!url) {
    return (
      <section className="panel">
        <h2>Evidence reel</h2>
        <div className="err">
          {/* A run that was refused before retrieval has nothing to cut, which is an outcome
              rather than a failure: reporting it as one reads like the compiler crashed. */}
          {reel?.error === "no evidence to compile"
            ? "No reel: nothing in the archive matched, so there was no footage to cut."
            : reel?.error
              ? "Live research completed with timestamped evidence, but this borrowed read-only corpus cannot compile a new reel under the public account. Play any NASA source below, or open a prepared journey for a compiled reel."
              : "No reel for this answer."}
        </div>
      </section>
    );
  }

  return (
    <section className="panel">
      {/* The player is pinned to the top of the rail: the shot list and the notes scroll under it,
          so the reel stays on screen while the evidence below it is read. */}
      <div className="player">
        <video ref={videoRef} controls playsInline preload="metadata" />
        {!ready && !streamError && <div className="spinner">loading stream…</div>}
        {streamError && <div className="err stream-err">{streamError}</div>}
      </div>

      <div className="shotlist">
        {reel?.shots.map((shot, i) => (
          <div
            key={`${shot.nasa_id}-${shot.at}`}
            className="shot"
            data-active={evidenceIndexOfShot(shot, i) === activeEvidenceIndex}
            onClick={() => seekLocal(i, shot.at)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === "Enter" && seekLocal(i, shot.at)}
          >
            <span className="t">
              {String(Math.floor(shot.at / 60)).padStart(2, "0")}:
              {String(shot.at % 60).padStart(2, "0")}
            </span>
            {/* The number is burned into the frame too, so it is stripped from the caption here
                rather than shown twice. Older answers carry no number in theirs. */}
            <span>
              [{evidenceIndexOfShot(shot, i) + 1}] {shot.caption.replace(/^\[\d+\]\s*/, "")}
            </span>
          </div>
        ))}
      </div>

      <p className="note" style={{ marginTop: 8, marginBottom: 0 }}>
        {reel?.shots.length ?? 0} shots{reel?.total_seconds ? `, ${Math.round(reel.total_seconds)}s` : ""}. Provenance is
        burned into the frame, so it survives an export.
        {reel?.dropped?.length
          ? ` ${reel.dropped.length} moment${reel.dropped.length > 1 ? "s" : ""} could not be cut from
             ${reel.dropped.length > 1 ? "their sources" : "its source"} and ${
              reel.dropped.length > 1 ? "are" : "is"
            } marked in the scene instead.`
          : ""}
      </p>
    </section>
  );
}
