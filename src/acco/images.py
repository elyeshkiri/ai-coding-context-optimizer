"""Real visual-token cost of an image, not the length of its base64.

Claude bills images in 28x28 patches: an image costs
``ceil(width / 28) * ceil(height / 28)`` visual tokens, and oversized images are
downscaled first, so a single image is hard-capped well below what its encoded
size suggests. Counting base64 characters overstates the cost by more than an
order of magnitude, which is exactly the kind of fake number this package exists
to argue against.

Reference: https://platform.claude.com/docs/en/build-with-claude/vision
"""

from __future__ import annotations

import base64
import binascii
import math
import struct
from dataclasses import dataclass

PATCH = 28

# (max long edge px, max visual tokens)
TIER_HIGH_RES = (2576, 4784)   # Claude 4.7 and later
TIER_STANDARD = (1568, 1568)   # everything else


@dataclass
class ImageCost:
    """Represent image cost state and behavior."""
    width: int
    height: int
    tokens: int
    fmt: str


def visual_tokens(width: int, height: int, high_res: bool = True) -> int:
    """Visual tokens for an image, applying the tier's downscale and cap."""
    if width <= 0 or height <= 0:
        return 0
    max_edge, max_tokens = TIER_HIGH_RES if high_res else TIER_STANDARD

    long_edge = max(width, height)
    if long_edge > max_edge:
        scale = max_edge / long_edge
        width = max(1, int(width * scale))
        height = max(1, int(height * scale))

    tokens = math.ceil(width / PATCH) * math.ceil(height / PATCH)
    if tokens > max_tokens:
        # Area-scale until the patch count fits. This matches the published
        # high-resolution table exactly and is within ~0.5% on the standard
        # tier, where the documented resize rounds slightly differently.
        scale = math.sqrt(max_tokens / tokens)
        width = max(1, int(width * scale))
        height = max(1, int(height * scale))
        tokens = math.ceil(width / PATCH) * math.ceil(height / PATCH)
    return min(tokens, max_tokens)


def dimensions(data: bytes) -> tuple[int, int, str] | None:
    """(width, height, format) from an image header, or None if unrecognised."""
    if len(data) < 24:
        return None

    if data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height), "png"

    if data[:6] in (b"GIF87a", b"GIF89a"):
        width, height = struct.unpack("<HH", data[6:10])
        return int(width), int(height), "gif"

    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            width = int.from_bytes(data[24:27], "little") + 1
            height = int.from_bytes(data[27:30], "little") + 1
            return width, height, "webp"
        if chunk == b"VP8 " and len(data) >= 30:
            width = int.from_bytes(data[26:28], "little") & 0x3FFF
            height = int.from_bytes(data[28:30], "little") & 0x3FFF
            return width, height, "webp"
        return None

    if data[:2] == b"\xff\xd8":
        return _jpeg_dimensions(data)

    return None


def _jpeg_dimensions(data: bytes) -> tuple[int, int, str] | None:
    """Walk JPEG segments to the start-of-frame marker that carries the size."""
    index = 2
    end = len(data)
    while index + 9 < end:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        if index + 4 > end:
            return None
        length = struct.unpack(">H", data[index + 2:index + 4])[0]
        # SOF0..SOF15, excluding the non-frame markers DHT/JPG/DAC
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if index + 9 > end:
                return None
            height, width = struct.unpack(">HH", data[index + 5:index + 9])
            return int(width), int(height), "jpeg"
        index += 2 + length
    return None


def cost_from_base64(payload: str, high_res: bool = True,
                     probe_chars: int = 512) -> ImageCost | None:
    """Measure an image without decoding all of it — headers are at the front."""
    head = payload[: max(probe_chars, 64)]
    head = head[: len(head) - (len(head) % 4)]
    try:
        raw = base64.b64decode(head, validate=False)
    except (binascii.Error, ValueError):
        return None
    found = dimensions(raw)
    if not found:
        return None
    width, height, fmt = found
    return ImageCost(width, height, visual_tokens(width, height, high_res), fmt)
