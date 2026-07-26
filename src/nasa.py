"""NASA Image and Video Library client.

Public domain footage, no auth required. https://images-api.nasa.gov
"""

from __future__ import annotations

from typing import Any, Iterator

import requests

SEARCH_URL = "https://images-api.nasa.gov/search"
ASSET_URL = "https://images-api.nasa.gov/asset/{nasa_id}"

# Preference order for the video rendition we upload to VideoDB. `~orig` is often
# a multi-hundred-MB .mov, which costs upload time and buys nothing: analyzers
# downsample anyway, and the pipeline applies a 480p transform.
MP4_PREFERENCE = ("~medium.mp4", "~small.mp4", "~mobile.mp4", "~preview.mp4")

TIMEOUT = 30


class NasaError(RuntimeError):
    pass


def _get(url: str, params: dict[str, Any] | None = None) -> dict:
    response = requests.get(url, params=params, timeout=TIMEOUT)
    if not response.ok:
        raise NasaError(f"{response.status_code} from {response.url}: {response.text[:200]}")
    return response.json()


def _https(url: str) -> str:
    """Asset manifests return http:// links. The CDN serves https fine."""
    return url.replace("http://", "https://", 1)


def search(
    query: str,
    *,
    media_type: str = "video",
    page_size: int = 20,
    page: int = 1,
    year_start: int | None = None,
    year_end: int | None = None,
    keywords: str | None = None,
) -> list[dict]:
    """Search the library. Returns normalized metadata without asset URLs.

    Note `date_created` is the publication date, not the era the footage depicts.
    The library holds essentially nothing before 2000, which is why the pipeline
    carries a second, extracted time axis.
    """
    params: dict[str, Any] = {
        "q": query,
        "media_type": media_type,
        "page_size": page_size,
        "page": page,
    }
    if year_start is not None:
        params["year_start"] = year_start
    if year_end is not None:
        params["year_end"] = year_end
    if keywords is not None:
        params["keywords"] = keywords

    payload = _get(SEARCH_URL, params)
    items = payload.get("collection", {}).get("items", [])
    return [_normalize_item(item) for item in items]


def total_hits(query: str, *, media_type: str = "video") -> int:
    payload = _get(SEARCH_URL, {"q": query, "media_type": media_type, "page_size": 1})
    return payload.get("collection", {}).get("metadata", {}).get("total_hits", 0)


def _normalize_item(item: dict) -> dict:
    data = (item.get("data") or [{}])[0]
    created = data.get("date_created", "") or ""
    return {
        "nasa_id": data.get("nasa_id"),
        "title": (data.get("title") or "").strip(),
        "description": (data.get("description") or "").strip(),
        "date_created": created,
        "published_year": int(created[:4]) if created[:4].isdigit() else None,
        "center": data.get("center"),
        "keywords": data.get("keywords") or [],
        "media_type": data.get("media_type"),
    }


def assets(nasa_id: str) -> dict:
    """Resolve a nasa_id to playable URLs.

    Returns `mp4_url` (best available rendition), `vtt_url` when NASA published
    captions, and `thumb_url`. The .vtt is worth capturing: it is a
    human-authored transcript, usable as ground truth for eval and as a baseline
    to compare machine transcription against.
    """
    payload = _get(ASSET_URL.format(nasa_id=nasa_id))
    hrefs = [_https(i["href"]) for i in payload.get("collection", {}).get("items", [])]

    mp4_url = None
    for suffix in MP4_PREFERENCE:
        mp4_url = next((h for h in hrefs if h.endswith(suffix)), None)
        if mp4_url:
            break
    if mp4_url is None:
        mp4_url = next((h for h in hrefs if h.endswith(".mp4")), None)

    return {
        "nasa_id": nasa_id,
        "mp4_url": mp4_url,
        "vtt_url": next((h for h in hrefs if h.endswith(".vtt")), None),
        "thumb_url": next((h for h in hrefs if h.endswith("~thumb.jpg")), None),
        "all_hrefs": hrefs,
    }


def resolve(nasa_id: str) -> dict:
    """Search metadata joined with asset URLs for a single item."""
    matches = search(f'"{nasa_id}"', page_size=20)
    meta = next((m for m in matches if m["nasa_id"] == nasa_id), None)
    if meta is None:
        payload = _get(SEARCH_URL, {"nasa_id": nasa_id, "media_type": "video"})
        items = payload.get("collection", {}).get("items", [])
        if not items:
            raise NasaError(f"nasa_id not found: {nasa_id}")
        meta = _normalize_item(items[0])
    return {**meta, **assets(nasa_id)}


def probe_size(url: str) -> tuple[int, int | None]:
    """HEAD a rendition. Returns (status_code, content_length)."""
    response = requests.head(url, allow_redirects=True, timeout=TIMEOUT)
    length = response.headers.get("content-length")
    return response.status_code, int(length) if length else None


def fetch_vtt(url: str) -> str:
    response = requests.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.text


def vtt_cues(vtt_text: str) -> Iterator[tuple[float, float, str]]:
    """Yield (start, end, text) from a WebVTT file.

    Used to build eval ground truth: NASA's own captions tell us what is said and
    when, without spending an indexing run to find out.
    """
    def to_seconds(stamp: str) -> float:
        stamp = stamp.strip().replace(",", ".")
        parts = stamp.split(":")
        if len(parts) == 2:
            parts = ["0", *parts]
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    block: list[str] = []
    for raw in vtt_text.splitlines() + [""]:
        line = raw.strip()
        if line:
            block.append(line)
            continue
        timing = next((b for b in block if "-->" in b), None)
        if timing:
            start_raw, end_raw = timing.split("-->")[:2]
            text = " ".join(b for b in block if "-->" not in b and b != "WEBVTT")
            if text:
                yield to_seconds(start_raw), to_seconds(end_raw.split()[0]), text
        block = []
