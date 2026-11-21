"""Open the GUI on a demo project, run one real turn from a synthesized question, save a screenshot.

    .venv\\Scripts\\python spike\\gui_screenshot.py <TORTI_DATA dir> <project name> "<question>" <out.png>

Camera is off (image=never) so nobody at the desk ends up in the picture.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

data_dir, project, question, out = sys.argv[1:5]
os.environ["TORTI_DATA"] = data_dir
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from torti.audio import Utterance  # noqa: E402
from torti.config import Settings  # noqa: E402
from torti.gui import MainWindow, apply_dark_theme  # noqa: E402


def synth(text: str) -> np.ndarray:
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    path = Path(tempfile.gettempdir()) / "torti_gui_q.wav"
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    fmt = win32com.client.Dispatch("SAPI.SpAudioFormat")
    fmt.Type = 18
    stream.Format = fmt
    stream.Open(str(path), 3)
    voice = win32com.client.Dispatch("SAPI.SpVoice")
    voice.AudioOutputStream = stream
    voice.Speak(text)
    stream.Close()
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    apply_dark_theme(app)
    win = MainWindow(Settings(image="never", mic="Wave:3", last_project=project), preview=False)
    win.show()
    audio = synth(question)

    def on_event(kind: str, data: dict) -> None:
        if kind == "ready":
            def turn() -> None:
                time.sleep(4)  # let the greeting finish
                now = time.perf_counter()
                win.engine.rec.listen = lambda **_kw: Utterance(audio, now - 2, now, now + 0.7, 0.2, False)
                win.engine.run_turn(time.perf_counter())
            threading.Thread(target=turn, daemon=True).start()
        elif kind == "turn":
            QTimer.singleShot(1500, shoot)
        elif kind == "fatal":
            print("fatal:", data)
            QTimer.singleShot(500, finish)

    def shoot() -> None:
        win.grab().save(out)
        print("saved", out)
        win.tabs.setCurrentIndex(1)  # briefing tab
        QTimer.singleShot(300, shoot_brief)

    def shoot_brief() -> None:
        path = out.replace(".png", "_brief.png")
        win.grab().save(path)
        print("saved", path)
        QTimer.singleShot(300, finish)

    def finish() -> None:
        win.quitting = True
        win.close()

    win.bridge.event.connect(on_event)
    QTimer.singleShot(120000, finish)  # safety net
    app.exec()


if __name__ == "__main__":
    main()
