"""M0 console: the voice engine without a GUI.

    .venv\\Scripts\\python spike\\m0_console.py --mic "Wave:3" [--project NAME | --new NAME --remote URL | --clone URL]

Tap the hotkey (default F9; a USB pedal mapped to that key works the same) and speak, or hold it
while speaking and let go. Press while it answers to interrupt. Ctrl+C quits (and pushes the log).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from torti.config import Settings, build_parser  # noqa: E402
from torti.engine import Engine  # noqa: E402
from torti.project import list_projects  # noqa: E402


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def console_emit(kind: str, data: dict) -> None:
    if kind == "log":
        log(data["text"])
    elif kind == "state":
        log(f"--> {data['state']}")
    elif kind == "say":
        log(f"🔊 {data['text']}")
    elif kind == "ready":
        log(f"준비 완료. [{data['hotkey']}] 탭 후 말하기(끝은 자동 감지) 또는 누른 채로 말하고 떼기. 종료: Ctrl+C")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser("Torti M0 console").parse_args()
    if args.list:
        print("\n".join(list_projects()) or "(작업 없음)")
        return
    engine = Engine(Settings().apply_args(args), console_emit)
    try:
        engine.load()
        engine.open_project(new=args.new, remote=args.remote, github=args.github, clone=args.clone,
                            name=args.project, reanalyze=args.reanalyze)
    except (RuntimeError, FileExistsError, FileNotFoundError, LookupError) as e:
        engine.shutdown()
        raise SystemExit(f"시작 실패: {e}") from None
    engine.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        log("종료합니다")
    finally:
        engine.shutdown()


if __name__ == "__main__":
    main()
