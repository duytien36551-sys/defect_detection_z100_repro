"""Image contract for the YOLOv8 board input and result projection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

SIZE = 640
PADDING = 114


@dataclass(frozen=True)
class ImageMapping:
    source_width: int
    source_height: int
    scale: float
    left: int
    top: int
    resized_width: int
    resized_height: int

    def project(self, xyxy: list[float]) -> list[float]:
        if len(xyxy) != 4 or not all(np.isfinite(xyxy)):
            raise ValueError("box must contain four finite model-pixel coordinates")
        if any(v < 0 or v > 1 for v in xyxy):
            raise ValueError("box must use normalized model-input coordinates in [0,1]")
        x1, y1, x2, y2 = (v * SIZE for v in xyxy)
        if x2 < x1 or y2 < y1:
            raise ValueError("box coordinates are reversed")
        return [
            max(0.0, min(float(self.source_width), (x1 - self.left) / self.scale)),
            max(0.0, min(float(self.source_height), (y1 - self.top) / self.scale)),
            max(0.0, min(float(self.source_width), (x2 - self.left) / self.scale)),
            max(0.0, min(float(self.source_height), (y2 - self.top) / self.scale)),
        ]


def load_bgr(path: str | Path) -> np.ndarray:
    """Use imdecode so non-ASCII Windows paths work."""
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"cannot decode image: {path}")
    return image


def prepare_bgr(image: np.ndarray) -> tuple[bytes, ImageMapping]:
    """Return interleaved RGB uint8, square letterbox, 114 pad.

    This transport sends uint8 pixels. The board applies /255 or its documented
    equivalent quantized input transform; the desktop does not divide twice.
    """
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ValueError("expected uint8 BGR image with three channels")
    height, width = image.shape[:2]
    if height < 1 or width < 1:
        raise ValueError("image dimensions must be positive")
    scale = min(SIZE / width, SIZE / height)
    new_width, new_height = round(width * scale), round(height * scale)
    if new_width < 1 or new_height < 1:
        raise ValueError("image aspect ratio is too extreme for a 640x640 letterbox")
    # cv2 INTER_LINEAR and symmetric padding follow the Ultralytics letterbox
    # dimensions for fixed 640x640 input with auto=False, center=True.
    resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
    left = round((SIZE - new_width) / 2 - 0.1)
    top = round((SIZE - new_height) / 2 - 0.1)
    canvas = np.full((SIZE, SIZE, 3), PADDING, dtype=np.uint8)
    canvas[top:top + new_height, left:left + new_width] = resized
    rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
    return rgb.tobytes(), ImageMapping(width, height, scale, left, top, new_width, new_height)


def prepare_image(path: str | Path) -> tuple[np.ndarray, bytes, ImageMapping]:
    source = load_bgr(path)
    tensor, mapping = prepare_bgr(source)
    return source, tensor, mapping
