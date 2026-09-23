"""Visual-token cost of images — the thing base64 length badly misrepresents."""

import base64
import struct

import pytest

from acco.images import cost_from_base64, dimensions, visual_tokens


def _png(width, height):
    header = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", width, height)
    return header + b"\x08\x06\x00\x00\x00" + b"\x00" * 64


@pytest.mark.parametrize(
    "width,height,expected",
    [
        (200, 200, 64),
        (1000, 1000, 1296),
        (1092, 1092, 1521),
        (1920, 1080, 2691),
        (2000, 1500, 3888),
        (3840, 2160, 4784),
    ],
)
def test_matches_the_published_high_resolution_table(width, height, expected):
    assert visual_tokens(width, height, high_res=True) == expected


def test_cost_is_hard_capped():
    """A single image can never cost what its base64 length suggests."""
    assert visual_tokens(8000, 8000, high_res=True) <= 4784
    assert visual_tokens(8000, 8000, high_res=False) <= 1568


def test_standard_tier_is_smaller_than_high_res():
    assert visual_tokens(3840, 2160, False) < visual_tokens(3840, 2160, True)


def test_degenerate_sizes():
    assert visual_tokens(0, 100) == 0
    assert visual_tokens(-5, 10) == 0
    assert visual_tokens(1, 1) == 1


def test_png_dimensions_are_read_from_the_header():
    assert dimensions(_png(1456, 816)) == (1456, 816, "png")


def test_gif_dimensions():
    data = b"GIF89a" + struct.pack("<HH", 640, 480) + b"\x00" * 32
    assert dimensions(data) == (640, 480, "gif")


def test_jpeg_dimensions():
    data = (
        b"\xff\xd8"
        + b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
        + b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", 768, 1024)
        + b"\x03" + b"\x00" * 9
    )
    assert dimensions(data) == (1024, 768, "jpeg")


def test_unrecognised_data():
    assert dimensions(b"not an image at all, really not") is None
    assert dimensions(b"tiny") is None


def test_cost_from_base64_reads_only_the_header():
    """A 5MB screenshot must not need 5MB of decoding to be measured."""
    payload = base64.b64encode(_png(1456, 816) + b"\x00" * 5_000_000).decode()
    cost = cost_from_base64(payload)
    assert cost is not None
    assert (cost.width, cost.height) == (1456, 816)
    assert cost.tokens == visual_tokens(1456, 816)


def test_base64_length_does_not_drive_the_cost():
    """Regression: 570KB of base64 was reported as 162,876 tokens."""
    small = base64.b64encode(_png(1456, 816) + b"\x00" * 10_000).decode()
    huge = base64.b64encode(_png(1456, 816) + b"\x00" * 4_000_000).decode()
    assert cost_from_base64(small).tokens == cost_from_base64(huge).tokens
    assert cost_from_base64(huge).tokens < 4784


def test_garbage_base64_is_handled():
    assert cost_from_base64("!!!!not base64!!!!") is None
    assert cost_from_base64("") is None
