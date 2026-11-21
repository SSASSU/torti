"""Close look: zoom, crop and clean up part of the camera frame so small things can be seen.

Separate from capture (camera.py) and from the conversation (engine.py):

* ``Zoom`` - the user's view: which part of the frame is shown, sent and pointed at.
* ``average_still`` / ``for_model`` - a cleaner, enlarged crop for the vision model.
* ``Inspector`` - finds what a question is about on the whole frame (fast model) and returns that
  part as a close-up. Reading questions get it *before* the answer, together with the whole photo,
  so there is no second round trip; the voice model can still ask for one (``<확대 대상="..."/>``).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import cv2
import numpy as np

from .camera import encode_jpeg, jpeg_size

class Zoom:
    """Software zoom on the camera frame: the cropped part is what's shown, sent and pointed at.

    The camera's own zoom is digital on its 1080p output (measured: no more detail than a crop),
    so cropping here loses nothing, is instant and leaves the camera alone. A crop is sent at its
    native pixels instead of the whole frame shrunk to 1280 px, so small parts get more detail.
    All values are fractions of the full frame.
    """

    MAX = 4.0

    def __init__(self) -> None:
        self.factor, self.cx, self.cy = 1.0, 0.5, 0.5

    @property
    def active(self) -> bool:
        return self.factor > 1.01

    def rect(self) -> tuple[float, float, float, float]:
        """Visible part (x1, y1, x2, y2) as fractions of the full frame."""
        s = 1 / self.factor
        x1 = min(max(self.cx - s / 2, 0.0), 1 - s)
        y1 = min(max(self.cy - s / 2, 0.0), 1 - s)
        return x1, y1, x1 + s, y1 + s

    def _set(self, factor: float, cx: float, cy: float) -> None:
        self.factor = min(max(factor, 1.0), self.MAX)
        self.cx, self.cy = cx, cy
        x1, y1, x2, y2 = self.rect()  # keep the stored center where the visible part really is
        self.cx, self.cy = (x1 + x2) / 2, (y1 + y2) / 2

    def reset(self) -> None:
        self._set(1.0, 0.5, 0.5)

    def zoom_at(self, factor: float, u: float = 0.5, v: float = 0.5) -> None:
        """New factor, keeping the point at (u, v) of the current view where it is."""
        x1, y1, x2, y2 = self.rect()
        px, py = x1 + u * (x2 - x1), y1 + v * (y2 - y1)
        s = 1 / min(max(factor, 1.0), self.MAX)
        self._set(factor, px - u * s + s / 2, py - v * s + s / 2)

    def pan(self, du: float, dv: float) -> None:
        """Move the view by a fraction of its own size."""
        s = 1 / self.factor
        self._set(self.factor, self.cx + du * s, self.cy + dv * s)

    def to_box(self, box: tuple[float, float, float, float], fill: float = 0.6) -> None:
        """Zoom so that a full-frame box fills about ``fill`` of the view."""
        x1, y1, x2, y2 = box
        size = max(x2 - x1, y2 - y1, 1e-3)
        self._set(min(max(fill / size, 1.5), self.MAX), (x1 + x2) / 2, (y1 + y2) / 2)

    def view_to_full(self, box: tuple[float, float, float, float],
                     rect: tuple[float, float, float, float] | None = None) -> tuple[float, float, float, float]:
        """A box in view fractions -> full-frame fractions (``rect``: the view it was in)."""
        rx1, ry1, rx2, ry2 = rect or self.rect()
        w, h = rx2 - rx1, ry2 - ry1
        return rx1 + box[0] * w, ry1 + box[1] * h, rx1 + box[2] * w, ry1 + box[3] * h

    def crop(self, frame: np.ndarray) -> np.ndarray:
        if not self.active:
            return frame
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = self.rect()
        return frame[round(y1 * h):round(y2 * h), round(x1 * w):round(x2 * w)]


STILL_DIFF = 2.5  # mean gray difference (0..255, on a small thumbnail) still counted as "the same scene"


def average_still(frames: list[np.ndarray]) -> tuple[np.ndarray | None, int]:
    """Average the newest frame with the earlier ones that barely differ from it."""
    if not frames:
        return None, 0
    last = frames[-1]

    def thumb(f: np.ndarray) -> np.ndarray:
        return cv2.cvtColor(cv2.resize(f, (192, 108), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)

    ref = thumb(last)
    same = [f for f in frames[:-1] if f.shape == last.shape and float(np.abs(thumb(f) - ref).mean()) < STILL_DIFF]
    if not same:
        return last.copy(), 1
    acc = last.astype(np.float32)
    for f in same:
        acc += f
    return (acc / (len(same) + 1) + 0.5).astype(np.uint8), len(same) + 1


def for_model(img: np.ndarray, long_edge: int = 1280) -> bytes:
    """JPEG of a zoomed crop for the vision model: enlarged (up to 4x) so small print spans enough
    of the model's image patches. Measured: a 320x180 board crop was misread ("FLIGHT?") as is,
    read right ("FIGHTING") when enlarged 4x, and was unreadable in the whole frame."""
    h, w = img.shape[:2]
    scale = min(long_edge / max(h, w), 4.0)
    if scale > 1.05:
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_LANCZOS4)
    return encode_jpeg(img, long_edge, quality=92)


# Questions about small print or fine detail: worth a close-up before answering.
_CLOSE = re.compile(r"읽어|읽혀|읽을|글씨|글자|적혀|써 ?있|각인|모델명|품번|색띠|몇 ?옴|납땜 ?(상태|잘|괜찮|어때)|브릿지|냉땜|핀 ?번호")


def needs_close_look(text: str) -> bool:
    return bool(_CLOSE.search(text))


@dataclass
class Look:
    jpeg: bytes  # the close-up, enlarged for the model
    box: tuple[float, float, float, float]  # where it is on the whole frame (fractions)
    factor: float
    label: str
    seconds: float  # time to find it
    frames: int  # still frames averaged


def union(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


class Inspector:
    """Finds the spot a question (or a named target) is about and crops it at native pixels.

    ``pointer`` is any object with ``locate(jpeg, size, question) -> (marks, seconds)``; a fast model
    is enough for a box around one thing (Haiku placed 4/4 boxes, IoU 0.96, in the M0 pointing test).
    """

    def __init__(self, pointer, long_edge: int = 1280) -> None:
        self.pointer = pointer
        self.long_edge = long_edge

    def find(self, frame: np.ndarray, question: str) -> tuple[tuple[float, float, float, float] | None, float, str]:
        """Box (fractions of ``frame``) for what ``question`` points at, seconds taken, label."""
        jpeg = encode_jpeg(frame, self.long_edge)
        t = time.perf_counter()
        marks, _ = self.pointer.locate(jpeg, jpeg_size(jpeg), question)
        secs = time.perf_counter() - t
        if not marks:
            return None, secs, ""
        return union([tuple(v / 1000 for v in m.box) for m in marks]), secs, marks[0].label

    def look(self, frames: list[np.ndarray], question: str, target: str | None = None) -> Look | None:
        """Close-up of what ``question`` (or ``target``) is about, from the newest still frames."""
        if not frames:
            return None
        box, secs, label = self.find(frames[-1], f"{target} 위치" if target else question)
        if box is None:
            return None
        z = Zoom()
        z.to_box(box)
        img, n = average_still([z.crop(f) for f in frames])
        return Look(for_model(img, self.long_edge), box, z.factor, target or label, secs, n)
