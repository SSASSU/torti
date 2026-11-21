"""Neural TTS trial: Chatterbox Multilingual (MIT) in Korean, one sample per mood. Runs in .venv-tts.

    .venv-tts\\Scripts\\python spike\\tts_lab_chatterbox.py <out_dir> [reference.wav]

Writes chatterbox_<mood>.wav and prints load time, synthesis time and real-time factor.
"""

from __future__ import annotations

import os
import sys
import time
import wave
from pathlib import Path

_CACHE = Path(__file__).resolve().parents[1] / ".cache"  # models stay in the project folder
os.environ.setdefault("HF_HOME", str(_CACHE / "huggingface"))
os.environ.setdefault("TORCH_HOME", str(_CACHE / "torch"))
os.environ.setdefault("PKUSEG_HOME", str(_CACHE / "pkuseg"))  # chatterbox's Chinese segmenter data
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

import numpy as np  # noqa: E402
import torch  # noqa: E402
from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # noqa: E402

# Real answers from the demo projects, one per mood. exaggeration: emotion intensity (0.25..2).
SAMPLES = {
    "lively": ("좋아요! 이제 LED 열여섯 개를 달 차례예요. 긴 다리가 플러스 쪽인 것만 확인해 주세요.", 0.75),
    "serious": ("좋습니다. 먼저 전원 플러그가 뽑혀 있는지 확인해 주세요. 변압기 일차측 절연 확인은 끝나셨나요?", 0.35),
    "friendly": ("우퍼 구멍 지름은 백이십팔 밀리미터예요. 트위터 쪽은 기록이 없으니 규격서를 확인해 보세요.", 0.5),
}


def save(path: Path, audio: np.ndarray, sr: int) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    ref = sys.argv[2] if len(sys.argv) > 2 else None
    print("cuda:", torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else "")
    t = time.perf_counter()
    model = ChatterboxMultilingualTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
    print(f"load {time.perf_counter() - t:.1f}s, sr={model.sr}")
    model.generate("준비.", language_id="ko")  # warm-up
    for mood, (text, exaggeration) in SAMPLES.items():
        t = time.perf_counter()
        wav = model.generate(text, language_id="ko", audio_prompt_path=ref, exaggeration=exaggeration, cfg_weight=0.5)
        secs = time.perf_counter() - t
        audio = wav.squeeze().detach().cpu().numpy().astype(np.float32)
        dur = len(audio) / model.sr
        name = f"chatterbox_{mood}{'_ref' if ref else ''}.wav"
        save(out / name, audio, model.sr)
        print(f"{name}: synth {secs:.2f}s for {dur:.2f}s audio (RTF {secs / dur:.2f})")
    print(f"vram peak {torch.cuda.max_memory_allocated() / 2**30:.1f} GiB" if torch.cuda.is_available() else "")


if __name__ == "__main__":
    main()
