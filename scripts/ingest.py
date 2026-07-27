"""Upload curated NASA clips into the project collection.

Idempotent: an entry already carrying a video_id is skipped, so re-running after
a partial failure costs nothing.

`profile` drives per-clip sampling later in the understanding pipeline. NASA's
accuracy guidance is that static talking-head footage wants roughly one frame per
scene while action footage wants three to five, and sampling is per-analyzer, so
this is a config choice rather than extra work.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import manifest  # noqa: E402
import nasa  # noqa: E402
import videodb_client as vc  # noqa: E402

# The corpus is chosen for historical reach, not for volume. The first quality gate
# showed 49 of 58 scenes falling back to publication year because the archive's
# video holdings start around 2004, so "how understanding changed" had nothing older
# than 2004 to reason over. Candidates were ranked by scripts/discover.py on early
# mission names, retrospective phrasing, and years cited well before upload date.
#
# The first four entries were the original failure-mode slice and are kept.
CLIPS = [
    # --- original slice, kept for failure-mode coverage ---
    {
        "nasa_id": "GSFC_20150305_Mars_m11796_Ocean",
        "profile": "visual",
        "note": "Narrated science explainer. References findings from earlier missions, "
                "so it is the main test of era extraction versus publication date.",
    },
    {
        "nasa_id": "JPL-20240710-Perseverance_Rover_Spots_an_Unusual_Rock_in_Ancient_River_Channel_Mars_Report",
        "profile": "visual",
        "note": "Modern field report, heavy on-screen graphics. Tests OCR and visual retrieval.",
    },
    {
        "nasa_id": "ksc_080407_phx_intro0",
        "profile": "briefing",
        "note": "2007 Phoenix pre-launch briefing. Talking head, weak visuals. "
                "Tests whether scene retrieval degrades where narration carries everything.",
    },
    {
        "nasa_id": "ksc_102504_marsdrill",
        "profile": "briefing",
        "note": "Short 2004 Mars drill demo. Already uploaded by scripts/recon.py.",
    },

    # --- historical anchors: the whole point of the expansion ---
    {
        "nasa_id": "JPL-20250710-MARINRs-0001-Mariner_4_Media_Reel",
        "profile": "visual",
        "note": "Mariner 4 60th anniversary reel. The 1965 flyby returned the first close-up "
                "images of Mars and showed a cratered, apparently dry world. This is the "
                "earliest anchor of the water narrative and the oldest era in the corpus.",
    },
    {
        "nasa_id": "1971 Aeronautics and Space Highlights",
        "profile": "visual",
        "note": "1971 highlights including Mariner 9 orbiting Mars, the mission that "
                "photographed dry channels and reopened the water question.",
    },
    {
        "nasa_id": "ksc_020105_why_jpl",
        "profile": "briefing",
        "note": "JPL institutional history reaching back to the 1930s, citing 1957, 1958, "
                "1975 and 1976. Names Viking directly.",
    },
    {
        "nasa_id": "ksc_080805_mro_smrekar9",
        "profile": "briefing",
        "note": "MRO scientist Q&A about imaging the Viking, Pathfinder and MER landing "
                "sites. Explicitly retrospective across four mission eras.",
    },

    # --- the 2001-2008 middle era, which the archive covers in depth ---
    {
        "nasa_id": "ksc_091704_odyssey",
        "profile": "briefing",
        "note": "Mars Odyssey mission extension. Launched 2001, mapped chemical composition "
                "and hydrogen signatures that implied subsurface ice.",
    },
    {
        "nasa_id": "ksc_122104_spirit_anniv",
        "profile": "briefing",
        "note": "Spirit's first landing anniversary, described as searching for signs of a "
                "watery history. Anchors the 2004 MER era.",
    },
    {
        "nasa_id": "ksc_042104_meteor",
        "profile": "briefing",
        "note": "Opportunity at Meridiani Planum analysing the rock Bounce with Mini-TES and "
                "Moessbauer spectrometers. Instrument-level water evidence.",
    },
    {
        "nasa_id": "ksc_062904_mars",
        "profile": "briefing",
        "note": "Spirit in the Columbia Hills examining Pot of Gold. Surface operations "
                "counterpart to the orbital evidence.",
    },
    {
        "nasa_id": "ksc_012805_mars_recon",
        "profile": "briefing",
        "note": "Two-year MER anniversary framing the upcoming MRO launch. Bridges the 2004 "
                "and 2006 eras in one clip.",
    },
    {
        "nasa_id": "ksc_080805_mro_zurek",
        "profile": "briefing",
        "note": "MRO project scientist with cruise and orbit insertion animation.",
    },
    {
        "nasa_id": "ksc_080407_phx_launch",
        "profile": "visual",
        "note": "Phoenix launch itself, 2007. Phoenix later confirmed water ice directly, "
                "making this the pivot from inference to confirmation.",
    },

    # --- modern era, to close the arc ---
    {
        "nasa_id": "JPL-20230208-MSLf-0001-Curiosity_Finds_New_Clues_to_Mars_Watery_Past",
        "profile": "visual",
        "note": "Curiosity evidence for ancient lakes. Modern in-situ sedimentary evidence.",
    },
    {
        "nasa_id": "JPL-20230607-MARSf-0001-Mars Report Whats in A Name",
        "profile": "visual",
        "note": "Names eight missions across the whole programme history in one clip, which "
                "is unusually dense mission_ref material.",
    },
    {
        "nasa_id": "GSFC_20130613_MAVEN_m11295_IUVS",
        "profile": "visual",
        "note": "MAVEN's ultraviolet spectrograph, built to measure atmospheric escape and "
                "therefore how Mars lost its water.",
    },
    {
        "nasa_id": "GSFC_20180608_Tonga_m12932_Volcanoes",
        "profile": "visual",
        "note": "Terrestrial analogue study of how water affected Martian volcanoes. Tests "
                "whether the pipeline correctly labels Earth footage used to reason about Mars.",
    },
]


SELECTION_PATH = Path(__file__).resolve().parent.parent / "data" / "selection.json"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_clips(from_selection: bool) -> list[dict]:
    """The hand-written CLIPS list is the curated core and stays. A selection file,
    produced by scripts/select.py, adds domain coverage on top of it."""
    if not from_selection:
        return CLIPS

    import json

    chosen = json.loads(SELECTION_PATH.read_text())["selection"]
    log(f"selection holds {len(chosen)} clips")
    return CLIPS + [
        {
            "nasa_id": c["nasa_id"],
            "profile": c["profile"],
            "note": c["note"],
            "domain": c.get("domain"),
        }
        for c in chosen
    ]


def main() -> None:
    from_selection = "--from-selection" in sys.argv[1:]
    coll = vc.get_collection()

    # A public collection is readable by any key that knows its id, so the corpus can be
    # queried without re-ingesting 240 minutes of video. Read-only for everyone else: uploads
    # and indexing still belong to the owning account. Checked rather than set unconditionally,
    # since flipping visibility on every run would be a write nobody asked for.
    if not coll.is_public:
        log("collection is private; making it public so the corpus can be shared read-only")
        coll.make_public()

    entries = manifest.load()
    clips = load_clips(from_selection)

    # Reconcile with what is actually in the collection, so a manifest deleted or
    # written by another script does not cause a duplicate upload.
    existing = {v.name: v for v in coll.get_videos()}

    for clip in clips:
        nasa_id = clip["nasa_id"]
        entry = entries.get(nasa_id, {})

        if entry.get("video_id"):
            log(f"skip {nasa_id}: already uploaded as {entry['video_id']}")
            continue

        meta = nasa.resolve(nasa_id)
        if not meta["mp4_url"]:
            log(f"SKIP {nasa_id}: no mp4 rendition available")
            continue

        name = meta["title"] or nasa_id
        if name in existing:
            video = existing[name]
            log(f"adopt {nasa_id}: found existing video {video.id} named {name!r}")
        else:
            status, size = nasa.probe_size(meta["mp4_url"])
            log(f"upload {nasa_id} ({size / 1e6:.1f}MB, HTTP {status})")
            video = coll.upload(url=meta["mp4_url"], name=name, description=meta["description"][:500])
            log(f"  -> {video.id}, {video.length}s")

        manifest.put(
            nasa_id,
            video_id=video.id,
            video_length=float(video.length or 0),
            profile=clip["profile"],
            note=clip["note"],
            domain=clip.get("domain", "mars"),
            title=meta["title"],
            description=meta["description"],
            date_created=meta["date_created"],
            published_year=meta["published_year"],
            center=meta["center"],
            keywords=meta["keywords"],
            mp4_url=meta["mp4_url"],
            vtt_url=meta["vtt_url"],
            thumb_url=meta["thumb_url"],
        )
        entries = manifest.load()

    log(f"manifest holds {len(manifest.load())} clips")
    total = sum(e.get("video_length", 0) for e in manifest.load().values())
    log(f"total footage: {total / 60:.1f} minutes")


if __name__ == "__main__":
    main()
