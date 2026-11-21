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
import re
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QBrush, QCloseEvent, QColor, QConicalGradient, QFont, QIcon, QImage, QPainter, QPainterPath, QPalette,
    QFontMetricsF, QKeySequence, QPen, QPixmap, QRadialGradient, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMenu, QPushButton,
    QSizePolicy, QSplitter, QSystemTrayIcon, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from .config import Settings
from .engine import Engine
from .project import gh_available, known_projects, projects_dir

# Look: a workbench tool, not a sci-fi HUD. Warm graphite, one orange accent, hardware-key buttons,
# small letter-spaced Latin labels (Teenage Engineering), dot-matrix meters (Nothing), state shown as a
# thin light around the camera view (Siri edge light, toned down), a glanceable NOW/NEXT card (HUDWAY),
# a safety banner over the view (car HUD), live-view chips (Bambu Studio), a mini companion window
# (ChatGPT desktop), soft matte orb (voice-orb references). No neon, glow halos, scanlines or grids.
C = {
    "bg": "#121212", "panel": "#1A1A1A", "card": "#202020", "line": "#2A2A2A", "line2": "#363636",
    "text": "#ECEAE5", "dim": "#8E8B85", "faint": "#5F5C57", "accent": "#FF6A13", "amber": "#F5B83D",
    "mint": "#4FD1A1", "red": "#FF5A4F", "lilac": "#B4A0FF", "ink": "#0E0E0E", "dot": "#2C2C2C",
}
LATIN = "Bahnschrift"  # DIN-like, ships with Windows; Korean text stays in Malgun Gothic
STATES = {  # state -> (label, color)
    "LOADING": ("준비 중", C["faint"]),
    "IDLE": ("대기", "#9A968F"),
    "LISTENING": ("듣는 중", C["accent"]),
    "TRANSCRIBING": ("받아쓰는 중", C["amber"]),
    "THINKING": ("생각 중", C["amber"]),
    "SPEAKING": ("말하는 중", C["mint"]),
    "ANALYZING": ("작업 분석 중", C["lilac"]),
    "ERROR": ("오류", C["red"]),
}
MOOD_COLORS = {"차분": "#8FA3B8", "진지": "#6C8EF5", "활기": "#F5B83D", "장난스러움": "#F07FB5", "친근": "#4FD1A1"}
MARK_COLOR = QColor(C["accent"])
NO_PROJECT = "(작업 없음)"
VISUAL_SECONDS = 45
BANNER_SECONDS = 12
SAFETY = re.compile(r"화상|감전|단락|합선|쇼트|위험|조심|뜨거|환기|연기|불꽃|보안경|장갑|베일|끼일|전원.{0,6}(끄|뽑|차단)")

QSS = f"""
QWidget {{ color: {C['text']}; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {C['bg']}; }}
#Panel {{ background: {C['panel']}; border: 1px solid #242424; border-radius: 14px; }}
#Card {{ background: {C['card']}; border: 1px solid {C['line']}; border-radius: 12px; }}
#Wordmark {{ font-family: {LATIN}; font-size: 15pt; font-weight: 700; letter-spacing: 4px; color: {C['text']}; }}
#Tag {{ font-family: {LATIN}; font-size: 8pt; letter-spacing: 2px; color: {C['dim']}; }}
#Chip {{ border-radius: 10px; padding: 3px 10px; color: {C['text']}; background: #242424; border: 1px solid {C['line']}; }}
#StateText {{ font-size: 18pt; font-weight: 700; }}
#Hint {{ color: {C['dim']}; }}
#NowText {{ font-size: 14pt; font-weight: 700; color: {C['text']}; }}
#NextText {{ color: #B9B5AE; }}
#Caution {{ color: {C['amber']}; }}
QPushButton {{ background: #232323; border: 1px solid #333333; border-bottom: 2px solid #0A0A0A;
    border-radius: 8px; padding: 6px 12px; }}
QPushButton:hover {{ background: #2A2A2A; }}
QPushButton:pressed {{ background: #1C1C1C; border-bottom: 1px solid #0A0A0A; padding-top: 7px; }}
QPushButton:disabled {{ color: #555555; }}
QPushButton:checked {{ background: #2E2118; border-color: {C['accent']}; }}
QPushButton#Talk {{ background: {C['accent']}; color: #161009; border: none; border-bottom: 3px solid #A94300;
    border-radius: 12px; font-size: 13pt; font-weight: 800; padding: 12px 18px; }}
QPushButton#Talk:pressed {{ background: #FF7F36; border-bottom: 1px solid #A94300; padding-top: 14px; }}
QPushButton#Talk:disabled {{ background: #3A2A20; color: #7A6A60; border-bottom-color: #261A12; }}
QPushButton#Key {{ font-family: {LATIN}; font-size: 11pt; padding: 4px 0; }}
QComboBox, QLineEdit, QListWidget {{ background: #161616; border: 1px solid #303030; border-radius: 8px; padding: 6px 9px; }}
QLineEdit:focus {{ border: 1px solid {C['accent']}; }}
QListWidget::item {{ padding: 6px; }}
QListWidget::item:selected {{ background: #2E2118; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {C['dim']}; padding: 7px 14px; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {C['text']}; border-bottom: 2px solid {C['accent']}; }}
QTextBrowser {{ background: transparent; border: none; }}
QSplitter::handle {{ background: transparent; }}
QStatusBar {{ color: #6F6C66; font-family: Consolas; font-size: 8.5pt; }}
QToolTip {{ background: {C['card']}; color: {C['text']}; border: 1px solid #333333; padding: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2E2E2E; border-radius: 4px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px; border: 1px solid #444; background: #161616; }}
QCheckBox::indicator:checked {{ background: {C['accent']}; border-color: {C['accent']}; }}
"""


def dot_text(color: str, text: str) -> str:
    """Chip text with a small colored dot in front (rich text)."""
    return f"<span style='color:{color}'>●</span>&nbsp; {html.escape(text)}"


_T_GLYPH = ("11111", "00100", "00100", "00100", "00100")


