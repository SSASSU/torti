"""Local speech-to-text with faster-whisper (GPU when available)."""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

from .cuda_dlls import add_nvidia_dll_dirs

# Vocabulary hint (FR-26). With a project, Brief.stt_prompt() replaces this with the project's own terms.
DEFAULT_PROMPT = "작업 중 질문. 토르티."

# Phrases Whisper tends to hallucinate from noise or silence in Korean.
_HALLUCINATIONS = (
    "시청해주셔서 감사합니다",
    "시청해 주셔서 감사합니다",
    "구독과 좋아요",
    "MBC 뉴스",
    "다음 영상에서 만나요",
)


@dataclass
class SttResult:
    text: str
    seconds: float
    language_probability: float


class WhisperStt:
    def __init__(
        self,
        model: str = "large-v3-turbo",
        device: str = "auto",
        compute_type: str = "auto",
        beam_size: int = 1,
        initial_prompt: str | None = DEFAULT_PROMPT,
    ) -> None:
        add_nvidia_dll_dirs()
        import ctranslate2
        from faster_whisper import WhisperModel

        if device == "auto":
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        if compute_type == "auto":
            compute_type = "float16" if device == "cuda" else "int8"
        if device == "cpu" and model.startswith("large"):
            model = "small"  # CPU fallback per requirements: small + int8
        self.model_name, self.device, self.compute_type = model, device, compute_type
        self.beam_size = beam_size
        self.initial_prompt = initial_prompt
        self._model = WhisperModel(model, device=device, compute_type=compute_type)

    def warmup(self) -> float:
        t = time.perf_counter()
        self.transcribe(np.zeros(16000, dtype=np.float32))
        return time.perf_counter() - t

    def transcribe(self, audio: np.ndarray) -> SttResult:
        """``audio``: mono float32 in [-1, 1] at 16 kHz."""
        t = time.perf_counter()
        segments, info = self._model.transcribe(
            audio,
            language="ko",
            beam_size=self.beam_size,
            initial_prompt=self.initial_prompt,
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=False,  # audio is already endpointed by our VAD
        )
        text = "".join(s.text for s in segments).strip()
        if any(h in text for h in _HALLUCINATIONS):
            text = ""
        return SttResult(text, time.perf_counter() - t, info.language_probability)
