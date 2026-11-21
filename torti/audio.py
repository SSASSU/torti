"""Microphone capture with VAD endpointing (FR-21, FR-24)."""

from __future__ import annotations

import collections
import queue
import threading
import time
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
import webrtcvad

SAMPLE_RATE = 16000
FRAME = 480  # 30 ms at 16 kHz, a frame size webrtcvad accepts
FRAME_S = FRAME / SAMPLE_RATE


def find_device(name: str | None, kind: str) -> int | None:
    """Device index by name substring (``kind``: "input" or "output"); None means system default.

    Prefers the MME host API, which resamples to any rate we ask for.
    """
    if not name:
        return None
    hostapis = sd.query_hostapis()
    cands = [
        (i, d) for i, d in enumerate(sd.query_devices())
        if d[f"max_{kind}_channels"] > 0 and name.lower() in d["name"].lower()
    ]
    if not cands:
        raise LookupError(f"{kind} 장치를 찾을 수 없습니다: {name!r}")
    cands.sort(key=lambda c: hostapis[c[1]["hostapi"]]["name"] != "MME")
    return cands[0][0]


@dataclass
class Utterance:
    audio: np.ndarray  # float32 mono 16 kHz
    speech_start: float  # perf_counter of first voiced frame
    speech_end: float  # perf_counter of last voiced frame
    endpoint_at: float  # perf_counter when the end was decided
    peak_rms: float
    manual_stop: bool


class Recorder:
    """Keeps an input stream open; ``listen()`` returns one endpointed utterance."""

    def __init__(self, device: int | None = None, vad_level: int = 2, min_rms: float = 0.0) -> None:
        self._vad = webrtcvad.Vad(vad_level)
        self.min_rms = min_rms
        self._q: queue.Queue[np.ndarray] = queue.Queue()
        self._listening = False
        self.level = 0.0  # last frame RMS, for meters and tuning
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME,
            device=device, callback=self._callback,
        )
        self._stream.start()
        self.device_name = sd.query_devices(self._stream.device)["name"]

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        mono = indata[:, 0]
        self.level = float(np.sqrt(np.mean((mono.astype(np.float32) / 32768) ** 2)))
        if self._listening:
            self._q.put(mono.copy())

    def _voiced(self, frame: np.ndarray) -> tuple[bool, float]:
        rms = float(np.sqrt(np.mean((frame.astype(np.float32) / 32768) ** 2)))
        if len(frame) != FRAME or rms < self.min_rms:
            return False, rms
        return self._vad.is_speech(frame.tobytes(), SAMPLE_RATE), rms

    def listen(
        self,
        *,
        ignore_ms: int = 0,
        wait_speech_s: float = 6.0,
        end_silence_ms: int = 800,
        max_s: float = 30.0,
        preroll_ms: int = 300,
        min_speech_ms: int = 250,
        hold: threading.Event | None = None,
        stop: threading.Event | None = None,
        cancel: threading.Event | None = None,
    ) -> Utterance | None:
        """Block until one utterance ends. None if nobody spoke, or on cancel.

        Tap mode: VAD decides where speech ends. Hold mode (``hold`` is set while the pedal is
        down): no silence endpoint; everything recorded until ``stop`` goes to STT, because quiet
        speech may never trip the VAD. ``stop`` also ends tap mode early (second press).
        ``ignore_ms`` skips our own "listening" beep. Utterances whose voiced part is shorter
        than ``min_speech_ms`` are dropped: Whisper invents text ("감사합니다") from clicks.
        """
        self._q = queue.Queue()
        self._listening = True
        t0 = time.perf_counter()
        ignore_frames = int(ignore_ms / 1000 / FRAME_S)
        preroll: collections.deque[np.ndarray] = collections.deque(maxlen=max(1, int(preroll_ms / 1000 / FRAME_S)))
        recent: collections.deque[bool] = collections.deque(maxlen=5)
        everything: list[np.ndarray] = []  # all audio after the beep, for hold mode
        frames: list[np.ndarray] = []  # from VAD speech start, for tap mode
        speech_start = last_voiced = None
        first_loud = last_loud = None
        voiced_frames = loud_frames = 0
        silence_needed = int(end_silence_ms / 1000 / FRAME_S)
        silent_run = 0
        peak = 0.0
        n = 0
        manual = False
        try:
            while True:
                if cancel is not None and cancel.is_set():
                    return None
                if stop is not None and stop.is_set():
                    manual = True
                    break
                held = hold is not None and hold.is_set()
                try:
                    frame = self._q.get(timeout=0.05)
                except queue.Empty:
                    if (speech_start is None and not held
                            and time.perf_counter() - t0 > wait_speech_s + ignore_ms / 1000):
                        return None
                    continue
                n += 1
                everything.append(frame)  # hold mode keeps even the beep window: people talk right away
                if n <= ignore_frames:
                    continue
                voiced, rms = self._voiced(frame)
                now = time.perf_counter()
                peak = max(peak, rms)
                if rms >= self.min_rms:
                    first_loud = first_loud or now
                    last_loud = now
                    loud_frames += 1
                if voiced:
                    voiced_frames += 1
                if speech_start is None:
                    preroll.append(frame)
                    recent.append(voiced)
                    if sum(recent) >= 3:  # 3 of the last 5 frames voiced: speech has started
                        speech_start = last_voiced = now
                        frames.extend(preroll)
                    elif not held and now - t0 > wait_speech_s + ignore_ms / 1000:
                        return None
                    continue
                frames.append(frame)
                if voiced:
                    last_voiced = now
                    silent_run = 0
                elif not held:
                    silent_run += 1
                    if silent_run >= silence_needed:
                        break
                if now - t0 > max_s:
                    break
        finally:
            self._listening = False
        end = time.perf_counter()
        if manual:  # pedal released or pressed again: trust the user, keep everything
            if first_loud is None or loud_frames * FRAME_S * 1000 < min_speech_ms:
                return None
            audio = np.concatenate(everything).astype(np.float32) / 32768
            return Utterance(audio, first_loud, last_loud, end, peak, True)
        if speech_start is None or voiced_frames * FRAME_S * 1000 < min_speech_ms:
            return None
        audio = np.concatenate(frames).astype(np.float32) / 32768
        return Utterance(audio, speech_start, last_voiced, end, peak, False)

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()
