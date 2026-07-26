"use client";

import { useEffect, useRef, useState } from "react";
import type { Reel as ReelData } from "@/lib/types";
import { useStore } from "@/lib/store";

/** HLS playback. Safari plays .m3u8 natively; everywhere else needs hls.js, which is
 *  imported dynamically so it never runs during server rendering. */
export function Reel({ reel }: { reel?: ReelData }) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const { activeShotIndex, setActiveShotIndex, seekTarget, setSeekTarget, setEngaged, selectShot } = useStore();
  const [ready, setReady] = useState(false);

  const url = reel?.stream_url ?? null;

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
        destroy = () => hls.destroy();
      });
      return () => {
        cancelled = true;
        destroy?.();
      };
    }
    return () => destroy?.();
  }, [url]);

  // Keep the shot list in step with playback so the burned-in caption and the
  // highlighted row always agree.
  useEffect(() => {
    const video = videoRef.current;
    if (!video || !reel?.shots?.length) return;
    const onTime = () => {
      const t = video.currentTime;
      let index = 0;
      reel.shots.forEach((shot, i) => {
        if (t >= shot.at) index = i;
      });
      if (useStore.getState().activeShotIndex !== index) {
        setActiveShotIndex(index);
      }
    };
    // Pressing play is what hands the camera over to the reel; before that it holds the wide shot.
    const onPlay = () => setEngaged(true);
    video.addEventListener("timeupdate", onTime);
    video.addEventListener("play", onPlay);
    return () => {
      video.removeEventListener("timeupdate", onTime);
      video.removeEventListener("play", onPlay);
    };
  }, [reel, setActiveShotIndex, setEngaged]);

  useEffect(() => {
    if (seekTarget !== null && videoRef.current) {
      videoRef.current.currentTime = seekTarget + 0.05;
      void videoRef.current.play();
      setSeekTarget(null);
    }
  }, [seekTarget, setSeekTarget]);

  function seekLocal(index: number, seconds: number) {
    selectShot(index, seconds);
  }

  if (!url) {
    return (
      <section className="panel">
        <h2>Evidence reel</h2>
        <div className="err">
          {reel?.error ? `Could not compile: ${reel.error}` : "No reel for this answer."}
        </div>
      </section>
    );
  }

  return (
    <section className="panel">
      <video ref={videoRef} controls playsInline preload="metadata" />
      {!ready && <div className="spinner" style={{ marginTop: 8 }}>loading stream…</div>}

      <div className="shotlist">
        {reel?.shots.map((shot, i) => (
          <div
            key={`${shot.nasa_id}-${shot.at}`}
            className="shot"
            data-active={i === activeShotIndex}
            onClick={() => seekLocal(i, shot.at)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === "Enter" && seekLocal(i, shot.at)}
          >
            <span className="t">
              {String(Math.floor(shot.at / 60)).padStart(2, "0")}:
              {String(shot.at % 60).padStart(2, "0")}
            </span>
            <span>{shot.caption}</span>
          </div>
        ))}
      </div>

      <p className="note" style={{ marginTop: 8, marginBottom: 0 }}>
        {reel?.shots.length ?? 0} shots{reel?.total_seconds ? `, ${Math.round(reel.total_seconds)}s` : ""}. Provenance is
        burned into the frame, so it survives an export.
      </p>
    </section>
  );
}
