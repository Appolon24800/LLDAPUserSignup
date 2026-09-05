"""Profile picture processing: sniff, size-check, strip, re-encode.

The final artifact is always produced server-side: content is identified by
magic bytes (never by file extension or client claims), decoded by Pillow
(``verify()`` first), re-encoded to plain JPEG — which rebuilds the image and
therefore strips EXIF/GPS metadata by construction — and bounded to
512x512 for the LLDAP ``jpegPhoto`` attribute.
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps

OUTPUT_MAX_DIMENSION = 512
OUTPUT_JPEG_QUALITY = 85

# Sanity ceiling to refuse absurdly large dimensions (decompression bombs).
MAX_IMAGE_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class ImageRejected(Exception):
    """Raised with a stable code ('too_large' | 'unsupported')."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def sniff_format(data: bytes) -> str | None:
    """Identify an image by magic bytes; returns None for unknown content."""
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def process_photo(data: bytes, max_bytes: int) -> bytes:
    """Validate and re-encode an uploaded photo into clean JPEG bytes."""
    if len(data) > max_bytes:
        raise ImageRejected("too_large")
    if sniff_format(data) is None:
        raise ImageRejected("unsupported")

    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()  # decode checks; invalidates the handle
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)  # honor rotation before discarding EXIF
            flattened = _flatten_to_rgb(img)
            flattened.thumbnail((OUTPUT_MAX_DIMENSION, OUTPUT_MAX_DIMENSION))
            buffer = io.BytesIO()
            flattened.save(buffer, format="JPEG", quality=OUTPUT_JPEG_QUALITY)
    except ImageRejected:
        raise
    except Exception as err:  # malformed input, bombs, unsupported codecs
        raise ImageRejected("unsupported") from err

    output = buffer.getvalue()
    if not output.startswith(b"\xff\xd8"):
        raise ImageRejected("unsupported")
    return output


def _flatten_to_rgb(img: Image.Image) -> Image.Image:
    """Convert any mode to RGB, compositing transparency onto white."""
    if img.mode == "RGB":
        return img.copy()
    rgba = img.convert("RGBA")
    background = Image.new("RGB", rgba.size, (255, 255, 255))
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background
