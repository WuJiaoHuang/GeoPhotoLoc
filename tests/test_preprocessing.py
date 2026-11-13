import base64
from io import BytesIO

import numpy as np
from PIL import Image
import pytest

from geophotoloc.config import ImageProcessingConfig
from geophotoloc.vision import ImageInputError, prepare_image


def decode(prepared):
    return Image.open(BytesIO(base64.b64decode(prepared.data_url.split(",", 1)[1])))


@pytest.mark.parametrize("suffix,format", [(".jpg", "JPEG"), (".jpeg", "JPEG"),
                                          (".png", "PNG"), (".webp", "WEBP")])
def test_supported_formats(tmp_path, suffix, format):
    path = tmp_path / ("image" + suffix)
    Image.new("RGB", (120, 80), "red").save(path, format=format)
    result = prepare_image(path)
    assert result.metadata.original_format == format
    assert result.metadata.original_size.width == 120
    assert result.metadata.original_size.height == 80
    assert result.metadata.processed_size.width == 120
    assert result.metadata.original_bytes == path.stat().st_size
    assert result.data_url.startswith("data:image/jpeg;base64,")
    with decode(result) as image:
        assert image.format == "JPEG"
        assert image.size == (120, 80)
        assert len(image.getexif()) == 0


def test_resize(photo):
    result = prepare_image(photo, ImageProcessingConfig(max_dimension=60))
    assert result.metadata.original_size.width == 120
    assert result.metadata.processed_size.width == 60
    assert result.metadata.processed_size.height == 40


@pytest.mark.parametrize("orientation,expected", [(6, (40, 80)), (8, (40, 80)),
                                                 (3, (80, 40)), (2, (80, 40))])
def test_exif_orientation_and_metadata_removal(tmp_path, orientation, expected):
    path = tmp_path / "exif.jpg"
    image = Image.new("RGB", (80, 40), "red")
    # Left half red, right half blue: orientation 6 must move blue to bottom.
    image.paste(Image.new("RGB", (40, 40), "blue"), (40, 0))
    exif = Image.Exif()
    exif[274] = orientation
    exif[315] = "private-metadata-marker"
    exif[34853] = {1: "N", 2: (1.0, 2.0, 3.0), 3: "E", 4: (4.0, 5.0, 6.0)}
    image.save(path, exif=exif)
    result = prepare_image(path)
    assert result.metadata.orientation_corrected is True
    assert (result.metadata.original_size.width, result.metadata.original_size.height) == (80, 40)
    assert (result.metadata.oriented_size.width, result.metadata.oriented_size.height) == expected
    with decode(result) as decoded:
        assert decoded.size == expected
        assert len(decoded.getexif()) == 0
        if orientation == 6:
            assert decoded.getpixel((20, 10))[0] > 200
            assert decoded.getpixel((20, 70))[2] > 200
    assert b"private-metadata-marker" not in base64.b64decode(result.data_url.split(",")[1])


def test_transparency_is_white(tmp_path):
    path = tmp_path / "transparent.png"
    Image.new("RGBA", (32, 32), (0, 0, 0, 0)).save(path)
    with decode(prepare_image(path)) as image:
        assert image.getpixel((10, 10)) == (255, 255, 255)


def test_compression_byte_bound(tmp_path):
    path = tmp_path / "noise.png"
    pixels = np.random.default_rng(42).integers(0, 256, (256, 256, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(path)
    result = prepare_image(path, ImageProcessingConfig(max_encoded_bytes=800))
    assert result.metadata.processed_bytes <= 800
    assert result.metadata.processed_size.width < 256
    assert len(base64.b64decode(result.data_url.split(",")[1])) == result.metadata.processed_bytes


@pytest.mark.parametrize("filename,data", [("bad.jpg", b"bad"), ("empty.png", b""),
                                           ("unsupported.gif", b"GIF89a")])
def test_invalid_image(tmp_path, filename, data):
    path = tmp_path / filename
    path.write_bytes(data)
    with pytest.raises(ImageInputError):
        prepare_image(path)


def test_missing_image(tmp_path):
    with pytest.raises(ImageInputError, match="Cannot read image"):
        prepare_image(tmp_path / "missing.jpg")


def test_mismatched_format(tmp_path):
    path = tmp_path / "fake.jpg"
    Image.new("RGB", (10, 10)).save(path, format="PNG")
    with pytest.raises(ImageInputError, match="does not match"):
        prepare_image(path)


@pytest.mark.parametrize("config,message", [
    (ImageProcessingConfig(max_file_bytes=10), "byte limit"),
    (ImageProcessingConfig(max_pixels=100), "pixel limit"),
    (ImageProcessingConfig(max_encoded_bytes=1), "Cannot encode"),
])
def test_resource_limits(photo, config, message):
    with pytest.raises(ImageInputError, match=message):
        prepare_image(photo, config)


def test_truncated_jpeg(photo):
    data = photo.read_bytes()
    photo.write_bytes(data[:-50])
    with pytest.raises(ImageInputError):
        prepare_image(photo)


def test_decoder_bomb_guard(photo, monkeypatch):
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 5000)
    with pytest.raises(ImageInputError, match="unsafe dimensions"):
        prepare_image(photo)


def test_animated_image(tmp_path):
    path = tmp_path / "animated.webp"
    Image.new("RGB", (32, 32), "red").save(
        path, save_all=True, append_images=[Image.new("RGB", (32, 32), "blue")], duration=100,
    )
    with pytest.raises(ImageInputError, match="Animated"):
        prepare_image(path)