def make_icon(color: str, size: int = 64) -> QIcon:
    """Placeholder app/tray icon until docs/ICONS.md exists: a dot-matrix 'T' lit in the state color."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(C["bg"]))
    p.drawRoundedRect(QRectF(1, 1, size - 2, size - 2), size * 0.26, size * 0.26)
    step, r = size / 6.2, size * 0.062
    for y, row in enumerate(_T_GLYPH):
        for x, bit in enumerate(row):
            p.setBrush(QColor(color) if bit == "1" else QColor("#2A2A2A"))
            p.drawEllipse(QPointF(size * 0.19 + x * step, size * 0.19 + y * step), r * (1.25 if bit == "1" else 1), r * (1.25 if bit == "1" else 1))
    p.end()
    return QIcon(pm)


def mini_label(text: str) -> QLabel:
    """Small letter-spaced Latin label (NOW, NEXT, MIC...)."""
    return QLabel(text, objectName="Tag")


class DotMeter(QWidget):
    """Level as a row of dots, dot-matrix style (mic input; zoom factor)."""

    def __init__(self, dots: int = 24, color: str = C["accent"]) -> None:
        super().__init__()
        self.dots, self.color, self.level = dots, color, 0.0
        self.setFixedHeight(14)
        self.setMinimumWidth(dots * 9)
        self.setMaximumWidth(dots * 11)

    def set_level(self, level: float) -> None:
        level = max(0.0, min(1.0, level))
        if abs(level - self.level) > 0.01:
            self.level = level
            self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        gap = self.width() / self.dots
        lit = round(self.level * self.dots)
        for i in range(self.dots):
            p.setBrush(QColor(self.color) if i < lit else QColor(C["dot"]))
            p.drawEllipse(QPointF(gap * (i + 0.5), self.height() / 2), 2.6, 2.6)
        p.end()


def bgr_to_qimage(bgr: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format_RGB888).copy()


def jpeg_to_qimage(jpeg: bytes) -> QImage:
    return bgr_to_qimage(cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR))


class ZoomView(QLabel):
    """The view; on the live camera the wheel zooms at the cursor, dragging moves, double-click shows all."""

    wheel = Signal(float, float, float)  # u, v in the shown image (0..1), wheel steps
    drag = Signal(float, float)  # movement as fractions of the shown image
    reset = Signal()

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last: QPointF | None = None
        # overlay drawn over the picture (set by the window each frame)
        self.state, self.level, self.phase = "LOADING", 0.0, 0.0
        self.source: tuple[str, str] | None = None  # (dot color, "LIVE · Elgato Facecam MK.2")
        self.zoom = 1.0
        self.caption = ""
        self.banner, self.banner_until = "", 0.0
        self._latin = QFont(LATIN)
        self._latin.setPixelSize(12)
        self._latin.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        self._ko = QFont("Malgun Gothic")
        self._ko.setPixelSize(13)
        self._ko_bold = QFont(self._ko)
        self._ko_bold.setBold(True)

    def paintEvent(self, e) -> None:  # noqa: N802
        super().paintEvent(e)
        r = self._image_rect()
        if r is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._edge(p, r)
        x = r.left() + 12
        if self.source:
            x += self._pill(p, x, r.top() + 12, self.source[1], self.source[0], self._latin) + 8
        if self.state in ("LISTENING", "THINKING", "TRANSCRIBING", "SPEAKING", "ANALYZING"):
            label, color = STATES[self.state]
            self._pill(p, x, r.top() + 12, label, color, self._ko)
        if self.zoom > 1.01:
            text = f"ZOOM {self.zoom:.1f}×"
            w = self._pill_width(text, self._latin, dots=4)
            self._pill(p, r.right() - 12 - w, r.top() + 12, text, None, self._latin, dots=(4, round(self.zoom)))
        if self.caption:
            self._pill(p, r.left() + 12, r.bottom() - 12 - 28, self.caption, C["amber"], self._ko)
        if self.banner and time.monotonic() < self.banner_until:
            self._banner(p, r)
        p.end()

    def _edge(self, p: QPainter, r: QRectF) -> None:
        """State as a thin light around the picture (seen from the corner of the eye while working)."""
        if self.state in ("IDLE", "LOADING"):
            return
        strong = QColor(STATES.get(self.state, ("", C["dim"]))[1])
        soft = QColor(strong)
        width = 3.0
        if self.state == "LISTENING":
            width = 2.5 + 5.0 * self.level
            soft.setAlphaF(0.55)
        elif self.state == "SPEAKING":
            strong.setAlphaF(0.55 + 0.35 * (math.sin(self.phase * 1.6) + 1) / 2)
            soft = QColor(strong)
        else:  # thinking-like: a brighter stretch travels around the frame
            soft.setAlphaF(0.12)
        grad = QConicalGradient(r.center(), -math.degrees(self.phase) % 360)
        grad.setColorAt(0.0, strong)
        grad.setColorAt(0.5, soft)
        grad.setColorAt(1.0, strong)
        p.setPen(QPen(QBrush(grad), width))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(width / 2, width / 2, -width / 2, -width / 2), 10, 10)

    @staticmethod
    def _pill_width(text: str, font: QFont, dot: bool = False, dots: int = 0) -> float:

        return QFontMetricsF(font).horizontalAdvance(text) + 22 + (14 if dot else 0) + (dots * 9 + 6 if dots else 0)

    def _pill(self, p: QPainter, x: float, y: float, text: str, dot: str | None, font: QFont,
              dots: tuple[int, int] | None = None) -> float:
        w = self._pill_width(text, font, bool(dot), dots[0] if dots else 0)
        box = QRectF(x, y, w, 28)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(14, 14, 14, 200))
        p.drawRoundedRect(box, 14, 14)
        tx = x + 11
        if dot:
            p.setBrush(QColor(dot))
            p.drawEllipse(QPointF(tx + 4, y + 14), 4, 4)
            tx += 14
        p.setFont(font)
        p.setPen(QColor(C["text"]))
        p.drawText(QRectF(tx, y, w, 28), Qt.AlignVCenter | Qt.AlignLeft, text)
        if dots:

            dx = tx + QFontMetricsF(font).horizontalAdvance(text) + 10
            p.setPen(Qt.NoPen)
            for i in range(dots[0]):
                p.setBrush(QColor(C["accent"]) if i < dots[1] else QColor("#3A3A3A"))
                p.drawEllipse(QPointF(dx + i * 9, y + 14), 2.8, 2.8)
        return w

    def _banner(self, p: QPainter, r: QRectF) -> None:
        """Safety line from the answer, over the top of the picture (like a car HUD warning)."""

        w = min(r.width() - 40, 720)
        box = QRectF(r.center().x() - w / 2, r.top() + 52, w, 40)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(C["amber"]))
        p.drawRoundedRect(box, 10, 10)
        tri = QPainterPath()
        cx, cy = box.left() + 24, box.center().y()
        tri.moveTo(cx, cy - 9)
        tri.lineTo(cx + 10, cy + 8)
        tri.lineTo(cx - 10, cy + 8)
        tri.closeSubpath()
        p.setBrush(QColor("#1A1405"))
        p.drawPath(tri)
        p.setPen(QColor(C["amber"]))
        p.setFont(self._ko_bold)
        p.drawText(QRectF(cx - 10, cy - 7, 20, 16), Qt.AlignCenter, "!")
        p.setPen(QColor("#1A1405"))
        text = QFontMetricsF(self._ko_bold).elidedText(self.banner, Qt.ElideRight, box.width() - 60)
        p.drawText(box.adjusted(44, 0, -12, 0), Qt.AlignVCenter | Qt.AlignLeft, text)

    def _image_rect(self) -> QRectF | None:
        pm = self.pixmap()
        if pm is None or pm.isNull() or pm.width() < 2:
            return None
        return QRectF((self.width() - pm.width()) / 2, (self.height() - pm.height()) / 2, pm.width(), pm.height())

    def wheelEvent(self, e) -> None:  # noqa: N802 - Qt override
        r = self._image_rect()
        steps = e.angleDelta().y() / 120
        if r is not None and steps:
            p = e.position()
            self.wheel.emit(min(max((p.x() - r.x()) / r.width(), 0.0), 1.0),
                            min(max((p.y() - r.y()) / r.height(), 0.0), 1.0), steps)
        e.accept()

    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.LeftButton:
            self._last = e.position()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        r = self._image_rect()
        if self._last is not None and r is not None:
            d = e.position() - self._last
            self._last = e.position()
            self.drag.emit(d.x() / r.width(), d.y() / r.height())

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._last = None

    def mouseDoubleClickEvent(self, e) -> None:  # noqa: N802
        self.reset.emit()


def draw_zoom_hud(img: np.ndarray, full: np.ndarray, rect: tuple[float, float, float, float], factor: float) -> None:
    """On a zoomed view: a minimap of the whole desk at bottom right (the factor is an overlay pill)."""
    h, w = img.shape[:2]
    tw = max(120, w // 5)
    th = round(tw * full.shape[0] / full.shape[1])
    if tw + 24 > w or th + 24 > h:
        return
    thumb = cv2.resize(full, (tw, th), interpolation=cv2.INTER_AREA)
    thumb = (thumb * 0.75).astype(np.uint8)  # dim, so the window rectangle stands out
    x1, y1, x2, y2 = rect
    a, b = (round(x1 * tw), round(y1 * th)), (round(x2 * tw) - 1, round(y2 * th) - 1)
    thumb[a[1]:b[1], a[0]:b[0]] = (thumb[a[1]:b[1], a[0]:b[0]] / 0.75).clip(0, 255).astype(np.uint8)
    cv2.rectangle(thumb, a, b, (19, 106, 255), 2, cv2.LINE_AA)  # accent (BGR)
    ox, oy = w - tw - 12, h - th - 12
    img[oy:oy + th, ox:ox + tw] = thumb
    cv2.rectangle(img, (ox - 1, oy - 1), (ox + tw, oy + th), (70, 70, 70), 1)


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
    """Voice state as a soft, matte sphere (voice-orb references, kept calm): it swells with the voice
    while listening, a highlight drifts across it while thinking, and quiet rings leave it while
    speaking. Idle it rests dim. No glow halo."""

    def __init__(self, size: int = 150) -> None:
        super().__init__()
        self.state = "LOADING"
        self.level = 0.0
        self.phase = 0.0
        self.setFixedSize(QSize(size, size))
        self._timer = QTimer(self, interval=33, timeout=self._tick)
        self._timer.start()

    def _tick(self) -> None:
        self.phase = (self.phase + 0.06) % (2 * math.pi * 10)
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        base = QColor(STATES.get(self.state, ("", C["dim"]))[1])
        if self.state in ("IDLE", "LOADING"):
            base = QColor("#4A4743")
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        r = min(self.width(), self.height()) * 0.30
        if self.state == "LISTENING":
            r *= 1.0 + 0.16 * self.level
        elif self.state in ("IDLE", "LOADING"):
            r *= 0.97 + 0.03 * math.sin(self.phase * 0.5)
        p.setPen(Qt.NoPen)
        if self.state == "SPEAKING":  # rings moving out, fading
            for k in range(3):
                t = ((self.phase * 0.35 + k / 3) % 1.0)
                ring = QColor(base)
                ring.setAlphaF(0.35 * (1 - t))
                p.setPen(QPen(ring, 2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, r * (1.08 + 0.55 * t), r * (1.08 + 0.55 * t))
            p.setPen(Qt.NoPen)
        if self.state == "LISTENING":  # mic level ring, close to the sphere
            ring = QColor(base)
            ring.setAlphaF(0.25 + 0.5 * self.level)
            p.setPen(QPen(ring, 2 + 5 * self.level))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, r * 1.18, r * 1.18)
            p.setPen(Qt.NoPen)
        shadow = QColor(0, 0, 0, 90)  # contact shadow under the sphere: an object, not a light
        p.setBrush(shadow)
        p.drawEllipse(QPointF(c.x(), c.y() + r * 0.98), r * 0.7, r * 0.14)
        g = QRadialGradient(QPointF(c.x() - r * 0.35, c.y() - r * 0.45), r * 1.6)
        g.setColorAt(0.0, base.lighter(150))
        g.setColorAt(0.45, base)
        g.setColorAt(1.0, base.darker(260))
        p.setBrush(QBrush(g))
        p.drawEllipse(c, r, r)
        if self.state in ("THINKING", "TRANSCRIBING", "ANALYZING"):  # a highlight drifting around
            sweep = QConicalGradient(c, -math.degrees(self.phase * 1.4) % 360)
            hi = QColor(255, 255, 255, 70)
            sweep.setColorAt(0.0, hi)
            sweep.setColorAt(0.18, QColor(255, 255, 255, 0))
            sweep.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(sweep))
            p.drawEllipse(c, r, r)
        p.end()


class MiniWindow(QWidget):
    """Small always-on-top companion (ChatGPT desktop companion idea): state, Torti's last line and the
    talk key, so the main window can make room for other work (firmware, datasheets)."""

    def __init__(self, main: "MainWindow") -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.main = main
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag: QPointF | None = None
        frame = QFrame(self, objectName="Card")
        frame.setStyleSheet(f"#Card {{ background: {C['panel']}; border: 1px solid #333; border-radius: 16px; }}")
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)
        row = QHBoxLayout(frame)
        row.setContentsMargins(10, 8, 10, 8)
        self.orb = StateOrb(64)
        row.addWidget(self.orb)
        col = QVBoxLayout()
        top = QHBoxLayout()
        self.state = QLabel("대기")
        self.state.setStyleSheet("font-weight:700; font-size:11pt;")
        top.addWidget(self.state)
        top.addStretch(1)
        top.addWidget(mini_label("TORTI"))
        col.addLayout(top)
        self.line = QLabel("", wordWrap=True)
        self.line.setStyleSheet(f"color:{C['dim']};")
        self.line.setFixedWidth(250)
        col.addWidget(self.line)
        row.addLayout(col, 1)
        keys = QVBoxLayout()
        self.talk = QPushButton("말하기", objectName="Talk")
        self.talk.setStyleSheet("font-size:10pt; padding:8px 12px; border-radius:10px;")
        self.talk.pressed.connect(main.engine.press)
        self.talk.released.connect(main.engine.release)
        back = QPushButton("크게", clicked=main.leave_mini)
        back.setToolTip("큰 창으로 돌아가기")
        keys.addWidget(self.talk)
        keys.addWidget(back)
        row.addLayout(keys)
        self.resize(470, 96)

    def set_state(self, state: str) -> None:
        label, color = STATES.get(state, (state, C["dim"]))
        self.orb.state = state
        self.state.setText(label)
        self.state.setStyleSheet(f"font-weight:700; font-size:11pt; color:{color};")

    def set_line(self, text: str) -> None:
        text = " ".join(text.split())
        self.line.setText(text if len(text) <= 70 else "…" + text[-69:])

    def mousePressEvent(self, e) -> None:  # noqa: N802 - drag the frameless window around
        if e.button() == Qt.LeftButton:
            self._drag = e.globalPosition() - QPointF(self.pos())

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag is not None:
            self.move((e.globalPosition() - self._drag).toPoint())

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag = None


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
        self.visual_tag = "MARKED"  # or "LOOK": the crop Torti zoomed into by itself
        self.setWindowTitle("Torti")
        self.setWindowIcon(make_icon(C["accent"]))
        self.resize(1340, 840)
        self._build()
        self._build_tray()
        self.mini = MiniWindow(self)
        QShortcut(QKeySequence("F11"), self, activated=self.btn_focus.toggle)
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
        bar.setSpacing(8)
        bar.addWidget(QLabel("TORTI", objectName="Wordmark"))
        bar.addSpacing(14)
        bar.addWidget(mini_label("PROJECT"))
        self.project_box = QComboBox(minimumWidth=230)
        self.project_box.activated.connect(self._project_chosen)
        bar.addWidget(self.project_box)
        self.btn_new = QPushButton("새 작업", clicked=self._new_project)
        self.btn_clone = QPushButton("GitHub에서 이어서", clicked=self._clone_project)
        self.btn_folder = QPushButton("폴더 열기", clicked=self._open_folder)
        self.btn_folder.setToolTip("쓰던 작업 폴더(Claude Code 프로젝트 포함)를 열어 이어서 하기. 다시 열면 지난 대화가 이어져요")
        self.btn_reveal = QPushButton("탐색기", clicked=self._reveal)
        self.btn_reveal.setToolTip("지금 작업 폴더를 탐색기에서 보기")
        self.btn_sync = QPushButton("동기화", clicked=lambda: self._bg(self.engine.sync))
        for b in (self.btn_new, self.btn_clone, self.btn_folder, self.btn_reveal, self.btn_sync):
            bar.addWidget(b)
        bar.addStretch(1)
        self.domain_chip = QLabel("", objectName="Chip")
        self.mood_chip = QLabel("", objectName="Chip")
        self.session_chip = QLabel("", objectName="Chip")
        self.work_chip = QLabel("", objectName="Chip")
        self.sync_chip = QLabel("", objectName="Chip")
        for w in (self.domain_chip, self.mood_chip, self.session_chip, self.work_chip, self.sync_chip):
            w.hide()
            bar.addWidget(w)
        bar.addSpacing(6)
        self.btn_mini = QPushButton("미니 창", clicked=self.enter_mini)
        self.btn_mini.setToolTip("작은 창으로 줄여 다른 창 위에 띄워 두기 (펌웨어 짤 때)")
        bar.addWidget(self.btn_mini)
        outer.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(12)

        left = QFrame(objectName="Panel")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(10, 10, 10, 10)
        lv.setSpacing(8)
        self.view = ZoomView("카메라 준비 중", alignment=Qt.AlignCenter)
        self.view.setToolTip("휠: 확대·축소 · 끌기: 옮기기 · 두 번 클릭: 전체 화면\n"
                             "말로도 됩니다: \"확대해\", \"보드 확대해\", \"세 배 확대\", \"원래대로\"")
        self.view.wheel.connect(self._view_wheel)
        self.view.drag.connect(self._view_drag)
        self.view.reset.connect(self._view_reset)
        self.view.setMinimumSize(QSize(480, 270))
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view.setStyleSheet(f"background:{C['ink']}; border-radius:10px; color:{C['faint']};")
        lv.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(mini_label("MIC"))
        self.mic_meter = DotMeter(22)
        row.addWidget(self.mic_meter, 1)
        row.addSpacing(10)
        row.addWidget(mini_label("PHOTO"))
        self.image_mode = QComboBox()
        for key, label in (("auto", "자동 (이거·방금·어디)"), ("always", "항상 보내기"), ("never", "보내지 않기")):
            self.image_mode.addItem(label, key)
        self.image_mode.setCurrentIndex(max(0, self.image_mode.findData(self.settings.image)))
        self.image_mode.currentIndexChanged.connect(self._image_mode_changed)
        row.addWidget(self.image_mode)
        row.addSpacing(10)
        row.addWidget(mini_label("ZOOM"))
        for label, tip, fn in (("−", "축소", lambda: self._zoom_step(0.5)),
                               ("+", "확대 (휠로도 됩니다)", lambda: self._zoom_step(2.0)),
                               ("1×", "전체 화면 (두 번 클릭으로도 됩니다)", self._view_reset)):
            b = QPushButton(label, clicked=fn, objectName="Key")
            b.setToolTip(tip)
            b.setFixedWidth(38)
            row.addWidget(b)
        row.addSpacing(10)
        self.btn_ref = QPushButton("자료 띄우기", clicked=self._open_reference)
        self.btn_ref.setToolTip("회로도·핀배치·도면 이미지를 띄우면 질문과 위치 표시가 그 자료 기준으로 바뀝니다")
        self.btn_live = QPushButton("실시간 보기", clicked=self._back_to_live)
        self.btn_focus = QPushButton("크게 보기", checkable=True)
        self.btn_focus.setToolTip("오른쪽 패널을 접고 카메라를 크게 (F11). 상태는 화면 테두리 빛으로 보입니다")
        self.btn_focus.toggled.connect(self._toggle_focus)
        for b in (self.btn_ref, self.btn_live, self.btn_focus):
            row.addWidget(b)
        lv.addLayout(row)
        split.addWidget(left)

        right = QFrame(objectName="Panel")
        self.right = right
        rv = QVBoxLayout(right)
        rv.setContentsMargins(14, 12, 14, 10)
        rv.setSpacing(10)
        top = QHBoxLayout()
        self.orb = StateOrb(128)
        top.addWidget(self.orb)
        sv = QVBoxLayout()
        sv.setSpacing(2)
        sv.addStretch(1)
        sv.addWidget(mini_label("VOICE"))
        self.state_text = QLabel("준비 중", objectName="StateText")
        self.state_hint = QLabel("음성 인식 모델과 장치를 불러오는 중", objectName="Hint", wordWrap=True)
        sv.addWidget(self.state_text)
        sv.addWidget(self.state_hint)
        sv.addStretch(1)
        top.addLayout(sv, 1)
        rv.addLayout(top)

        # NOW / NEXT: readable at a glance from the workbench (HUDWAY idea)
        card = QFrame(objectName="Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 10, 14, 12)
        cl.setSpacing(3)
        head = QHBoxLayout()
        head.addWidget(mini_label("NOW"))
        head.addStretch(1)
        self.step_count = mini_label("")
        head.addWidget(self.step_count)
        cl.addLayout(head)
        self.now_text = QLabel("", objectName="NowText", wordWrap=True)
        cl.addWidget(self.now_text)
        cl.addSpacing(6)
        self.next_tag = mini_label("NEXT")
        cl.addWidget(self.next_tag)
        self.next_text = QLabel("", objectName="NextText", wordWrap=True)
        cl.addWidget(self.next_text)
        self.caution_text = QLabel("", objectName="Caution", wordWrap=True)
        cl.addWidget(self.caution_text)
        rv.addWidget(card)

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
        self.log_view.setStyleSheet(f"font-family: Consolas, 'D2Coding', monospace; font-size: 9pt; color:{C['dim']};")
        work_tab = QWidget()  # the worker session (worker.py): steps, result, commit
        wv = QVBoxLayout(work_tab)
        wv.setContentsMargins(0, 6, 0, 0)
        self.work_view = QTextBrowser()
        self.work_view.setStyleSheet(f"font-size: 9.5pt; color:{C['text']};")
        self.work_view.setHtml(
            f"<p style='color:{C['dim']}'>작업자가 아직 일을 받지 않았어요.<br>말로 \"버튼 매핑에 C 버튼 추가해줘\", "
            "\"빌드해봐\"처럼 시키면 작업 폴더에서 파일을 고치고 명령을 돌린 뒤, 끝나면 GitHub에 올립니다. "
            "\"작업 멈춰\", \"되돌려줘\"로 멈추거나 되돌릴 수 있어요.</p>")
        wv.addWidget(self.work_view, 1)
        wrow = QHBoxLayout()
        self.work_status = QLabel("대기", objectName="Hint")
        wrow.addWidget(self.work_status, 1)
        self.btn_work_stop = QPushButton("작업 멈춤", clicked=lambda: self._bg(self.engine.run_command, "work_stop", "버튼"))
        self.btn_work_undo = QPushButton("되돌리기", clicked=lambda: self._bg(self.engine.run_command, "work_undo", "버튼"))
        self.btn_work_undo.setToolTip("작업자의 마지막 커밋을 되돌리는 커밋을 만들고 GitHub에도 올립니다")
        wrow.addWidget(self.btn_work_stop)
        wrow.addWidget(self.btn_work_undo)
        wv.addLayout(wrow)
        self.tabs.addTab(chat_tab, "대화")
        self.tabs.addTab(work_tab, "작업")
        self.tabs.addTab(self.brief_view, "브리핑")
        self.tabs.addTab(self.log_view, "로그")
        self.tabs.addTab(self._settings_tab(), "설정")
        rv.addWidget(self.tabs, 1)
        split.addWidget(right)
        split.setSizes([840, 560])
        outer.addWidget(split, 1)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.btn_talk = QPushButton(f"누르고 말하기        {self.settings.hotkey.upper()}  ·  페달", objectName="Talk")
        self.btn_talk.pressed.connect(self.engine.press)
        self.btn_talk.released.connect(self.engine.release)
        self.btn_stop = QPushButton("멈춤", clicked=lambda: self.engine.run_command("stop", "버튼"))
        self.btn_repeat = QPushButton("다시 말해줘", clicked=lambda: self.engine.run_command("repeat", "버튼"))
        self.btn_newchat = QPushButton("새 대화", clicked=lambda: self._bg(self.engine.new_conversation))
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
        menu.addAction(QAction("미니 창", self, triggered=self.enter_mini))
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
            inside = path.resolve().parent == projects_dir().resolve()  # resolve: short (LONGNA~1) vs long Windows names
            return {"name": path.name} if inside else {"folder": path}
        return {"name": target} if (projects_dir() / target).is_dir() else {}

    def _show(self) -> None:
        self.mini.hide()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def enter_mini(self) -> None:
        """Shrink to the small always-on-top window at the bottom right of the screen."""
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        self.mini.move(screen.right() - self.mini.width() - 24, screen.bottom() - self.mini.height() - 24)
        self.mini.show()
        self.hide()

    def leave_mini(self) -> None:
        self._show()

    def _toggle_focus(self, on: bool) -> None:
        """Camera large: the right panel folds away; the state stays visible as the light around the view."""
        self.right.setVisible(not on)

    def _quit(self) -> None:
        self.quitting = True
        self.close()

    def closeEvent(self, e: QCloseEvent) -> None:  # noqa: N802
        if not self.quitting and self.tray.isVisible():  # FR-72: keep running in the tray
            self.hide()
            self.tray.showMessage("Torti", "트레이에서 계속 듣고 있어요.", make_icon(C["accent"]), 2500)
            e.ignore()
            return
        self.mini.hide()
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
        """Open a project at any time (a running answer is cut off); analysis shows on the orb."""
        self.statusBar().showMessage("작업 여는 중… 처음 여는 폴더는 분석에 10초쯤 걸려요", 8000)
        self._bg(self.engine.switch_project, **kwargs)

    def _reveal(self) -> None:
        """Show the current work folder in Explorer."""
        import os

        if self.engine.project:
            os.startfile(str(self.engine.project.root))  # noqa: S606 - local folder the user opened
        else:
            self.statusBar().showMessage("열린 작업이 없어요. 먼저 작업을 고르거나 폴더를 여세요", 5000)

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
            self.mic_meter.set_level((db + 60) / 50)
            self.orb.level = self.mini.orb.level = max(0.0, min(1.0, (db + 50) / 35))
        v = self.view  # overlay: state light, source, zoom
        v.state, v.level, v.phase = self.orb.state, self.orb.level, self.orb.phase
        cam = self.engine.camera
        v.zoom = 1.0
        if self.visual is not None and time.monotonic() < self.visual_until:
            v.source = (C["accent"], self.visual_tag)
            self._show_pixmap(self.visual)
            return
        if self.visual is not None:  # marks expired
            self.visual = None
            self._caption(None)
        if self.reference_image is not None:
            v.source = (C["amber"], "REFERENCE")
            self._show_pixmap(QPixmap.fromImage(self.reference_image))
            return
        v.source = (C["mint"], f"LIVE · {cam.name}" if cam and cam.name else "LIVE") if cam else None
        v.zoom = self.engine.zoom.factor
        full = cam.snapshot() if cam else None
        if full is None:
            if cam is not None and self.view.text() != "카메라 다시 연결하는 중…":
                self.view.setText("카메라 다시 연결하는 중…")  # unplugged or being moved
            return
        zoom = self.engine.zoom
        frame = zoom.crop(full)
        w, h = self.view.width(), self.view.height()
        fh, fw = frame.shape[:2]
        scale = min(w / fw, h / fh)
        frame = cv2.resize(frame, (max(1, int(fw * scale)), max(1, int(fh * scale))),
                           interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        if zoom.active:
            draw_zoom_hud(frame, full, zoom.rect(), zoom.factor)
        self.view.setPixmap(QPixmap.fromImage(bgr_to_qimage(frame)))

    # ------------------------------------------------------------------ zoom
    def _zoomable(self) -> bool:
        """Zoom applies to the live camera; marks shown over it are dropped so the zoom is visible."""
        if self.engine.camera is None or self.reference_image is not None:
            return False
        if self.visual is not None:
            self.visual = None
            self._caption(None)
        return True

    def _view_wheel(self, u: float, v: float, steps: float) -> None:
        if self._zoomable():
            self.engine.zoom.zoom_at(self.engine.zoom.factor * 1.25 ** steps, u, v)

    def _view_drag(self, du: float, dv: float) -> None:
        if self._zoomable() and self.engine.zoom.active:
            self.engine.zoom.pan(-du, -dv)

    def _view_reset(self) -> None:
        if self._zoomable():
            self.engine.zoom.reset()
            self.engine.zoom_changed("전체 화면")

    def _zoom_step(self, mult: float) -> None:
        if self._zoomable():
            self.engine.zoom.zoom_at(self.engine.zoom.factor * mult)
            self.engine.zoom_changed("버튼")

    def _caption(self, text: str | None) -> None:
        """Line at the bottom of the view (what the marks are, or that a reference is shown)."""
        if text:
            self.view.caption = text
        elif self.reference_image is not None:
            self.view.caption = "자료 보는 중 · 질문과 위치 표시가 이 자료 기준"
        else:
            self.view.caption = ""
        self.view.update()

    def _warn(self, text: str) -> None:
        """Safety sentence from an answer -> amber banner over the view for a while."""
        for sentence in re.split(r"(?<=[.!?。])\s+", text):
            if SAFETY.search(sentence):
                self.view.banner, self.view.banner_until = sentence.strip(), time.monotonic() + BANNER_SECONDS
                self.view.update()
                return

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
                self._set_sync_chip("git 아님", C["faint"])
            elif not data["has_remote"]:
                self._set_sync_chip("로컬만", C["faint"])
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
        elif kind == "work":
            self._on_work(data)
        elif kind == "session" and data.get("continued"):  # this project's conversation from last time
            self.session_chip.setText(dot_text(C["lilac"], "지난 대화 이어서"))
            self.session_chip.show()
            for role, text in data.get("history") or []:
                self.entries.append({"role": role, "text": text, "meta": "지난 대화"})
            self.entries.append({"role": "cmd", "text": "여기서부터 이어서", "meta": "지난 대화"})
            self._render_chat()
        elif kind == "session":
            if data["id"]:
                self.session_chip.setText(dot_text(C["lilac"], f"세션 {data['title'][:18]}"
                                                   f"{' · 수정 허용' if data['edits'] else ''}"))
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
            self.mini.set_line("나: " + data["text"])
            self._render_chat()
        elif kind == "delta":
            if self.entries and self.entries[-1]["role"] == "torti" and self.entries[-1].get("open"):
                self.entries[-1]["text"] += data["text"]
            else:
                self.entries.append({"role": "torti", "text": data["text"].lstrip(), "meta": "", "open": True})
            self.mini.set_line(self.entries[-1]["text"])
            self._render_chat()
        elif kind == "say":
            self._warn(data["text"])
        elif kind == "turn":
            if time.monotonic() > self.view.banner_until:  # typed answers are not spoken: check them here
                self._warn(data.get("answer") or "")
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
        elif kind == "zoom":  # voice zoom or self-zoom: show the live, zoomed view
            self.visual = None
            self._caption(None)
        elif kind == "peek":  # Torti zoomed in by itself: show what it looked at, briefly
            self.visual = QPixmap.fromImage(jpeg_to_qimage(data["jpeg"]))
            self.visual_until = time.monotonic() + 12
            self.visual_tag = "LOOK"
            self._caption(f"토르티가 확대해서 본 곳 · {data['label']} · {data['factor']}배")
        elif kind == "tool":
            self.state_hint.setText({"WebSearch": "인터넷에서 찾는 중", "WebFetch": "웹 페이지 읽는 중"}.get(
                data["name"], "작업 폴더 파일 확인 중"))
        elif kind == "visual":
            self.visual_tag = "MARKED"
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
                self._set_sync_chip("동기화 중…", C["amber"])
            elif data.get("ok"):
                self._set_sync_chip("동기화됨", C["mint"])
            else:
                self._set_sync_chip("동기화 실패", C["red"])
                self.statusBar().showMessage(data.get("message", "")[-200:], 8000)
        elif kind in ("error", "fatal"):
            self.statusBar().showMessage(f"오류: {data['text']}", 10000)
            self.log_view.append(f"<span style='color:{C['red']}'>오류: {html.escape(data['text'])}</span>")
            if kind == "fatal":
                self._set_state("ERROR")
                self.state_hint.setText(data["text"])

    def _set_state(self, state: str) -> None:
        label, color = STATES.get(state, (state, C["dim"]))
        self.orb.state = state
        self.mini.set_state(state)
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

    def _on_work(self, d: dict) -> None:
        """Worker progress (worker.py) -> 작업 tab, top chip, a line in the conversation."""
        phase = d.get("phase")
        icon = {"edit": "✎", "run": "$", "read": "·", "web": "⌕"}
        if phase == "start":
            self.work_view.clear()
            self.work_view.append(f"<p><span style='color:{C['accent']}'>▶ 지시</span>  {html.escape(d['instruction'])}</p>")
            self.work_chip.setText(dot_text(C["amber"], "작업 중"))
            self.work_chip.show()
            self.work_status.setText("작업 중")
            self.tabs.setTabText(1, "작업 ●")
            self.entries.append({"role": "cmd", "text": d["instruction"][:80], "meta": "작업자에게 맡김"})
            self._render_chat()
        elif phase == "step":
            mark = icon.get(d.get("kind"), "·")
            color = C["dim"] if d.get("kind") == "read" else C["text"]
            self.work_view.append(f"<span style='color:{C['faint']}'>{d['n']:>2}</span>&nbsp; "
                                  f"<span style='color:{color}'>{mark} {html.escape(d['text'])}</span>")
            self.work_chip.setText(dot_text(C["amber"], f"작업 중 · {d['n']}단계"))
            self.work_status.setText(f"{d['n']}단계 · {d['text'][:60]}")
        elif phase == "queued":
            self.work_view.append(f"<span style='color:{C['amber']}'>… 다음 작업 대기 ({d['waiting']})</span> "
                                  f"{html.escape(d['instruction'])}")
            self.entries.append({"role": "cmd", "text": d["instruction"][:80], "meta": "작업 대기"})
            self._render_chat()
        elif phase == "denied":
            self.work_view.append(f"<span style='color:{C['red']}'>✗ 허용 목록에 없어 실행 안 함: "
                                  f"{html.escape(d['text'])}</span>")
        elif phase == "done":
            color = C["mint"] if d["ok"] else (C["amber"] if d["stopped"] else C["red"])
            head = "멈춤" if d["stopped"] else ("끝" if d["ok"] else "실패")
            git = (f"커밋 {d['commit']}" + (" · GitHub에 올림" if d["pushed"] else "")) if d["commit"] else "바뀐 파일 없음"
            files = ", ".join(html.escape(f) for f in d["files"][:8])
            self.work_view.append(
                f"<p><span style='color:{color}'>■ {head}</span> <span style='color:{C['dim']}'>{d['seconds']}초 · "
                f"{git}{' · ' + files if files else ''}</span><br>{html.escape(d['summary'])}</p>")
            self.work_chip.setText(dot_text(color, f"작업 {head}"))
            self.work_status.setText(f"{head} · {git}")
            self.tabs.setTabText(1, "작업")
            self.entries.append({"role": "cmd", "text": git, "meta": f"작업 {head}"})
            self._render_chat()
        elif phase == "undone":
            self.work_view.append(f"<p><span style='color:{C['amber']}'>↶ 되돌림</span> 커밋 {d['commit']}"
                                  f"{' · GitHub에 올림' if d['pushed'] else ''}</p>")
            self.work_chip.setText(dot_text(C["amber"], "되돌림"))
            self.entries.append({"role": "cmd", "text": f"커밋 {d['commit']}", "meta": "작업 되돌림"})
            self._render_chat()

    def _set_sync_chip(self, text: str | None, color: str) -> None:
        if not text:
            self.sync_chip.hide()
            return
        self.sync_chip.setText(dot_text(color, text))
        self.sync_chip.show()

    def _render_chat(self) -> None:
        parts = []
        for e in self.entries:
            text = html.escape(e["text"]).replace("\n", "<br>")
            meta = html.escape(e.get("meta") or "")
            if e["role"] == "me":
                parts.append(
                    "<table width='100%' cellspacing='0' cellpadding='0'><tr><td width='22%'></td>"
                    "<td style='background:#2B1D14; padding:9px 12px;'>"
                    f"<span style='color:#FFB27D; font-size:8pt;'>나 · {meta}</span><br>{text}</td></tr></table>")
            elif e["role"] == "torti":
                parts.append(
                    "<table width='100%' cellspacing='0' cellpadding='0'><tr>"
                    f"<td style='background:{C['card']}; padding:9px 12px;'>"
                    f"<span style='color:{C['mint']}; font-size:8pt;'>토르티{' · ' + meta if meta else ''}</span><br>"
                    f"{text}</td><td width='22%'></td></tr></table>")
            else:
                parts.append(f"<p align='center' style='color:{C['dim']}; font-size:8pt;'>"
                             f"<span style='color:{C['amber']}'>{meta}</span> · {text}</p>")
        if not parts:
            parts.append(f"<p style='color:{C['faint']};'>아직 대화가 없어요.</p>")
        self.chat.setHtml("<div style='line-height:150%;'>" + "<br>".join(parts) + "</div>")
        self.chat.verticalScrollBar().setValue(self.chat.verticalScrollBar().maximum())

    def _render_brief(self, b: dict | None) -> None:
        if not b:
            self.domain_chip.hide()
            self.mood_chip.hide()
            self.now_text.setText("작업을 고르면 지금 할 일이 여기 떠요")
            self.now_text.setStyleSheet(f"color:{C['faint']};")
            self.step_count.setText("")
            self.next_tag.hide()
            self.next_text.setText("")
            self.caution_text.setText("")
            self.brief_view.setHtml(
                f"<h3>연결된 작업이 없어요</h3><p style='color:{C['dim']}'>위에서 작업을 고르거나, 새 작업을 만들거나, "
                "Claude Code로 쓰던 폴더를 열면 저장소를 분석해 분야, 진행 상황, 다음 단계, 말투를 정합니다.</p>")
            return
        self.domain_chip.setText(b.get("domain") or "분야 미정")
        self.domain_chip.show()
        mood = b.get("mood", "")
        self.mood_chip.setText(dot_text(MOOD_COLORS.get(mood, C["dim"]), f"{mood} · {b.get('speech_level', '')}"))
        self.mood_chip.show()
        steps = b.get("next_steps") or []
        self.now_text.setStyleSheet("")
        self.now_text.setText(steps[0] if steps else (b.get("status") or "다음 단계가 기록되지 않았어요"))
        self.step_count.setText(f"1 / {len(steps)}" if steps else "")
        self.next_tag.setVisible(len(steps) > 1)
        self.next_text.setText(steps[1] if len(steps) > 1 else "")
        cautions = b.get("cautions") or []
        self.caution_text.setText(f"주의  {cautions[0]}" if cautions else "")

        def items(xs: list[str], color: str = C["text"]) -> str:
            return "".join(f"<li style='color:{color}; margin:2px 0'>{html.escape(x)}</li>" for x in xs) or "<li>-</li>"

        subtitle = " · ".join(html.escape(x) for x in (b.get("domain"), b.get("assistant_role")) if x)
        self.brief_view.setHtml(
            f"<h2 style='margin:0'>{html.escape(b.get('title', ''))}</h2>"
            + (f"<p style='color:{C['dim']}'>{subtitle}</p>" if subtitle else "") +
            f"<p>{html.escape(b.get('summary', ''))}</p>"
            f"<h4>진행 상황</h4><p>{html.escape(b.get('status', ''))}</p>"
            f"<h4>다음 단계</h4><ol>{items(steps)}</ol>"
            f"<h4>핵심 사실</h4><ul>{items(b.get('key_facts') or [])}</ul>"
            f"<h4>주의</h4><ul>{items(b.get('cautions') or [], C['amber'])}</ul>"
            f"<h4>말투</h4><p>{html.escape(mood)}, {html.escape(b.get('speech_level', ''))}. "
            f"{html.escape(b.get('tone', ''))}</p>"
            f"<p style='color:{C['faint']}; font-size:8pt'>음성 인식 용어: "
            f"{html.escape(', '.join(b.get('vocabulary') or []))}</p>")


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in ((QPalette.Window, C["bg"]), (QPalette.Base, "#161616"), (QPalette.Text, C["text"]),
                        (QPalette.WindowText, C["text"]), (QPalette.Button, "#232323"),
                        (QPalette.ButtonText, C["text"]), (QPalette.Highlight, C["accent"]),
                        (QPalette.HighlightedText, "#161009"), (QPalette.ToolTipBase, C["card"]),
                        (QPalette.ToolTipText, C["text"]), (QPalette.PlaceholderText, C["faint"])):
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
