from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class GifBinaryPayload:
    name: str
    width: int
    height: int
    frames: int
    delay_ms: int
    total_size: int
    data: bytes

    def metadata(self) -> dict:
        return {
            "type": "set_gif",
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "frames": self.frames,
            "total_size": self.total_size,
            "delay": self.delay_ms,
        }


def build_rgb565_from_gif(
    gif_path: str | Path,
    *,
    name: str | None = None,
    width: int = 80,
    height: int = 80,
    delay_ms: int = 200,
    remove_frames: Iterable[int] | None = None,
    bg_color: tuple[int, int, int, int] = (0, 0, 0, 255),
    contrast: float = 1.45,
    brightness: float = 1.20,
) -> GifBinaryPayload:
    """
    Convert a GIF into a raw RGB565 animation binary (little-endian).

    `remove_frames` uses 1-based indices to match the UI payload.
    """
    gif_path = Path(gif_path)
    if not gif_path.exists():
        raise FileNotFoundError(f"GIF file not found: {gif_path}")

    try:
        from PIL import Image, ImageEnhance, ImageOps
    except ImportError as e:
        raise RuntimeError("Pillow is required for GIF processing") from e

    remove_set = {int(i) for i in (remove_frames or []) if int(i) > 0}
    raw = bytearray()
    frame_count = 0

    with Image.open(gif_path) as img:
        total_frames = getattr(img, "n_frames", 1)
        for frame_index in range(total_frames):
            frame_num = frame_index + 1
            if frame_num in remove_set:
                continue

            img.seek(frame_index)
            frame = img.convert("RGBA")
            background = Image.new("RGBA", frame.size, bg_color)
            frame = Image.alpha_composite(background, frame).convert("RGB")

            if contrast != 1.0:
                frame = ImageEnhance.Contrast(frame).enhance(contrast)
            if brightness != 1.0:
                frame = ImageEnhance.Brightness(frame).enhance(brightness)

            frame = ImageOps.fit(frame, (width, height), Image.Resampling.LANCZOS)

            for r, g, b in frame.getdata():
                rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                raw.extend(struct.pack("<H", rgb565))

            frame_count += 1

    if frame_count == 0:
        raise ValueError("All GIF frames were removed; nothing to send")

    binary = bytes(raw)
    return GifBinaryPayload(
        name=name or gif_path.name,
        width=width,
        height=height,
        frames=frame_count,
        delay_ms=delay_ms,
        total_size=len(binary),
        data=binary,
    )

