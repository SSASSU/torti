"""Local record of every turn: question, photo, answer, timings (FR-60)."""

from __future__ import annotations

import json
import time
from pathlib import Path


class History:
    def __init__(self, root: Path) -> None:
        self.dir = root / time.strftime("%Y%m%d-%H%M%S")
        self.dir.mkdir(parents=True, exist_ok=True)
        self._log = self.dir / "log.jsonl"
        self._n = 0

    def next_id(self) -> int:
        self._n += 1
        return self._n

    def save_image(self, turn_id: int, jpeg: bytes, suffix: str = "") -> str:
        path = self.dir / f"turn-{turn_id:03d}{suffix}.jpg"
        path.write_bytes(jpeg)
        return path.name

    def save_wav(self, turn_id: int, audio, sample_rate: int = 16000) -> str:
        """Keep the utterance for VAD/STT tuning (local only)."""
        import wave

        import numpy as np

        path = self.dir / f"turn-{turn_id:03d}.wav"
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(pcm.tobytes())
        return path.name

    def append(self, record: dict) -> None:
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **record}
        with self._log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
