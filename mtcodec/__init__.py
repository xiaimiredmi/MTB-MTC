"""MTC — self-built image codec.

One format, one extension: ``.mtc``. Lossy and lossless share the container,
with optional alpha and 4:2:0 / 4:4:4 chroma.
"""

from .format import EXT_IMAGE, MIME_IMAGE, NAME
from .image_codec import (
    MAGIC,
    VERSION,
    decode_image,
    encode_image,
    probe,
    psnr,
)

__all__ = [
    "EXT_IMAGE",
    "MIME_IMAGE",
    "NAME",
    "MAGIC",
    "VERSION",
    "decode_image",
    "encode_image",
    "probe",
    "psnr",
]
__version__ = "2.0"
