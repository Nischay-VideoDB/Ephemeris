"""Index construction.

Six indexes, two of them built from the *same* VLM artifact. Understanding and
indexing are separate stages, so one analyzer run can back several indexes with
different capabilities: one tuned for vector search over prose, one for exact
filtering and counting over enums. One model pass, two retrieval surfaces, no
extra inference cost.

Field names here are the ones observed live in docs/field-schema.md, not the ones
the reference docs claim.
"""

from __future__ import annotations

from schema import VLM_SCHEMA

# Index names are a schema contract across a collection: reuse a name on every
# video and retrieval fans out over all of them, but indexes sharing a name must
# have identical field structure or creation fails. Bump the suffix when the
# schema changes rather than fighting a mismatch.
TRANSCRIPT = "transcript"
SCENE_SEMANTIC = "scene_semantic"
SCENE_FACETS = "scene_facets"
OCR = "ocr"
OBJECTS = "objects"
MISSION_META = "mission_meta"

FACET_FIELDS = ["celestial_body", "event_type", "evidence_shown", "mission_ref", "era_basis"]

META_FILTER_FIELDS = [
    "nasa_id", "center", "published_year", "primary_mission",
    "era_start", "era_basis", "era_axis", "water_relevance",
    "celestial_body", "event_type",
]

# `era_start` has to be aggregatable, not just filterable and sortable: the decade
# histogram behind the timeline view is an aggregate over it. Its default derivation
# put a number field in filter+sort only, which silently made that query impossible.
META_AGGREGATE_FIELDS = [
    "center", "published_year", "primary_mission", "era_start", "era_basis",
    "era_axis", "water_relevance", "celestial_body", "event_type",
]


def build_transcript_index(video, analyzer):
    """Spoken words. `text` also gets full-text search applied automatically."""
    return video.index(
        source=analyzer,
        name=TRANSCRIPT,
        use_for=["semantic"],
        fields={"semantic": ["text"]},
    )


def build_scene_semantic_index(video, analyzer):
    """Prose half of the VLM artifact: what the scene looks like."""
    return video.index(
        source=analyzer,
        name=SCENE_SEMANTIC,
        use_for=["semantic"],
        fields={"semantic": ["scene_description", "on_screen_text"]},
    )


def build_scene_facets_index(video, analyzer):
    """Structured half of the *same* VLM artifact: what the scene is.

    Enums are what make this worth having. Counting or filtering on free prose
    produces one bucket per scene; counting on a constrained vocabulary produces
    an answer.
    """
    return video.index(
        source=analyzer,
        name=SCENE_FACETS,
        use_for=["query", "aggregate"],
        fields={
            "filter": FACET_FIELDS + ["era_year"],
            "aggregate": FACET_FIELDS,
            "sort": ["era_year"],
        },
    )


def build_ocr_index(video, analyzer):
    """On-screen text: mission clocks, dates, chart labels, lower thirds.

    `use_for` is omitted deliberately. Many scenes carry no on-screen text at all,
    and an artifact with no embeddable text degrades gracefully to query+aggregate
    when `use_for` is omitted, but raises "use_for includes semantic but no scene
    has embeddable text" if semantic is requested explicitly. Omitting is
    forgiving; requesting is strict.
    """
    return video.index(source=analyzer, name=OCR, fields={"semantic": ["text"]})


def build_objects_index(video, analyzer):
    """Sandbox-only analyzer. Field paths are unverified until a sandbox run happens."""
    return video.index(
        source=analyzer,
        name=OBJECTS,
        use_for=["query", "aggregate"],
    )


def build_mission_meta_index(video, records: list[dict]):
    """Provenance and the dual time axis, indexed without an understanding run.

    `video.index()` accepts raw temporal records, so NASA's own metadata becomes a
    first-class index. That puts publication year, extracted era, and mission on
    the server as filterable, sortable, aggregatable fields, which is what makes
    chronological reasoning a VideoDB operation rather than a sort in our process.
    """
    return video.index(
        source=records,
        name=MISSION_META,
        use_for=["query", "aggregate"],
        fields={
            "filter": META_FILTER_FIELDS,
            "aggregate": META_AGGREGATE_FIELDS,
            "sort": ["published_year", "era_start"],
        },
    )


def wait_all(indexes: list, timeout: int = 1800) -> list:
    for index in indexes:
        if index is not None:
            index.wait_until_complete(timeout=timeout)
    return indexes


def describe(index) -> dict:
    return {
        "name": index.name,
        "status": index.status,
        "use_for": list(index.use_for or []),
        "record_count": index.record_count,
        "fields": dict(index.fields or {}),
        "error": index.error,
    }


def schema_keys() -> list[str]:
    return list(VLM_SCHEMA.keys())
