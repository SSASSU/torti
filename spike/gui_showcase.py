"""GUI showcase without a microphone: open a demo project, put a board drawing on screen as a
reference, ask by typing "where is D3?", and screenshot once the answer and the location mark are in.

    .venv\\Scripts\\python spike\\gui_showcase.py <TORTI_DATA dir> <project folder> "<question>" <out.png>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

data_dir, project, question, out = sys.argv[1:5]
os.environ["TORTI_DATA"] = data_dir
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pointing_test import board  # noqa: E402
from torti.config import Settings  # noqa: E402
from torti.gui import MainWindow, apply_dark_theme  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ref = Path(project) / "refs" / "board.png"
    ref.parent.mkdir(exist_ok=True)
    cv2.imencode(".png", board()[0])[1].tofile(str(ref))  # tofile: Korean path safe

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    apply_dark_theme(app)
    win = MainWindow(Settings(image="never", mic="Wave:3", last_project=project), preview=False)
    win.show()
    seen: set[str] = set()

    def on_event(kind: str, data: dict) -> None:
        if kind == "ready":
            QTimer.singleShot(3000, lambda: (win.engine.set_reference(ref), win.engine.ask_text(question, True)))
        elif kind in ("visual", "turn"):
            seen.add(kind)
            if seen == {"visual", "turn"}:
                QTimer.singleShot(1200, shoot)
        elif kind == "fatal":
            print("fatal:", data)
            QTimer.singleShot(500, finish)

    def shoot() -> None:
        win.grab().save(out)
        print("saved", out)
        QTimer.singleShot(300, finish)

    def finish() -> None:
        win.quitting = True
        win.close()

    win.bridge.event.connect(on_event)
    QTimer.singleShot(180000, finish)  # safety net
    app.exec()


if __name__ == "__main__":
    main()
