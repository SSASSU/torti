"""Status earcons (FR-06). A persistent output stream keeps trigger-to-beep latency low (NFR-09)."""

from __future__ import annotations

import threading

import numpy as np
import sounddevice as sd

SR = 48000

# (frequency Hz, seconds); 0 Hz is a gap.
_SPECS = {
    "listen": [(660, 0.07), (0, 0.02), (990, 0.09)],   # rising: speak now
    "accept": [(880, 0.06)],                            # got it, thinking
    "idle": [(740, 0.05), (0, 0.02), (554, 0.07)],      # falling: back to standby
    "cancel": [(523, 0.06), (0, 0.02), (392, 0.08)],
    "error": [(330, 0.12), (0, 0.04), (247, 0.20)],
    "visual": [(1175, 0.05), (0, 0.03), (1568, 0.08)],  # look at the screen: a location is marked
}


def _render(spec: list[tuple[float, float]], volume: float) -> np.ndarray:
    parts = []
    for freq, dur in spec:
        t = np.arange(int(SR * dur)) / SR
        if freq <= 0:
            parts.append(np.zeros_like(t))
            continue
        env = np.minimum(1.0, np.minimum(t / 0.005, (dur - t) / 0.02))  # 5 ms attack, 20 ms release
        parts.append(np.sin(2 * np.pi * freq * t) * env)
    return (np.concatenate(parts) * volume).astype(np.float32)


class Earcons:
    def __init__(self, device: int | None = None, volume: float = 0.3) -> None:
        self._sounds = {k: _render(v, volume) for k, v in _SPECS.items()}
        self._lock = threading.Lock()
        self._buf: np.ndarray | None = None
        self._pos = 0
        self._stream = sd.OutputStream(samplerate=SR, channels=1, dtype="float32", device=device,
                                       callback=self._callback)
        self._stream.start()

    def _callback(self, outdata, frames, time_info, status) -> None:  # noqa: ARG002
        with self._lock:
            if self._buf is None:
                outdata.fill(0)
                return
            chunk = self._buf[self._pos:self._pos + frames]
            outdata[:len(chunk), 0] = chunk
            outdata[len(chunk):, 0] = 0
            self._pos += frames
            if self._pos >= len(self._buf):
                self._buf = None

    def play(self, name: str) -> None:
        with self._lock:
            self._buf, self._pos = self._sounds[name], 0

    def duration_ms(self, name: str) -> int:
        return round(len(self._sounds[name]) / SR * 1000)

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()
