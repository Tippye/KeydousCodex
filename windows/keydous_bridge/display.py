"""Export and fixed-delay device animation conversion."""
from __future__ import annotations

from bisect import bisect_right
import io
import math

from PIL import Image


def gif_bytes(frames: list[Image.Image], durations: list[int]) -> bytes:
    output = io.BytesIO()
    frames[0].save(output, format="GIF", save_all=True, append_images=frames[1:],
                   duration=durations, loop=0, disposal=2, optimize=False)
    return output.getvalue()


def png_bytes(frame: Image.Image) -> bytes:
    output = io.BytesIO()
    frame.save(output, format="PNG")
    return output.getvalue()


def rgb565(image: Image.Image) -> bytes:
    image = image.convert("RGB")
    pixels = image.load()
    output = bytearray()
    for x in range(image.width):
        for y in range(image.height):
            red, green, blue = pixels[x, y]
            value = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
            output.extend(value.to_bytes(2, "big"))
    return bytes(output)


def device_animation(frames: list[Image.Image], durations: list[int]) -> tuple[list[bytes], int]:
    if not frames or len(frames) != len(durations) or any(d < 1 for d in durations):
        raise ValueError("动画帧或时长无效")
    total = sum(durations)
    delay = max(100, math.ceil(total / 50 / 10) * 10)
    if delay > 250:
        raise ValueError("动画时长超过 NJ98 当前导出上限")
    count = max(2, math.ceil(total / delay))
    boundaries, acc = [], 0
    for duration in durations:
        acc += duration
        boundaries.append(acc)
    encoded = [rgb565(image) for image in frames]
    return [encoded[min(bisect_right(boundaries, (index * delay) % total), len(frames) - 1)]
            for index in range(count)], delay
