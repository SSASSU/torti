"""Torti main window (PySide6, M1 skeleton).

Everything feeds one conversation: voice (hotkey/pedal/button), typed chat, the camera, reference
images, location marks drawn on them, the work project and its Claude Code sessions.
Layout: project bar on top; the view (camera / reference / marked image) on the left; the voice
state, conversation with a text box, briefing, log and settings on the right; push-to-talk below.
Placeholder icons are drawn in code until the set in docs/ICONS.md exists.
"""

from __future__ import annotations

import html
import math
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QBrush, QCloseEvent, QColor, QFont, QIcon, QImage, QPainter, QPainterPath, QPalette, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QProgressBar, QPushButton,
    QSizePolicy, QSplitter, QSystemTrayIcon, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from .config import Settings
from .engine import Engine
from .project import gh_available, known_projects, projects_dir

STATES = {  # state -> (label, color); colors follow docs/ICONS.md tokens (dark theme)
    "LOADING": ("준비 중", "#9CA3AF"),
    "IDLE": ("대기", "#9CA3AF"),
    "LISTENING": ("듣는 중", "#60A5FA"),
    "TRANSCRIBING": ("받아쓰는 중", "#FBBF24"),
    "THINKING": ("생각 중", "#FBBF24"),
    "SPEAKING": ("말하는 중", "#34D399"),
    "ANALYZING": ("작업 분석 중", "#A78BFA"),
    "ERROR": ("오류", "#F87171"),
}
MOOD_COLORS = {"차분": "#64748B", "진지": "#1E3A8A", "활기": "#F59E0B", "장난스러움": "#EC4899", "친근": "#10B981"}
MARK_COLOR = QColor("#F59E0B")
NO_PROJECT = "(작업 없음)"
VISUAL_SECONDS = 45

QSS = """
QWidget { color: #E5E7EB; font-size: 10pt; }
QMainWindow, QDialog { background: #111318; }
#Panel { background: #181B22; border: 1px solid #262A33; border-radius: 10px; }
#Title { font-size: 15pt; font-weight: 700; color: #F9FAFB; }
#Chip { border-radius: 9px; padding: 2px 10px; font-weight: 600; color: #F9FAFB; }
#StateText { font-size: 16pt; font-weight: 700; }
#Hint { color: #9CA3AF; }
#ViewCaption { color: #FCD34D; font-weight: 600; }
QPushButton { background: #232733; border: 1px solid #333846; border-radius: 7px; padding: 6px 12px; }
QPushButton:hover { background: #2B3040; }
QPushButton:pressed { background: #1E40AF; }
QPushButton:disabled { color: #4B5563; }
QPushButton#Talk { background: #1D4ED8; border: none; font-size: 12pt; font-weight: 700; padding: 12px; }
QPushButton#Talk:pressed { background: #2563EB; }
QComboBox, QLineEdit, QListWidget { background: #1F232D; border: 1px solid #333846; border-radius: 7px; padding: 5px 8px; }
QListWidget::item { padding: 6px; }
QListWidget::item:selected { background: #1E3A8A; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: #9CA3AF; padding: 7px 14px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #F9FAFB; border-bottom: 2px solid #60A5FA; }
QTextBrowser { background: transparent; border: none; }
QProgressBar { background: #1F232D; border: none; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #60A5FA; border-radius: 4px; }
QStatusBar { color: #9CA3AF; }
"""


def chip(color: str) -> str:
    return f"background:{color};"


