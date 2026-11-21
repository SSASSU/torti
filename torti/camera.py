"""Webcam capture: a background thread keeps the latest frame so a snapshot is instant (FR-12)."""

from __future__ import annotations

import collections
import threading
import time

import cv2
import numpy as np

_BACKENDS = {"dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF, "any": cv2.CAP_ANY}


def _com_init() -> None:
    """DirectShow enumeration is COM, which must be initialized on every thread that uses it
    (comtypes only does it for the thread that first imports it)."""
    try:
        import comtypes

        comtypes.CoInitialize()  # S_FALSE when already done on this thread: fine
    except Exception:  # noqa: BLE001 - e.g. thread already in another COM mode; enumeration may still work
        pass


def list_cameras() -> list[str] | None:
    """DirectShow video input names (list position == OpenCV CAP_DSHOW index); None if enumeration failed."""
    _com_init()
    try:
        from pygrabber.dshow_graph import FilterGraph

        return FilterGraph().get_input_devices()
    except Exception:  # noqa: BLE001 - enumeration is best effort
        return None


def resolve_camera(name: str | None = None) -> tuple[int, str | None]:
    """Pick a camera by name substring, else the first non-virtual device (FR-10)."""
    names = list_cameras() or []
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
    """Keeps the latest frame. If the camera is unplugged or moved to another port it reconnects by
    itself (by device name, since the index can change), and an old frame is never handed out."""

    STALE_S = 2.0  # a frame older than this is not the desk any more
    GIVE_UP_S = 1.5  # this long without frames: close and reconnect

    def __init__(self, want: str | None = None, width: int = 1920, height: int = 1080,
                 backend: str = "dshow", index: int | None = None, on_change=None) -> None:
        """``want``: name substring from settings; None picks the first real (non-virtual) camera.
        ``index`` forces a DirectShow index (spikes). ``on_change(text)`` reports connect/disconnect."""
        self.want, self.index, self.width, self.height, self.backend = want, index, width, height, backend
        self.name: str | None = None  # device actually in use
        self._forced = index is not None
        self._on_change = on_change
        self.reconnects = 0
        self._cap: cv2.VideoCapture | None = None
        self._frame: np.ndarray | None = None
        self._frame_time = 0.0
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._recent: collections.deque[np.ndarray] = collections.deque(maxlen=8)  # for snapshot_still

    def _pick(self) -> bool:
        """Find the device again; a replugged camera can come back under another index."""
        if self._forced:
            return True
        names = list_cameras()
        if names is None:  # enumeration itself failed: only a device we already know is safe to reopen
            return self.index is not None and self.name is not None
        if self.name in names:
            self.index = names.index(self.name)
            return True
        for i, n in enumerate(names):
            if (self.want.lower() in n.lower()) if self.want else ("virtual" not in n.lower()):
                self.index, self.name = i, n
                return True
        return False  # only virtual cameras (or not the wanted one): wait instead of showing a placeholder

    def _connect(self) -> bool:
        if not self._pick():
            return False
        cap = cv2.VideoCapture(self.index, _BACKENDS[self.backend])
        if not cap.isOpened():
            cap.release()
            return False
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))  # needed for 1080p at full frame rate
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap = cap
        return True

    def open(self, timeout: float = 5.0) -> bool:
        """Start capturing. True if a frame came within ``timeout``; otherwise it keeps trying in
        the background and frames appear once the camera is plugged in. All device work happens on
        the capture thread."""
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="camera")
        self._thread.start()
        deadline = time.monotonic() + timeout
        while self._frame is None and time.monotonic() < deadline:
            time.sleep(0.02)
        return self._frame is not None

    def _report(self, text: str) -> None:
        if self._on_change:
            try:
                self._on_change(text)
            except Exception:  # noqa: BLE001 - logging must not stop capture
                pass

    def _loop(self) -> None:
        failing_since: float | None = None
        first = True
        while self._running:
            cap = self._cap
            if cap is None:
                if not first:
                    time.sleep(1.0)
                if self._running and self._connect():
                    if not first:
                        self.reconnects += 1
                    self._report(f"카메라 연결됨: {self.name or self.index} (index {self.index})")
                first = False
                continue
            ok, frame = cap.read()
            if ok:
                failing_since = None
                with self._lock:
                    self._frame, self._frame_time = frame, time.monotonic()
                    self._recent.append(frame)
                continue
            failing_since = failing_since or time.monotonic()
            if time.monotonic() - failing_since > self.GIVE_UP_S:
                cap.release()
                self._cap, failing_since = None, None
                self._report(f"카메라 끊김: {self.name or self.index} - 다시 연결을 기다립니다")
            else:
                time.sleep(0.05)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    @property
    def connected(self) -> bool:
        return self.frame_age() <= self.STALE_S

    def snapshot(self) -> np.ndarray | None:
        """Latest frame, or None when there is none recent (camera unplugged or reconnecting)."""
        with self._lock:
            if self._frame is None or time.monotonic() - self._frame_time > self.STALE_S:
                return None
            return self._frame.copy()

    def recent_frames(self, n: int = 8) -> list[np.ndarray]:
        """The last few frames, oldest first (cheap: no copies); [] when the camera is gone.
        ``average_still`` turns them into one cleaner picture when a photo is actually sent."""
        with self._lock:
            if self._frame is None or time.monotonic() - self._frame_time > self.STALE_S:
                return []
            return list(self._recent)[-n:]

    def frame_age(self) -> float:
        return time.monotonic() - self._frame_time if self._frame_time else float("inf")

    def close(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2)


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
