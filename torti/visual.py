"""Visual pointing (FR-80..): mark where to work on a photo or reference image.

The fast voice model answers in speech; a separate, more precise model (``Pointer``) looks at the
same image in parallel and returns tags such as::

    <표시 상자="412,300,468,352" 라벨="D3"/>

in pixel coordinates of the image it was sent. They are converted to 0..1000 fractions (``Mark``)
and drawn on screen, never spoken. ``TagFilter`` strips any tag a model writes into speech.
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .claude_cli import ClaudeCli

POINTER_SYSTEM = """\
너는 작업 사진에서 위치를 짚어 주는 도우미다. 사진과 질문을 받으면 질문이 가리키는 대상을 사진에서 찾는다.
답은 표시 태그만 쓴다. 다른 말은 쓰지 않는다.
형식: <표시 상자="x1,y1,x2,y2" 라벨="짧은 이름"/>
- 좌표는 함께 알려 준 사진 크기 기준 픽셀 좌표다. 왼쪽 위가 0,0이다.
- 상자는 대상을 빠듯하게 감싼다. 글자 라벨이 아니라 부품이나 자리 자체를 감싼다.
- 대상이 여러 개면 태그를 세 개까지 쓴다.
- 사진에서 대상을 확실히 찾을 수 없으면 <없음/>만 쓴다."""

# Questions that ask where something is (Korean); photos are only pointed at for these.
_WHERE = re.compile(r"어디|어느 ?쪽|어느 ?자리|자리|위치|짚어|표시|가리켜|찾아|몇 번 핀|핀 위치")


def wants_pointing(text: str) -> bool:
    return bool(_WHERE.search(text))

POINTING_RULES = """\
- 사진이나 작업 자료 이미지 속 위치를 짚어야 하면 답 끝에 표시 태그를 붙인다. 화면에 그려지고 소리로는 읽히지 않는다.
  형식: <표시 대상="사진" 상자="x1,y1,x2,y2" 라벨="짧은 이름"/>
  좌표는 이미지 왼쪽 위가 0,0, 오른쪽 아래가 1000,1000인 비율 좌표로, 대상을 빠듯하게 감싼다. 태그는 세 개까지.
  대상은 함께 온 사진이면 "사진", 작업 폴더의 이미지 파일이면 그 상대 경로를 쓴다.
  말로는 "화면에 표시한 곳"처럼 짧게만 언급하고 좌표는 말하지 않는다. 위치를 확신할 수 없으면 태그를 붙이지 않는다."""

_TAG = re.compile(r"<표시\b([^>]*)/?>")
_ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


@dataclass
class Mark:
    target: str  # "사진" or a project-relative image path
    box: tuple[int, int, int, int]  # x1, y1, x2, y2 in 0..1000
    label: str = ""

    def pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = self.box
        return (round(x1 / 1000 * width), round(y1 / 1000 * height),
                round(x2 / 1000 * width), round(y2 / 1000 * height))


def parse_tag(attrs: str, size: tuple[int, int] | None = None) -> Mark | None:
    """``size`` (width, height): coordinates are pixels of that image; None: already 0..1000."""
    a = dict(_ATTR.findall(attrs))
    try:
        nums = [float(v) for v in a.get("상자", "").split(",")]
    except ValueError:
        return None
    if len(nums) != 4:
        return None
    if size:
        w, h = size
        nums = [nums[0] / w * 1000, nums[1] / h * 1000, nums[2] / w * 1000, nums[3] / h * 1000]
    x1, y1, x2, y2 = (max(0, min(1000, round(v))) for v in nums)
    if x2 <= x1 or y2 <= y1:
        return None
    return Mark(a.get("대상", "사진") or "사진", (x1, y1, x2, y2), a.get("라벨", ""))


def parse_marks(text: str, size: tuple[int, int] | None = None) -> list[Mark]:
    return [m for m in (parse_tag(g, size) for g in _TAG.findall(text)) if m][:3]


class Pointer:
    """Resident precise-model CLI that only returns location tags for one image + question.

    Every call starts from an empty conversation (old photos would pile up in its context): after
    answering, the process is recycled in the background so the next call finds a warm one.
    """

    def __init__(self, model: str = "sonnet", cwd: str | Path | None = None) -> None:
        self.model = model
        self.cwd = cwd
        self._cli: ClaudeCli | None = None
        self._lock = threading.Lock()
        self._recycle()

    def _recycle(self) -> None:
        old = self._cli
        self._cli = ClaudeCli(POINTER_SYSTEM, model=self.model, effort="low", cwd=self.cwd)
        self._cli.start()
        if old:
            threading.Thread(target=old.stop, daemon=True).start()

    def locate(self, jpeg: bytes, size: tuple[int, int], question: str, timeout: float = 30) -> tuple[list[Mark], float]:
        """Marks (0..1000 fractions) for what ``question`` points at, and seconds taken."""
        with self._lock:
            t = time.perf_counter()
            text = f"사진 크기: {size[0]}x{size[1]} 픽셀\n질문: {question}"
            result = None
            for kind, val in self._cli.ask(text, jpeg, timeout=timeout):
                if kind == "result":
                    result = val
            self._recycle()
            marks = parse_marks(result.text, size) if result and result.ok else []
            return marks, time.perf_counter() - t

    def stop(self) -> None:
        if self._cli:
            self._cli.stop()


class TagFilter:
    """Streaming filter: passes speakable text through, holds back anything that may be a tag."""

    def __init__(self, max_hold: int = 400) -> None:
        self._buf = ""
        self.marks: list[Mark] = []
        self.max_hold = max_hold

    def feed(self, text: str) -> str:
        self._buf += text
        out = []
        while self._buf:
            lt = self._buf.find("<")
            if lt < 0:
                out.append(self._buf)
                self._buf = ""
                break
            out.append(self._buf[:lt])
            self._buf = self._buf[lt:]
            gt = self._buf.find(">")
            if gt < 0:
                if len(self._buf) > self.max_hold:  # not a tag after all
                    out.append(self._buf)
                    self._buf = ""
                break
            chunk, self._buf = self._buf[:gt + 1], self._buf[gt + 1:]
            m = _TAG.fullmatch(chunk.strip())
            if m:
                mark = parse_tag(m.group(1))
                if mark:
                    self.marks.append(mark)
            else:
                out.append(chunk)
        return "".join(out)

    def flush(self) -> str:
        rest, self._buf = self._buf, ""
        m = _TAG.search(rest)
        if m:
            mark = parse_tag(m.group(1))
            if mark:
                self.marks.append(mark)
            rest = _TAG.sub("", rest)
        return rest
