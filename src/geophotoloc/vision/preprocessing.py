"""Bounded JPEG/PNG/WebP decoding and metadata-free JPEG encoding."""

import base64
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from geophotoloc.config import ImageProcessingConfig
from geophotoloc.models import ImageMetadata, ImageSize


class ImageInputError(ValueError):
    """Invalid, unavailable, or oversized input image."""


@dataclass(frozen=True)
class PreparedImage:
    data_url: str
    metadata: ImageMetadata


def prepare_image(
    path: str | Path, config: ImageProcessingConfig | None = None,
) -> PreparedImage:
    config = config or ImageProcessingConfig()
    path = Path(path)
    formats = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
    expected = formats.get(path.suffix.lower())
    if expected is None:
        raise ImageInputError("Unsupported image extension; use JPEG, PNG or WebP")
    try:
        with path.open("rb") as stream:
            data = stream.read(config.max_file_bytes + 1)
        if not data:
            raise ImageInputError("Image file is empty")
        if len(data) > config.max_file_bytes:
            raise ImageInputError("Image file exceeds byte limit")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format != expected:
                    raise ImageInputError("Image content format does not match its extension")
                original_size = ImageSize(width=source.width, height=source.height)
                if source.width * source.height > config.max_pixels:
                    raise ImageInputError("Image dimensions exceed pixel limit")
                if getattr(source, "is_animated", False):
                    raise ImageInputError("Animated images are not supported")
                source.verify()
            with Image.open(BytesIO(data)) as source:
                # Read orientation only. GPS is never used or included in the payload.
                orientation = source.getexif().get(274, 1)
                oriented = ImageOps.exif_transpose(source)
                oriented.load()
                oriented_size = ImageSize(width=oriented.width, height=oriented.height)
                rgba = oriented.convert("RGBA")
                clean = Image.new("RGB", rgba.size, "white")
                clean.paste(rgba, mask=rgba.getchannel("A"))
        clean.thumbnail((config.max_dimension, config.max_dimension), Image.Resampling.LANCZOS)
        while True:
            for quality in (85, 70, 55, 40):
                buffer = BytesIO()
                clean.save(buffer, format="JPEG", quality=quality, optimize=True)
                encoded = buffer.getvalue()
                if len(encoded) <= config.max_encoded_bytes:
                    metadata = ImageMetadata(
                        original_size=original_size, oriented_size=oriented_size,
                        processed_size=ImageSize(width=clean.width, height=clean.height),
                        original_format=expected, original_bytes=len(data),
                        processed_bytes=len(encoded), orientation_corrected=orientation in range(2, 9),
                    )
                    return PreparedImage(
                        "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii"),
                        metadata,
                    )
            if clean.size == (1, 1):
                raise ImageInputError("Cannot encode image within configured byte limit")
            clean = clean.resize(
                (max(1, int(clean.width * 0.8)), max(1, int(clean.height * 0.8))),
                Image.Resampling.LANCZOS,
            )
    except ImageInputError:
        raise
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageInputError("Cannot read image: missing, inaccessible, corrupt or unsafe dimensions") from None
