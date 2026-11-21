"""Settings shared by the console and the GUI; the GUI remembers them in settings.json."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, fields

from .paths import data_dir


@dataclass
class Settings:
    hotkey: str = "f9"
    mic: str | None = None
    speaker: str | None = None
    camera: str | None = None
    image: str = "auto"  # auto | always | never
    long_edge: int = 1280
    model: str = "haiku"
    effort: str = "low"
    stt_model: str = "large-v3-turbo"
    beam: int = 1
    vad: int = 2
    min_rms: float = 0.003
    end_silence_ms: int = 700
    tts_rate: int | None = None  # None: follow the project's mood
    tts_engine: str = "chatterbox"  # chatterbox (natural male voice, .venv-tts) | sapi (Windows Heami)
    brief_model: str = "sonnet"
    pointer_model: str = "sonnet"  # marks locations on photos; measured 4/4 hits, ~2s
    push_photos: bool = False
    last_project: str | None = None  # project name or folder path
    text_speaks: bool = False  # answers to typed questions are also spoken

    @classmethod
    def load(cls) -> Settings:
        try:
            data = json.loads((data_dir() / "settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    def save(self) -> None:
        (data_dir() / "settings.json").write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2),
                                                  encoding="utf-8")

    def apply_args(self, args: argparse.Namespace) -> Settings:
        """Command-line values override saved ones when given."""
        for f in fields(self):
            value = getattr(args, f.name, None)
            if value is not None and value is not False:
                setattr(self, f.name, value)
        return self


def build_parser(description: str = "Torti") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--hotkey", help="트리거 키 (페달을 이 키로 매핑). 기본 f9")
    ap.add_argument("--mic", help="마이크 이름 일부, 예: 'Wave:3' (기본: 시스템 기본)")
    ap.add_argument("--speaker", help="출력 장치 이름 일부 (기본: 시스템 기본)")
    ap.add_argument("--camera", help="카메라 이름 일부 (기본: 가상 카메라가 아닌 첫 장치)")
    ap.add_argument("--image", choices=("auto", "always", "never"),
                    help="사진 전송: auto=질문에 '이거/방금/보여' 등이 있을 때만")
    ap.add_argument("--long-edge", type=int, help="전송 이미지 긴 변 픽셀 (기본 1280)")
    ap.add_argument("--model", help="Claude CLI 모델 haiku/sonnet/opus (기본 haiku)")
    ap.add_argument("--effort")
    ap.add_argument("--stt-model")
    ap.add_argument("--beam", type=int)
    ap.add_argument("--vad", type=int, choices=(0, 1, 2, 3), help="VAD 민감도 (3=소음에 가장 엄격)")
    ap.add_argument("--min-rms", type=float, help="이 RMS 미만은 무음 취급 (기본 0.003)")
    ap.add_argument("--end-silence-ms", type=int, help="이만큼 조용하면 발화 끝 (기본 700)")
    ap.add_argument("--tts-rate", type=int, help="SAPI 속도 -10..10 (기본: 작업 분위기에 맞춤)")
    ap.add_argument("--tts-engine", choices=("chatterbox", "sapi"),
                    help="목소리: chatterbox(자연스러운 남성, 기본) / sapi(Windows 기본 음성)")
    g = ap.add_argument_group("작업(GitHub 연동)")
    g.add_argument("--new", metavar="NAME", help="새 작업 시작")
    g.add_argument("--remote", metavar="URL", help="--new와 함께: 미리 만든 빈 GitHub 저장소 URL")
    g.add_argument("--github", action="store_true", help="--new와 함께: gh CLI로 비공개 저장소 자동 생성")
    g.add_argument("--clone", metavar="URL", help="GitHub 저장소에서 작업 이어서 하기")
    g.add_argument("--project", metavar="NAME", help="로컬 작업 이어서 하기 (pull 후 시작)")
    g.add_argument("--push-photos", action="store_true", help="사진도 저장소에 올리기 (기본: 로컬에만)")
    g.add_argument("--brief-model", help="작업 분석에 쓸 모델 (기본 sonnet, 바뀐 파일이 있을 때만 실행)")
    g.add_argument("--reanalyze", action="store_true", help="캐시를 무시하고 작업 다시 분석")
    g.add_argument("--list", action="store_true", help="로컬 작업 목록 보기")
    return ap
