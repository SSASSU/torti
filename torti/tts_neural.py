"""Natural Korean voice (Chatterbox, male) through the .venv-tts worker process.

Same interface as ``SapiTts`` so the engine can swap them. Sentences are sent to the worker as
they arrive and synthesized in order; the player speaks one while the next is being made.
``stop()`` (barge-in) cuts playback within one audio block and drops sentences not made yet.
The worker runs at about 1.1x real time on an RTX 4070 SUPER, so a long first sentence is split
at a comma to start talking sooner.
"""

from __future__ import annotations

import base64
import collections
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import sounddevice as sd

from . import ROOT
from .speech_text import first_chunk, spell_numbers

WORKER_PYTHON = ROOT / ".venv-tts" / "Scripts" / "python.exe"
MOOD_EXAGGERATION = {"차분": 0.4, "진지": 0.35, "활기": 0.65, "장난스러움": 0.8, "친근": 0.5}
BLOCK = 1024  # playback block: stop() takes effect within ~40 ms at 24 kHz


def available() -> bool:
    return WORKER_PYTHON.exists()


class NeuralTts:
    voice_name = "Chatterbox 한국어 (남성)"

    def __init__(self, device: int | None = None) -> None:
        self.device = device
        self.rate = 0  # SAPI-style -10..10 around the mood's base rate; maps to playback speed
        self.base_rate = 0
        self.exaggeration = 0.5
        self.sr = 24000
        self.error: str | None = None
        self.load_s: float | None = None
        self._next_id = 0
        self._order: collections.deque[int] = collections.deque()  # ids to play, in order
        self._audio: dict[int, np.ndarray | None] = {}
        self._cv = threading.Condition()
        self._playing = False
        self._abort = False
        self._first_in_turn = True
        self._play_starts: collections.deque[float] = collections.deque(maxlen=64)
        self._ready = threading.Event()
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._proc = subprocess.Popen(
            [str(WORKER_PYTHON), "-m", "torti.tts_worker"], cwd=str(ROOT), env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=flags)
        threading.Thread(target=self._read, daemon=True, name="tts-neural-read").start()
        threading.Thread(target=self._play_loop, daemon=True, name="tts-neural-play").start()

    # ------------------------------------------------------------- lifecycle
    def wait_ready(self, timeout: float = 180) -> bool:
        """Model load takes ~25 s; call this after starting the other heavy parts."""
        if not self._ready.wait(timeout):
            self.error = self.error or "신경망 TTS 준비 시간 초과"
        return self._ready.is_set() and not self.error

    def close(self) -> None:
        self.stop()
        try:
            self._proc.stdin.close()
            self._proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            self._proc.kill()

    def _read(self) -> None:
        for raw in self._proc.stdout:
            try:
                msg = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if msg.get("ready"):
                self.sr, self.load_s = msg["sr"], msg.get("load_s")
                self._ready.set()
                continue
            with self._cv:
                if msg.get("id") in self._order:
                    if "pcm" in msg:
                        pcm = np.frombuffer(base64.b64decode(msg["pcm"]), dtype=np.int16)
                        self._audio[msg["id"]] = pcm.astype(np.float32) / 32768
                    else:
                        self._audio[msg["id"]] = None  # synthesis failed: skip this sentence
                    self._cv.notify_all()
        self.error = "신경망 TTS 프로세스가 종료됨"
        self._ready.set()
        with self._cv:
            for i in self._order:
                self._audio.setdefault(i, None)
            self._cv.notify_all()

    # ------------------------------------------------------------- interface
    def say(self, text: str) -> None:
        text = spell_numbers(text).strip()
        if not text:
            return
        parts = [text]
        if self._first_in_turn:  # nothing queued: get the first words out sooner
            head, rest = first_chunk(text)
            parts = [head, rest] if rest else [head]
        self._first_in_turn = False
        for part in parts:
            self._send(part)

    def _send(self, text: str) -> None:
        with self._cv:
            self._next_id += 1
            rid = self._next_id
            self._order.append(rid)
        speed = max(0.75, min(1.3, 1 + 0.06 * (self.rate - self.base_rate)))
        self._write({"id": rid, "text": text, "exaggeration": self.exaggeration, "speed": round(speed, 2)})

    def _write(self, obj: dict) -> None:
        try:
            self._proc.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            self._proc.stdin.flush()
        except OSError:
            self.error = "신경망 TTS에 보낼 수 없음"

    def stop(self) -> None:
        with self._cv:
            dropped = self._next_id
            self._order.clear()
            self._audio.clear()
            self._abort = True
            self._first_in_turn = True
            self._cv.notify_all()
        self._write({"cancel_upto": dropped})

    def busy(self) -> bool:
        with self._cv:
            return bool(self._order) or self._playing

    def wait_done(self, cancel: threading.Event | None = None, timeout: float = 120) -> bool:
        deadline = time.monotonic() + timeout
        while self.busy() and time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                return False
            time.sleep(0.05)
        done = not self.busy()
        if done:
            self._first_in_turn = True
        return done

    def first_audio_after(self, t: float) -> float | None:
        """perf_counter time the first sentence after ``t`` actually started playing."""
        return next((s for s in self._play_starts if s >= t), None)

    def set_rate(self, rate: int) -> None:
        self.rate = max(-10, min(10, rate))

    def set_style(self, rate: int, pitch: int) -> None:  # noqa: ARG002 - pitch is the voice's own
        """Mood rate becomes the baseline (natural speed); only 천천히/빠르게 change speed from there."""
        self.base_rate = self.rate = rate

    def set_mood(self, mood: str | None) -> None:
        self.exaggeration = MOOD_EXAGGERATION.get(mood or "", 0.5)

    # ---------------------------------------------------------------- player
    def _play_loop(self) -> None:
        stream = sd.OutputStream(samplerate=self.sr, channels=1, dtype="float32", device=self.device)
        stream.start()
        while True:
            with self._cv:
                while not self._order or self._order[0] not in self._audio:
                    self._cv.wait(0.5)
                rid = self._order[0]
                audio = self._audio.pop(rid)
                self._playing = True
                self._abort = False
            if audio is not None:
                self._play_starts.append(time.perf_counter())
                for i in range(0, len(audio), BLOCK):
                    if self._abort:
                        break
                    stream.write(audio[i:i + BLOCK])
            with self._cv:
                if self._order and self._order[0] == rid:
                    self._order.popleft()
                self._playing = False
                self._cv.notify_all()
