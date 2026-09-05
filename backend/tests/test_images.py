"""Photo pipeline: magic-byte sniffing, size caps, EXIF stripping, re-encode."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.images import ImageRejected, process_photo, sniff_format


def jpeg_bytes(size=(64, 48), exif: bytes | None = None, color=(120, 30, 200)) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    if exif is None:
        img.save(buf, format="JPEG")
    else:
        img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def png_bytes(size=(64, 48)) -> bytes:
    img = Image.new("RGB", size, (10, 200, 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def webp_bytes(size=(64, 48)) -> bytes:
    img = Image.new("RGB", size, (5, 5, 250))
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    return buf.getvalue()


def gif_bytes(size=(64, 48)) -> bytes:
    img = Image.new("P", size)
    img.putpalette([0, 0, 0, 255, 255, 255])
    buf = io.BytesIO()
    img.save(buf, format="GIF")
    return buf.getvalue()


def test_sniff_format():
    assert sniff_format(jpeg_bytes()) == "jpeg"
    assert sniff_format(png_bytes()) == "png"
    assert sniff_format(gif_bytes()) == "gif"
    assert sniff_format(webp_bytes()) == "webp"
    assert sniff_format(b"not an image at all") is None
    assert sniff_format(b"") is None
    assert sniff_format(b"\xff\xd8" + b"\x00" * 10) is None  # near-miss signature
    assert sniff_format(b"GIF98a" + b"\x00" * 10) is None


def test_rejects_oversized():
    with pytest.raises(ImageRejected) as exc:
        process_photo(b"\x00" * 100, max_bytes=10)
    assert exc.value.code == "too_large"


def test_rejects_non_image_content():
    for junk in (b"hello world", b"<?php echo 1; ?>", jpeg_bytes()[:20]):
        with pytest.raises(ImageRejected) as exc:
            process_photo(junk, max_bytes=1024 * 1024)
        assert exc.value.code == "unsupported"


def test_rejects_extension_disguise():
    # PNG content is fine regardless of any filename — we only look at bytes.
    out = process_photo(png_bytes(), max_bytes=1024 * 1024)
    assert out.startswith(b"\xff\xd8")  # always re-encoded to JPEG


@pytest.mark.parametrize("raw", [jpeg_bytes(), png_bytes(), webp_bytes(), gif_bytes()])
def test_accepts_and_reencodes_to_jpeg(raw):
    out = process_photo(raw, max_bytes=1024 * 1024)
    assert out.startswith(b"\xff\xd8\xff")
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"


def test_downscales_large_images():
    out = process_photo(jpeg_bytes(size=(3000, 2000)), max_bytes=1024 * 1024)
    with Image.open(io.BytesIO(out)) as img:
        assert max(img.size) <= 512


def test_strips_exif_metadata():
    exif = Image.Exif()
    exif[0x010F] = "CameraCorp"  # Make
    exif[0x0110] = "ModelX"  # Model
    out = process_photo(jpeg_bytes(exif=exif.tobytes()), max_bytes=1024 * 1024)
    with Image.open(io.BytesIO(out)) as img:
        assert not img.getexif()  # empty EXIF after re-encode
    assert b"CameraCorp" not in out
    assert b"ModelX" not in out


def test_rejects_huge_dimensions(monkeypatch):
    from app import images

    monkeypatch.setattr(images.Image, "MAX_IMAGE_PIXELS", 10, raising=False)
    with pytest.raises(ImageRejected) as exc:
        process_photo(jpeg_bytes(size=(200, 200)), max_bytes=1024 * 1024)
    assert exc.value.code == "unsupported"
