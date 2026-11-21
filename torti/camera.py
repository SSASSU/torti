"""Webcam capture: a background thread keeps the latest frame so a snapshot is instant (FR-12)."""

from __future__ import annotations

import threading
import time

import cv2
import numpy as np

_BACKENDS = {"dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF, "any": cv2.CAP_ANY}


def list_cameras() -> list[str]:
    """DirectShow video input names; list position == OpenCV CAP_DSHOW index."""
    try:
        from pygrabber.dshow_graph import FilterGraph

        return FilterGraph().get_input_devices()
    except Exception:  # noqa: BLE001 - enumeration is best effort; fall back to index 0
        return []


def resolve_camera(name: str | None = None) -> tuple[int, str | None]:
    """Pick a camera by name substring, else the first non-virtual device (FR-10)."""
    names = list_cameras()
    if name:
        for i, n in enumerate(names):
            if name.lower() in n.lower():
                return i, n
        raise LookupError(f"카메라를 찾을 수 없습니다: {name!r} (목록: {names})")
    for i, n in enumerate(names):
        if "virtual" not in n.lower():
            return i, n
    return 0, names[0] if names else None


class Camera:
    def __init__(self, index: int = 0, width: int = 1920, height: int = 1080, backend: str = "dshow") -> None:
        self.index, self.width, self.height, self.backend = index, width, height, backend
        self._cap: cv2.VideoCapture | None = None
        self._frame: np.ndarray | None = None
        self._frame_time = 0.0
        self._lock = threading.Lock()
        self._running = False

    def open(self, timeout: float = 5.0) -> bool:
        cap = cv2.VideoCapture(self.index, _BACKENDS[self.backend])
        if not cap.isOpened():
            return False
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))  # needed for 1080p at full frame rate
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap = cap
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        deadline = time.monotonic() + timeout
        while self._frame is None and time.monotonic() < deadline:
            time.sleep(0.02)
        return self._frame is not None

    def _loop(self) -> None:
        while self._running and self._cap is not None:
            ok, frame = self._cap.read()
            if ok:
                with self._lock:
                    self._frame, self._frame_time = frame, time.monotonic()
            else:
                time.sleep(0.05)

    def snapshot(self) -> np.ndarray | None:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def frame_age(self) -> float:
        return time.monotonic() - self._frame_time if self._frame_time else float("inf")

    def close(self) -> None:
        self._running = False
        if self._cap is not None:
            time.sleep(0.1)
            self._cap.release()
            self._cap = None


def read_image(path) -> np.ndarray | None:
    """cv2.imread can't open non-ASCII (Korean) paths on Windows; decode from bytes instead."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def jpeg_size(jpeg: bytes) -> tuple[int, int]:
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    return img.shape[1], img.shape[0]


def encode_jpeg(frame: np.ndarray, max_long_edge: int = 1280, quality: int = 85) -> bytes:
    """Downscale and compress for upload (FR-17): enough detail to read, fewer image tokens."""
    h, w = frame.shape[:2]
    scale = max_long_edge / max(h, w)
    if scale < 1:
        frame = cv2.resize(frame, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()
