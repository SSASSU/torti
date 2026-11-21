r"""Design preview without devices or models: a desk photo as the camera, a demo briefing and chat,
each voice state, zoom, marks, the safety banner, the large view and the mini window, saved as PNGs.

    .venv\Scripts\python spike\gui_design_preview.py desk.jpg out_dir
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("TORTI_DATA", tempfile.mkdtemp(prefix="torti-preview-"))  # don't touch real settings

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from torti.camera import read_image  # noqa: E402
from torti.config import Settings  # noqa: E402
from torti.gui import MainWindow, apply_dark_theme, draw_marks, bgr_to_qimage  # noqa: E402

BRIEF = {
    "title": "아케이드 스틱 배선", "domain": "전자 · 아케이드 컨트롤러", "assistant_role": "배선 도우미",
    "summary": "Brook 보드에 버튼 8개와 레버를 배선하는 작업.", "status": "버튼 4개 배선 끝, 레버 배선 전",
    "next_steps": ["레버 커넥터 5핀을 보드 J2에 꽂기", "버튼 5~8 배선", "USB로 연결해 입력 테스트"],
    "key_facts": ["보드: Brook FIGHTING Gen-5X", "버튼은 GND 공통"], "cautions": ["배선 중에는 USB를 뽑아 두기"],
    "mood": "차분", "speech_level": "존댓말", "tone": "짧고 차분하게", "vocabulary": ["Brook", "J2", "GND"],
}


class FakeCam:
    name = "Elgato Facecam MK.2"

    def __init__(self, frame) -> None:
        self.frame = frame

    def snapshot(self):
        return self.frame.copy()

    def close(self) -> None:
        pass

    def recent_frames(self, n: int = 8):
        return [self.frame]


def main() -> None:
    desk, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    MainWindow._boot = lambda self: None  # no devices, no models
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    apply_dark_theme(app)
    win = MainWindow(Settings(image="auto"))
    frame = read_image(desk)
    win.engine.camera = FakeCam(frame)
    win._ui_ready(True)
    win._render_brief(BRIEF)
    win.domain_chip.show()
    win._set_sync_chip("동기화됨", "#4FD1A1")
    win.entries = [
        {"role": "torti", "text": "아케이드 스틱 배선 이어서 할게요. 레버 커넥터부터 꽂으면 돼요.", "meta": "인사"},
        {"role": "me", "text": "보드에 뭐라고 써 있어?", "meta": "STT 151ms"},
        {"role": "torti", "text": "Brook FIGHTING, 그 아래 Gen-5X라고 써 있어요. 작은 글씨는 안 읽혀요.",
         "meta": "첫 음성 2.9초 · 사진 첨부"},
        {"role": "cmd", "text": "보드", "meta": "확대 2.6배"},
        {"role": "me", "text": "J2가 어디야?", "meta": "STT 132ms"},
        {"role": "torti", "text": "보드 오른쪽 위 5핀 자리예요. 화면에 표시했어요.", "meta": "첫 음성 1.4초 · 사진 첨부"},
    ]
    win._render_chat()
    win.resize(1440, 900)
    win.show()

    def state(s: str, level: float = 0.0):
        def f():
            win._set_state(s)
            win.orb.level = level
        return f

    def zoom_in():
        win.engine.zoom.zoom_at(2.6, 0.52, 0.36)

    def zoom_out():
        win.engine.zoom.reset()

    def marks():
        h, w = frame.shape[:2]
        win.visual = draw_marks(bgr_to_qimage(frame), [{"box": (545, 300, 600, 345), "label": "J2"},
                                                       {"box": (480, 320, 535, 420), "label": "보드"}])
        win.visual_until = time.monotonic() + 60
        win._caption("표시: 1 J2, 2 보드  ·  사진  ·  1.0초")

    def banner():
        win.visual = None
        win._caption(None)
        win._warn("작업 전에 USB를 뽑아 두세요. 전원이 들어간 채로 핀을 꽂으면 단락 위험이 있어요.")

    def focus(on: bool):
        return lambda: win.btn_focus.setChecked(on)

    def mini():
        win.mini.set_state("SPEAKING")
        win.mini.set_line("보드 오른쪽 위 5핀 자리예요. 화면에 표시했어요.")
        win.mini.move(80, 80)
        win.mini.show()

    shots = [
        ("1_idle", state("IDLE")),
        ("2_listening", state("LISTENING", 0.75)),
        ("3_thinking_zoom", lambda: (state("THINKING")(), zoom_in())),
        ("4_speaking_marks", lambda: (zoom_out(), state("SPEAKING")(), marks())),
        ("5_safety_banner", lambda: (state("SPEAKING")(), banner())),
        ("6_focus_listening", lambda: (state("LISTENING", 0.6)(), focus(True)())),
        ("7_mini", lambda: (focus(False)(), mini())),
    ]

    def run(i: int = 0) -> None:
        if i == len(shots):
            win.mini.grab().save(str(out / "7_mini_only.png"))
            win.quitting = True
            win.close()
            return
        name, action = shots[i]
        action()

        def grab() -> None:
            win.grab().save(str(out / f"{name}.png"))
            print("saved", name, flush=True)
            run(i + 1)

        QTimer.singleShot(900, grab)

    QTimer.singleShot(800, run)
    QTimer.singleShot(60000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
