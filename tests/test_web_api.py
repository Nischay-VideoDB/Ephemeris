import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web.api.index import _browser_safe_url


def test_browser_safe_url_encodes_nasa_path_text_without_double_encoding():
    raw = (
        "https://images-assets.nasa.gov/video/"
        "1971 Aeronautics and Space Highlights/"
        "1971 Aeronautics and Space Highlights~orig.mp4"
    )

    encoded = _browser_safe_url(raw)

    assert " " not in encoded
    assert "%20" in encoded
    assert _browser_safe_url(encoded) == encoded