def make_icon(color: str, size: int = 64) -> QIcon:
    """Placeholder app/tray icon: a rounded 'T' badge in the state color."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(2, 2, size - 4, size - 4), size * 0.28, size * 0.28)
    p.setPen(QColor("#0B0D12"))
    f = QFont("Segoe UI", int(size * 0.42))
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "T")
    p.end()
    return QIcon(pm)


def bgr_to_qimage(bgr: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888).copy()


def jpeg_to_qimage(jpeg: bytes) -> QImage:
    return bgr_to_qimage(cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR))


def draw_marks(img: QImage, marks: list[dict]) -> QPixmap:
    """Dim everything except the marked boxes, outline them, and label them (Korean-capable)."""
    pm = QPixmap.fromImage(img)
    w, h = pm.width(), pm.height()
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    rects = []
    for m in marks:
        x1, y1, x2, y2 = m["box"]
        pad = max(w, h) * 0.008
        rects.append(QRectF(x1 / 1000 * w - pad, y1 / 1000 * h - pad,
                            (x2 - x1) / 1000 * w + 2 * pad, (y2 - y1) / 1000 * h + 2 * pad))
    shade = QPainterPath()
    shade.addRect(QRectF(0, 0, w, h))
    for r in rects:
        hole = QPainterPath()
        hole.addRoundedRect(r, 8, 8)
        shade = shade.subtracted(hole)
    p.fillPath(shade, QColor(0, 0, 0, 120))
    stroke = max(3.0, max(w, h) / 320)
    font = QFont("Malgun Gothic")
    font.setPixelSize(int(max(16, h / 28)))
    font.setBold(True)
    p.setFont(font)
    for i, (r, m) in enumerate(zip(rects, marks), 1):
        p.setPen(QPen(MARK_COLOR, stroke))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 8, 8)
        text = f"{i}  {m.get('label') or ''}".strip()
        tw = p.fontMetrics().horizontalAdvance(text) + 18
        th = p.fontMetrics().height() + 8
        ty = r.top() - th - 4 if r.top() - th - 4 > 0 else r.bottom() + 4
        tag = QRectF(r.left(), ty, tw, th)
        p.setPen(Qt.NoPen)
        p.setBrush(MARK_COLOR)
        p.drawRoundedRect(tag, 6, 6)
        p.setPen(QColor("#111318"))
        p.drawText(tag, Qt.AlignCenter, text)
    p.end()
    return pm


class Bridge(QObject):
    """Engine callbacks arrive on worker threads; a queued signal brings them to the UI thread."""

    event = Signal(str, object)


class StateOrb(QWidget):
    """Large voice-state indicator: color per state, pulse while busy, ring shows mic level."""

    def __init__(self) -> None:
        super().__init__()
        self.state = "LOADING"
        self.level = 0.0
        self.phase = 0.0
        self.setMinimumSize(QSize(160, 160))
        self._timer = QTimer(self, interval=33, timeout=self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self.phase = (self.phase + 0.08) % (2 * math.pi)
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        color = QColor(STATES.get(self.state, ("", "#9CA3AF"))[1])
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        r = min(self.width(), self.height()) * 0.30
        busy = self.state not in ("IDLE", "LOADING")
        pulse = (math.sin(self.phase) + 1) / 2 if busy else 0.3
        glow = QColor(color)
        glow.setAlphaF(0.10 + 0.15 * pulse)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, r * (1.35 + 0.1 * pulse), r * (1.35 + 0.1 * pulse))
        if self.state == "LISTENING":
            ring = QColor(color)
            ring.setAlphaF(0.9)
            p.setPen(QPen(ring, 6))
            p.setBrush(Qt.NoBrush)
            extra = r * 0.45 * min(1.0, self.level)
            p.drawEllipse(c, r + 10 + extra, r + 10 + extra)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(c, r, r)
        dark = QColor("#0B0D12")
        if self.state in ("THINKING", "TRANSCRIBING", "ANALYZING"):
            for i in range(3):
                dot = QColor(dark)
                dot.setAlphaF(0.35 + 0.65 * ((math.sin(self.phase * 2 - i * 0.9) + 1) / 2))
                p.setBrush(dot)
                p.drawEllipse(QPointF(c.x() + (i - 1) * r * 0.42, c.y()), r * 0.12, r * 0.12)
        elif self.state == "SPEAKING":
            p.setPen(QPen(dark, 4, Qt.SolidLine, Qt.RoundCap))
            for i in range(5):
                hgt = r * (0.25 + 0.45 * abs(math.sin(self.phase * 3 + i)))
                x = c.x() + (i - 2) * r * 0.22
                p.drawLine(QPointF(x, c.y() - hgt / 2), QPointF(x, c.y() + hgt / 2))
        elif self.state == "LISTENING":
            p.setPen(QPen(dark, 5, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(c.x() - r * 0.16, c.y() - r * 0.42, r * 0.32, r * 0.56), r * 0.16, r * 0.16)
            p.drawArc(QRectF(c.x() - r * 0.32, c.y() - r * 0.2, r * 0.64, r * 0.5), 180 * 16, 180 * 16)
            p.drawLine(QPointF(c.x(), c.y() + r * 0.3), QPointF(c.x(), c.y() + r * 0.45))
        p.end()


class NewProjectDialog(QDialog):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("새 작업")
        self.name = QLineEdit(placeholderText="예: 원목 스피커 박스")
        self.remote = QLineEdit(placeholderText="https://github.com/<user>/<repo>.git (비워 두면 로컬만)")
        self.github = QCheckBox("gh CLI로 비공개 저장소 자동 생성")
        self.github.setEnabled(gh_available())
        if not self.github.isEnabled():
            self.github.setToolTip("gh CLI가 없거나 로그인되지 않았습니다")
        form = QFormLayout(self)
        form.addRow("작업 이름", self.name)
        form.addRow("GitHub 저장소", self.remote)
        form.addRow("", self.github)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(520, 0)


class SessionDialog(QDialog):
    """Pick a Claude Code session recorded in this work folder to continue (voice or typed)."""

    def __init__(self, parent: QWidget, sessions: list, folder: Path) -> None:
        super().__init__(parent)
        self.setWindowTitle("세션 불러오기")
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"작업 폴더: {folder}", objectName="Hint", wordWrap=True))
        self.list = QListWidget()
        first = QListWidgetItem("새 Torti 대화 (세션 없이 시작)")
        first.setData(Qt.UserRole, None)
        self.list.addItem(first)
        for s in sessions:
            item = QListWidgetItem(f"{s.modified:%m-%d %H:%M} · {s.user_turns}턴 · {s.title}")
            item.setData(Qt.UserRole, s)
            self.list.addItem(item)
        self.list.setCurrentRow(1 if sessions else 0)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        v.addWidget(self.list, 1)
        self.edits = QCheckBox("이 세션에서 작업 폴더 파일 수정 허용 (읽기는 항상 허용)")
        v.addWidget(self.edits)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)
        self.resize(680, 420)

    def chosen(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, preview: bool = True) -> None:
        super().__init__()
        self.settings = settings
        self.preview_enabled = preview  # camera preview runs even when photos aren't sent
        self.bridge = Bridge()
        self.bridge.event.connect(self.on_event)
        self.engine = Engine(settings, lambda kind, data: self.bridge.event.emit(kind, data))
        self.ready = False
        self.quitting = False
        self.entries: list[dict] = []  # conversation: {"role": "me"|"torti"|"cmd", "text", "meta"}
        self.reference_image: QImage | None = None
        self.visual: QPixmap | None = None
        self.visual_until = 0.0
        self.setWindowTitle("Torti")
        self.setWindowIcon(make_icon("#60A5FA"))
        self.resize(1320, 820)
        self._build()
        self._build_tray()
        self._preview = QTimer(self, interval=66, timeout=self._update_view)
        self._preview.start()
        threading.Thread(target=self._boot, daemon=True).start()

    # ----------------------------------------------------------------- layout
    def _build(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(14, 12, 14, 8)
        outer.setSpacing(10)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Torti", objectName="Title"))
        bar.addSpacing(12)
        bar.addWidget(QLabel("작업"))
        self.project_box = QComboBox(minimumWidth=230)
        self.project_box.activated.connect(self._project_chosen)
        bar.addWidget(self.project_box)
        self.btn_new = QPushButton("새 작업", clicked=self._new_project)
        self.btn_clone = QPushButton("GitHub에서 이어서", clicked=self._clone_project)
        self.btn_folder = QPushButton("폴더 열기", clicked=self._open_folder)
        self.btn_sync = QPushButton("⟳ 동기화", clicked=lambda: self._bg(self.engine.sync))
        for b in (self.btn_new, self.btn_clone, self.btn_folder, self.btn_sync):
            bar.addWidget(b)
        bar.addStretch(1)
        self.domain_chip = QLabel("", objectName="Chip")
        self.mood_chip = QLabel("", objectName="Chip")
        self.session_chip = QLabel("", objectName="Chip")
        self.sync_chip = QLabel("", objectName="Chip")
        for w in (self.domain_chip, self.mood_chip, self.session_chip, self.sync_chip):
            w.hide()
            bar.addWidget(w)
        outer.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(10)

        left = QFrame(objectName="Panel")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(10, 10, 10, 10)
        self.view_caption = QLabel("", objectName="ViewCaption", wordWrap=True)
        self.view_caption.hide()
        lv.addWidget(self.view_caption)
        self.view = QLabel("카메라 준비 중", alignment=Qt.AlignCenter)
        self.view.setMinimumSize(QSize(480, 270))
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view.setStyleSheet("background:#0B0D12; border-radius:8px; color:#6B7280;")
        lv.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("마이크"))
        self.mic_meter = QProgressBar(maximum=100, textVisible=False)
        row.addWidget(self.mic_meter, 1)
        row.addSpacing(8)
        row.addWidget(QLabel("사진"))
        self.image_mode = QComboBox()
        for key, label in (("auto", "자동 (이거·방금·어디)"), ("always", "항상 보내기"), ("never", "보내지 않기")):
            self.image_mode.addItem(label, key)
        self.image_mode.setCurrentIndex(max(0, self.image_mode.findData(self.settings.image)))
        self.image_mode.currentIndexChanged.connect(self._image_mode_changed)
        row.addWidget(self.image_mode)
        self.btn_ref = QPushButton("자료 띄우기", clicked=self._open_reference)
        self.btn_ref.setToolTip("회로도·핀배치·도면 이미지를 띄우면 질문과 위치 표시가 그 자료 기준으로 바뀝니다")
        self.btn_live = QPushButton("실시간 보기", clicked=self._back_to_live)
        row.addWidget(self.btn_ref)
        row.addWidget(self.btn_live)
        lv.addLayout(row)
        split.addWidget(left)

        right = QFrame(objectName="Panel")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(12, 10, 12, 10)
        top = QHBoxLayout()
        self.orb = StateOrb()
        self.orb.setFixedSize(QSize(150, 150))
        top.addWidget(self.orb)
        sv = QVBoxLayout()
        sv.addStretch(1)
        self.state_text = QLabel("준비 중", objectName="StateText")
        self.state_hint = QLabel("음성 인식 모델과 장치를 불러오는 중", objectName="Hint", wordWrap=True)
        self.next_step = QLabel("", wordWrap=True)
        self.next_step.setStyleSheet("color:#D1D5DB;")
        sv.addWidget(self.state_text)
        sv.addWidget(self.state_hint)
        sv.addSpacing(6)
        sv.addWidget(self.next_step)
        sv.addStretch(1)
        top.addLayout(sv, 1)
        rv.addLayout(top)

        self.tabs = QTabWidget()
        chat_tab = QWidget()
        cv = QVBoxLayout(chat_tab)
        cv.setContentsMargins(0, 6, 0, 0)
        self.chat = QTextBrowser(openExternalLinks=True)
        cv.addWidget(self.chat, 1)
        inp = QHBoxLayout()
        self.input = QLineEdit(placeholderText="말하기 어려우면 여기에 입력 (Enter)")
        self.input.returnPressed.connect(self._send_text)
        self.btn_send = QPushButton("보내기", clicked=self._send_text)
        self.speak_text = QCheckBox("소리로도 답")
        self.speak_text.setChecked(self.settings.text_speaks)
        self.speak_text.toggled.connect(lambda on: setattr(self.settings, "text_speaks", on))
        self.btn_session = QPushButton("세션…", clicked=self._choose_session)
        self.btn_session.setToolTip("이 작업 폴더에서 쓰던 Claude Code 세션을 불러와 이어서 대화")
        inp.addWidget(self.input, 1)
        for w in (self.btn_send, self.speak_text, self.btn_session):
            inp.addWidget(w)
        cv.addLayout(inp)
        self.brief_view = QTextBrowser()
        self.log_view = QTextBrowser()
        self.log_view.setStyleSheet("font-family: Consolas, 'D2Coding', monospace; font-size: 9pt; color:#9CA3AF;")
        self.tabs.addTab(chat_tab, "대화")
        self.tabs.addTab(self.brief_view, "브리핑")
        self.tabs.addTab(self.log_view, "로그")
        self.tabs.addTab(self._settings_tab(), "설정")
        rv.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([660, 640])
        outer.addWidget(split, 1)

        controls = QHBoxLayout()
        self.btn_talk = QPushButton(f"누르고 말하기   ·   {self.settings.hotkey.upper()} / 페달", objectName="Talk")
        self.btn_talk.pressed.connect(self.engine.press)
        self.btn_talk.released.connect(self.engine.release)
        self.btn_stop = QPushButton("■ 멈춤", clicked=lambda: self.engine.run_command("stop", "버튼"))
        self.btn_repeat = QPushButton("↺ 다시 말해줘", clicked=lambda: self.engine.run_command("repeat", "버튼"))
        self.btn_newchat = QPushButton("＋ 새 대화", clicked=lambda: self._bg(self.engine.new_conversation))
        self.btn_reanalyze = QPushButton("작업 다시 분석", clicked=lambda: self._bg(self.engine.reanalyze))
        controls.addWidget(self.btn_talk, 1)
        for b in (self.btn_stop, self.btn_repeat, self.btn_newchat, self.btn_reanalyze):
            controls.addWidget(b)
        outer.addLayout(controls)
        self.setCentralWidget(root)
        self._ui_ready(False)
        self.statusBar().showMessage("시작 중…")
        self._refresh_projects()
        self._render_chat()
        self._render_brief(None)

    def _ui_ready(self, on: bool) -> None:
        for w in (self.btn_talk, self.btn_stop, self.btn_repeat, self.btn_newchat, self.btn_reanalyze,
                  self.btn_send, self.input, self.btn_session, self.btn_ref, self.btn_live, self.project_box,
                  self.btn_new, self.btn_clone, self.btn_folder, self.btn_sync):
            w.setEnabled(on)

    def _settings_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        s = self.settings
        rows = [
            ("트리거", f"{s.hotkey.upper()} (탭: 자동 종료 / 0.4초 이상 누르면 뗄 때 종료)"),
            ("마이크", s.mic or "시스템 기본"), ("스피커", s.speaker or "시스템 기본"),
            ("카메라", s.camera or "자동 (가상 카메라 제외)"),
            ("대화 모델", f"{s.model} · effort {s.effort}"),
            ("작업 분석 / 위치 표시 모델", f"{s.brief_model} / {s.pointer_model}"),
            ("음성 인식", f"{s.stt_model} · beam {s.beam}"),
            ("VAD", f"민감도 {s.vad} · 무음 기준 rms {s.min_rms} · 끝 감지 {s.end_silence_ms}ms"),
            ("사진 전송 크기", f"긴 변 {s.long_edge}px (자료 이미지는 1568px)"),
            ("사진 저장소 업로드", "켬" if s.push_photos else "끔 (로컬에만)"),
        ]
        for k, v in rows:
            label = QLabel(v)
            label.setStyleSheet("color:#D1D5DB;")
            form.addRow(QLabel(k), label)
        form.addRow(QLabel("설정 편집 화면은 다음 단계에서 붙입니다. 지금은 실행 인자와 settings.json으로 바꿉니다.",
                           objectName="Hint", wordWrap=True))
        return w

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(make_icon(STATES["LOADING"][1]), self)
        menu = QMenu()
        menu.addAction(QAction("열기", self, triggered=self._show))
        menu.addAction(QAction("GitHub 동기화", self, triggered=lambda: self._bg(self.engine.sync)))
        menu.addSeparator()
        menu.addAction(QAction("종료", self, triggered=self._quit))
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self._show() if r == QSystemTrayIcon.Trigger else None)
        self.tray.setToolTip("Torti · 준비 중")
        self.tray.show()

    # -------------------------------------------------------------- lifecycle
    def _boot(self) -> None:
        try:
            self.engine.load(open_camera=self.preview_enabled)
            self.engine.open_project(**self._project_args(self.settings.last_project))
            self.engine.start()
        except Exception as e:  # noqa: BLE001
            self.bridge.event.emit("fatal", {"text": str(e)})

    @staticmethod
    def _project_args(target: str | None) -> dict:
        """last_project / combo value -> open_project kwargs (Torti project name or any folder)."""
        if not target:
            return {}
        path = Path(target)
        if path.is_absolute():
            if not path.is_dir():
                return {}
            inside = path.resolve().parent == projects_dir().resolve()  # resolve: PURURO~1 vs pururoong
            return {"name": path.name} if inside else {"folder": path}
        return {"name": target} if (projects_dir() / target).is_dir() else {}

    def _show(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self) -> None:
        self.quitting = True
        self.close()

    def closeEvent(self, e: QCloseEvent) -> None:  # noqa: N802
        if not self.quitting and self.tray.isVisible():  # FR-72: keep running in the tray
            self.hide()
            self.tray.showMessage("Torti", "트레이에서 계속 듣고 있어요.", make_icon("#60A5FA"), 2500)
            e.ignore()
            return
        self._preview.stop()
        self.settings.save()
        self.engine.shutdown()
        self.tray.hide()
        e.accept()
        QApplication.quit()

    # ---------------------------------------------------------------- actions
    def _bg(self, fn, *args, **kwargs) -> None:
        def job() -> None:
            try:
                fn(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                self.bridge.event.emit("error", {"text": str(e)})

        threading.Thread(target=job, daemon=True).start()

    def _switch(self, **kwargs) -> None:
        if self.engine.state != "IDLE":
            self.statusBar().showMessage("대화 중에는 작업을 바꿀 수 없어요", 4000)
            return
        self._bg(self.engine.open_project, **kwargs)

    def _refresh_projects(self, current: str | None = None) -> None:
        self.project_box.blockSignals(True)
        self.project_box.clear()
        self.project_box.addItem(NO_PROJECT, None)
        for name, path in known_projects().items():
            self.project_box.addItem(name, str(path))
            if current and Path(current).resolve() == path.resolve():
                self.project_box.setCurrentIndex(self.project_box.count() - 1)
        self.project_box.blockSignals(False)

    def _project_chosen(self, _index: int) -> None:
        self._switch(**self._project_args(self.project_box.currentData()))

    def _new_project(self) -> None:
        dlg = NewProjectDialog(self)
        if dlg.exec() == QDialog.Accepted and dlg.name.text().strip():
            self._switch(new=dlg.name.text().strip(), remote=dlg.remote.text().strip() or None,
                         github=dlg.github.isChecked())

    def _clone_project(self) -> None:
        url, ok = QInputDialog.getText(self, "GitHub에서 이어서", "저장소 URL")
        if ok and url.strip():
            self._switch(clone=url.strip())

    def _open_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "작업 폴더 열기 (Claude Code로 쓰던 폴더도 그대로)")
        if path:
            self._switch(folder=path)

    def _choose_session(self) -> None:
        dlg = SessionDialog(self, self.engine.list_sessions(), self.engine.cwd)
        if dlg.exec() == QDialog.Accepted:
            self._bg(self.engine.load_session, dlg.chosen(), dlg.edits.isChecked())

    def _send_text(self) -> None:
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.engine.ask_text(text, self.speak_text.isChecked())

    def _open_reference(self) -> None:
        start = str(self.engine.cwd)
        path, _ = QFileDialog.getOpenFileName(self, "자료 이미지 띄우기", start,
                                              "이미지 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            self._bg(self.engine.set_reference, path)

    def _back_to_live(self) -> None:
        self.visual = None
        self._bg(self.engine.set_reference, None)

    def _image_mode_changed(self) -> None:
        self.settings.image = self.image_mode.currentData()

    # ---------------------------------------------------------------- updates
    def _show_pixmap(self, pm: QPixmap) -> None:
        self.view.setPixmap(pm.scaled(self.view.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _update_view(self) -> None:
        if self.ready and hasattr(self.engine, "rec"):
            db = 20 * math.log10(max(self.engine.rec.level, 1e-6))
            self.mic_meter.setValue(int(max(0, min(100, (db + 60) * 2))))
            self.orb.level = max(0.0, min(1.0, (db + 50) / 35))
        if self.visual is not None and time.monotonic() < self.visual_until:
            self._show_pixmap(self.visual)
            return
        if self.visual is not None:  # marks expired
            self.visual = None
            self._caption(None)
        if self.reference_image is not None:
            self._show_pixmap(QPixmap.fromImage(self.reference_image))
            return
        cam = self.engine.camera
        frame = cam.snapshot() if cam else None
        if frame is None:
            return
        w, h = self.view.width(), self.view.height()
        fh, fw = frame.shape[:2]
        scale = min(w / fw, h / fh)
        frame = cv2.resize(frame, (max(1, int(fw * scale)), max(1, int(fh * scale))), interpolation=cv2.INTER_AREA)
        self.view.setPixmap(QPixmap.fromImage(bgr_to_qimage(frame)))

    def _caption(self, text: str | None) -> None:
        if text:
            self.view_caption.setText(text)
            self.view_caption.show()
        elif self.reference_image is not None:
            self.view_caption.setText("자료 보는 중 · 질문과 위치 표시가 이 자료 기준입니다")
            self.view_caption.show()
        else:
            self.view_caption.hide()

    def on_event(self, kind: str, data: dict) -> None:  # noqa: C901 - one switch for all engine events
        if kind == "log":
            self.log_view.append(f"[{time.strftime('%H:%M:%S')}] {html.escape(data['text'])}")
        elif kind == "state":
            self._set_state(data["state"])
        elif kind == "ready":
            self.ready = True
            self._ui_ready(True)
            if self.engine.camera is None:
                self.view.setText("카메라 미리보기 꺼짐" if not self.preview_enabled else "카메라 없음 · 사진 없이 대화")
            self.statusBar().showMessage(
                f"STT {self.engine.stt.device.upper()} · {self.engine.stt.model_name} · 대화 {self.settings.model}")
            self.entries.append({"role": "torti", "text": data["greeting"], "meta": "인사"})
            self._render_chat()
        elif kind == "cli":
            if not data.get("ok"):
                self.state_hint.setText(data.get("error", "Claude CLI 문제"))
        elif kind == "project":
            self.settings.last_project = data["root"]
            self._refresh_projects(data["root"])
            if not data["is_repo"]:
                self._set_sync_chip("git 아님", "#4B5563")
            elif not data["has_remote"]:
                self._set_sync_chip("로컬만", "#4B5563")
            else:
                self._set_sync_chip(None, "")
        elif kind == "brief":
            self._render_brief(data["brief"])
            if not self.engine.project:
                self.settings.last_project = None
                self._refresh_projects()
                self._set_sync_chip(None, "")
            self.entries.clear()
            self._render_chat()
        elif kind == "session":
            if data["id"]:
                self.session_chip.setText(f"세션: {data['title'][:18]}{' · 수정 허용' if data['edits'] else ''}")
                self.session_chip.setStyleSheet(chip("#6D28D9"))
                self.session_chip.show()
                self.entries.append({"role": "cmd", "text": data["title"], "meta": "세션 불러옴"})
            else:
                self.session_chip.hide()
                if self.ready:
                    self.entries.append({"role": "cmd", "text": "새 대화", "meta": "대화 초기화"})
            self._render_chat()
        elif kind == "heard":
            if self.visual is not None:
                self.visual = None
                self._caption(None)
            src = "입력" if data["source"] == "text" else f"STT {data['stt_ms']}ms"
            self.entries.append({"role": "me", "text": data["text"], "meta": src})
            self._render_chat()
        elif kind == "delta":
            if self.entries and self.entries[-1]["role"] == "torti" and self.entries[-1].get("open"):
                self.entries[-1]["text"] += data["text"]
            else:
                self.entries.append({"role": "torti", "text": data["text"].lstrip(), "meta": "", "open": True})
            self._render_chat()
        elif kind == "turn":
            if self.entries and self.entries[-1].get("open"):
                self.entries[-1]["open"] = False
                lat = data["latency_ms"]
                first = lat.get("speech_end_to_first_audio")
                meta = ("끼어들어 중단" if data["interrupted"] else
                        f"첫 음성 {first / 1000:.1f}초" if first else
                        f"첫 글자 {lat['cli_first_token'] / 1000:.1f}초" if lat.get("cli_first_token") else "")
                if data.get("image"):
                    meta += " · 사진 첨부"
                self.entries[-1]["meta"] = meta
                self._render_chat()
            lat = data["latency_ms"]
            parts = [f"{name} {lat[key]}ms" for key, name in
                     (("stt", "STT"), ("cli_first_token", "첫 토큰"), ("speech_end_to_first_audio", "말 끝→첫 음성"))
                     if lat.get(key) is not None]
            self.statusBar().showMessage(" · ".join(parts + [f"모델 {data.get('model')}"]))
        elif kind == "command":
            self.entries.append({"role": "cmd", "text": f"{data['cmd']} · {data['text']}", "meta": "명령"})
            self._render_chat()
        elif kind == "visual":
            self.visual = draw_marks(jpeg_to_qimage(data["jpeg"]), data["marks"])
            self.visual_until = time.monotonic() + VISUAL_SECONDS
            labels = ", ".join(f"{i} {m['label']}" for i, m in enumerate(data["marks"], 1))
            self._caption(f"표시: {labels}  ·  {data['source']}  ·  {data['seconds']}초")
            self.entries.append({"role": "cmd", "text": labels, "meta": "화면에 위치 표시"})
            self._render_chat()
        elif kind == "reference":
            self.reference_image = jpeg_to_qimage(data["jpeg"]) if data.get("path") else None
            self._caption(None)
            if data.get("path"):
                self.entries.append({"role": "cmd", "text": Path(data["path"]).name, "meta": "자료 띄움"})
                self._render_chat()
        elif kind == "sync":
            if data.get("running"):
                self._set_sync_chip("동기화 중…", "#B45309")
            elif data.get("ok"):
                self._set_sync_chip("● 동기화됨", "#047857")
            else:
                self._set_sync_chip("동기화 실패", "#B91C1C")
                self.statusBar().showMessage(data.get("message", "")[-200:], 8000)
        elif kind in ("error", "fatal"):
            self.statusBar().showMessage(f"오류: {data['text']}", 10000)
            self.log_view.append(f"<span style='color:#F87171'>오류: {html.escape(data['text'])}</span>")
            if kind == "fatal":
                self._set_state("ERROR")
                self.state_hint.setText(data["text"])

    def _set_state(self, state: str) -> None:
        label, color = STATES.get(state, (state, "#9CA3AF"))
        self.orb.state = state
        self.state_text.setText(label)
        self.state_text.setStyleSheet(f"color:{color};")
        hints = {
            "IDLE": f"{self.settings.hotkey.upper()}나 페달을 누르고 말하세요. 말하기 어려우면 아래에 입력해도 됩니다.",
            "LISTENING": "말씀하세요. 다시 누르거나 손을 떼면 끝납니다.",
            "THINKING": "작업 브리핑을 보고 답을 만드는 중",
            "SPEAKING": "누르면 끊고 새 질문을 들어요",
            "ANALYZING": "작업 저장소를 읽기 전용으로 살펴보는 중",
        }
        if state in hints:
            self.state_hint.setText(hints[state])
        self.tray.setIcon(make_icon(color))
        self.tray.setToolTip(f"Torti · {label}")

    def _set_sync_chip(self, text: str | None, color: str) -> None:
        if not text:
            self.sync_chip.hide()
            return
        self.sync_chip.setText(text)
        self.sync_chip.setStyleSheet(chip(color))
        self.sync_chip.show()

    def _render_chat(self) -> None:
        parts = []
        for e in self.entries:
            text = html.escape(e["text"]).replace("\n", "<br>")
            meta = html.escape(e.get("meta") or "")
            if e["role"] == "me":
                parts.append(
                    "<table width='100%' cellspacing='0' cellpadding='0'><tr><td width='22%'></td>"
                    "<td style='background:#1E3A8A; padding:8px 12px;'>"
                    f"<span style='color:#BFDBFE; font-size:8pt;'>나 · {meta}</span><br>{text}</td></tr></table>")
            elif e["role"] == "torti":
                parts.append(
                    "<table width='100%' cellspacing='0' cellpadding='0'><tr>"
                    "<td style='background:#1F2937; padding:8px 12px;'>"
                    f"<span style='color:#6EE7B7; font-size:8pt;'>토르티{' · ' + meta if meta else ''}</span><br>"
                    f"{text}</td><td width='22%'></td></tr></table>")
            else:
                parts.append(f"<p align='center' style='color:#FCD34D; font-size:8pt;'>{meta} · {text}</p>")
        if not parts:
            parts.append("<p style='color:#6B7280;'>아직 대화가 없어요.</p>")
        self.chat.setHtml("<div style='line-height:150%;'>" + "<br>".join(parts) + "</div>")
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())

    def _render_brief(self, b: dict | None) -> None:
        if not b:
            self.domain_chip.hide()
            self.mood_chip.hide()
            self.next_step.setText("")
            self.brief_view.setHtml(
                "<h3>연결된 작업이 없어요</h3><p style='color:#9CA3AF'>위에서 작업을 고르거나, 새 작업을 만들거나, "
                "Claude Code로 쓰던 폴더를 열면 저장소를 분석해 분야, 진행 상황, 다음 단계, 말투를 정합니다.</p>")
            return
        self.domain_chip.setText(b.get("domain") or "분야 미정")
        self.domain_chip.setStyleSheet(chip("#374151"))
        self.domain_chip.show()
        mood = b.get("mood", "")
        self.mood_chip.setText(f"{mood} · {b.get('speech_level', '')}")
        self.mood_chip.setStyleSheet(chip(MOOD_COLORS.get(mood, "#4B5563")))
        self.mood_chip.show()
        steps = b.get("next_steps") or []
        self.next_step.setText(f"다음 단계: {steps[0]}" if steps else "")

        def items(xs: list[str], color: str = "#E5E7EB") -> str:
            return "".join(f"<li style='color:{color}; margin:2px 0'>{html.escape(x)}</li>" for x in xs) or "<li>-</li>"

        subtitle = " · ".join(html.escape(x) for x in (b.get("domain"), b.get("assistant_role")) if x)
        self.brief_view.setHtml(
            f"<h2 style='margin:0'>{html.escape(b.get('title', ''))}</h2>"
            + (f"<p style='color:#9CA3AF'>{subtitle}</p>" if subtitle else "") +
            f"<p>{html.escape(b.get('summary', ''))}</p>"
            f"<h4>진행 상황</h4><p>{html.escape(b.get('status', ''))}</p>"
            f"<h4>다음 단계</h4><ol>{items(steps)}</ol>"
            f"<h4>핵심 사실</h4><ul>{items(b.get('key_facts') or [])}</ul>"
            f"<h4>주의</h4><ul>{items(b.get('cautions') or [], '#FCA5A5')}</ul>"
            f"<h4>말투</h4><p>{html.escape(mood)}, {html.escape(b.get('speech_level', ''))}. "
            f"{html.escape(b.get('tone', ''))}</p>"
            f"<p style='color:#6B7280; font-size:8pt'>음성 인식 용어: {html.escape(', '.join(b.get('vocabulary') or []))}</p>")


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in ((QPalette.Window, "#111318"), (QPalette.Base, "#181B22"), (QPalette.Text, "#E5E7EB"),
                        (QPalette.WindowText, "#E5E7EB"), (QPalette.Button, "#232733"),
                        (QPalette.ButtonText, "#E5E7EB"), (QPalette.Highlight, "#2563EB"),
                        (QPalette.HighlightedText, "#FFFFFF"), (QPalette.ToolTipBase, "#1F232D"),
                        (QPalette.ToolTipText, "#E5E7EB"), (QPalette.PlaceholderText, "#6B7280")):
        pal.setColor(role, QColor(color))
    app.setPalette(pal)
    app.setFont(QFont("Malgun Gothic", 10))
    app.setStyleSheet(QSS)


def run(settings: Settings) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    apply_dark_theme(app)
    win = MainWindow(settings)
    win.show()
    return app.exec()
