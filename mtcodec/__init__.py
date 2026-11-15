from .format import EXT_IMAGE, EXT_VIDEO, MIME_IMAGE, MIME_VIDEO, NAME, VIDEO_NAME
from .image_codec import MAGIC as IMAGE_MAGIC
from .image_codec import decode_image, encode_image, probe, psnr
from .video_codec import VID_MAGIC as VIDEO_MAGIC
from .video_codec import decode_video, encode_video, probe_video

__all__ = [
    "NAME",
    "VIDEO_NAME",
    "EXT_IMAGE",
    "EXT_VIDEO",
    "MIME_IMAGE",
    "MIME_VIDEO",
    "IMAGE_MAGIC",
    "VIDEO_MAGIC",
    "encode_image",
    "decode_image",
    "probe",
    "psnr",
    "encode_video",
    "decode_video",
    "probe_video",
]
__version__ = "1.0"
