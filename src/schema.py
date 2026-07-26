"""The VLM output contract.

Enums are the point. Free-text scene descriptions can only be searched
semantically; declared enum fields can additionally be filtered with `query()`
and counted with `aggregate()`, and they produce clean buckets instead of a
thousand distinct prose strings.

`mission_ref` and `era_year` implement the second time axis. NASA's video library
holds essentially nothing published before 2000, so a chronology built from
publication dates alone cannot express "how understanding changed" across earlier
missions. The publication date is reliable and comes from the NASA API; the era is
extracted here and carries a confidence, and the agent says which axis it used.
"""

from __future__ import annotations

# The corpus expansion broke the original Mars-era list: a Titan landing was forced to
# choose between "moon", "deep_space" and "unknown", and picked all three across one clip.
# Outer-planet values are worth their place because the interface positions evidence by
# this field, and a body it cannot name becomes an unplaced marker.
CELESTIAL_BODIES = [
    "mars", "moon", "earth", "earth_orbit", "sun",
    "venus", "mercury", "jupiter", "saturn", "titan",
    "comet_asteroid", "deep_space", "ground", "unknown",
]

EVENT_TYPES = [
    "launch", "landing", "surface_ops", "instrument_readout", "briefing",
    "data_visualization", "animation", "eva", "other",
]

EVIDENCE_KINDS = [
    "surface_imagery", "data_visualization", "instrument", "model_animation", "none",
]

# How the era was arrived at. This exists instead of a numeric confidence because
# it is checkable: a claim sourced to spoken words or on-screen text can be
# verified against the transcript and OCR indexes, while a bare 0.82 cannot. The
# agent shows this basis in its trace and refuses to order on `not_determinable`.
ERA_BASES = [
    "stated_in_speech", "on_screen_text", "inferred_from_mission", "not_determinable",
]

# Every field is required with an explicit sentinel. Reconnaissance showed that
# `required: False` fields the model chooses to omit are absent from scene data
# entirely, and a field absent from the data cannot be indexed or filtered at all
# ("fields.filter names not present in any scene's data"). A declared "unknown" is
# indexable; a missing field is not.
VLM_SCHEMA: dict = {
    "scene_description": "text",
    "celestial_body": {"type": "enum", "values": CELESTIAL_BODIES},
    "event_type": {"type": "enum", "values": EVENT_TYPES},
    "evidence_shown": {"type": "enum", "values": EVIDENCE_KINDS},
    "mission_ref": {
        "type": "string",
        "description": (
            "NASA mission named in speech, printed on screen, or clearly depicted. "
            "Use exactly 'unknown' if no mission can be identified."
        ),
    },
    "era_year": {
        "type": "number",
        "description": (
            "Year of the events or scientific findings discussed in this scene, not "
            "the year the video was published. Use 0 if the scene is not tied to a "
            "specific year."
        ),
    },
    "era_basis": {"type": "enum", "values": ERA_BASES},
    "on_screen_text": "text",
}

# Naming the searchable dimensions in the prompt beats raising the frame count:
# VideoDB's own accuracy guidance is that prompt specificity matters more than
# how many frames the model sees.
def vlm_prompt(with_ocr: bool = True) -> str:
    """The scene-classification prompt.

    `with_ocr` is False for clips analysed without the OCR analyzer. The OCR analyzer
    is billed against a managed tier that the hackathon account has exhausted, so later
    clips read on-screen text out of the frames themselves into `on_screen_text` rather
    than receiving it as a separate input. Interpolating `{{inputs.ocr}}` when no such
    input exists would leave the placeholder in the prompt verbatim.
    """
    body_rule = (
        "- celestial_body: the body the footage concerns, not where the camera is. "
        "Judge it from what the frames actually show, colour, atmosphere, terrain, "
        "and from what is said. This archive spans the whole solar system, so do not "
        "assume Mars: grey cratered airless terrain is the Moon, rust-orange terrain "
        "with a thin sky is Mars, blue-and-white cloud cover is Earth, banded cloud "
        "tops are Jupiter, a ringed globe is Saturn, hazy orange is Titan. Use "
        "comet_asteroid for small bodies and deep_space for stars, galaxies and "
        "telescope imagery of anything outside the solar system.\n"
    )
    prompt = (
        "This is archival NASA footage from a public science and mission archive.\n\n"
        "Describe what is visible in this scene, using the frames as primary evidence. "
        "Be concrete about surfaces, instruments, spacecraft, terrain, and any charts or "
        "imagery shown on screen.\n\n"
        "Then classify the scene:\n"
        + body_rule +
        "- event_type: what is happening.\n"
        "- evidence_shown: the form any scientific evidence takes on screen.\n"
        "- mission_ref: a NASA mission named in speech, printed on screen, or clearly "
        "depicted. Write exactly 'unknown' rather than guessing.\n"
        "- era_year: the year of the events or findings this scene discusses, which is "
        "often much earlier than the year the video was made. Write 0 if the scene is "
        "not tied to a specific year. Do not guess a year to fill the field.\n"
        "- era_basis: how you determined era_year. Use 'not_determinable' whenever "
        "era_year is 0.\n"
        "- on_screen_text: any burned-in captions, mission clocks, dates, or data readouts. "
        "Write an empty string if there is none.\n\n"
        "Spoken words in this scene:\n{{inputs.transcript}}"
    )
    if with_ocr:
        prompt += "\n\nText detected on screen in this scene:\n{{inputs.ocr}}"
    return prompt


VLM_PROMPT = vlm_prompt(with_ocr=True)

# Frames per scene by clip character. Static talking-head footage gains little from
# extra frames; action and graphics-heavy footage needs several.
SAMPLING_BY_PROFILE = {
    "briefing": {"strategy": "uniform", "frame_count": 2},
    "visual": {"strategy": "uniform", "frame_count": 5},
}
