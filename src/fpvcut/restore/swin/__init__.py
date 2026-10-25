"""Swin-UNet aus miccunifi/analog-video-restoration (MIT, siehe LICENSE in diesem Ordner).

Übernommen aus fpv-restoration (dort ``fpv_restoration/swin/``), unverändert bis auf relative
Importe. Quelle: https://github.com/miccunifi/analog-video-restoration (Stand c1ea129).
"""

from .video_swin_unet import VideoSwinEncoderDecoder

__all__ = ["VideoSwinEncoderDecoder"]
