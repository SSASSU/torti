"""Turn streamed answer text into speakable sentences (FR-31a, FR-33)."""

from __future__ import annotations

import re

_SPLIT = re.compile(r"(?<=[.!?…。？！])\s+|\n+")


class SentenceSplitter:
    """Feed streaming deltas, get whole sentences as soon as they end.

    A period followed by a digit ("4.7") is not a boundary, because a boundary needs whitespace.
    Very short fragments are held and joined to the next sentence.
    """

    def __init__(self, min_chars: int = 6) -> None:
        self.min_chars = min_chars
        self._buf = ""

    def feed(self, text: str) -> list[str]:
        self._buf += text
        out: list[str] = []
        while True:
            cut = None
            for m in _SPLIT.finditer(self._buf):
                if len(self._buf[:m.start()].strip()) >= self.min_chars:
                    cut = m
                    break
            if cut is None:
                return out
            sentence = self._buf[:cut.start()].strip()
            self._buf = self._buf[cut.end():]
            if sentence:
                out.append(sentence)

    def flush(self) -> list[str]:
        rest, self._buf = self._buf.strip(), ""
        return [rest] if rest else []


_NUM = r"(\d(?:[\d,.]*\d)?)\s*"
_UNITS = [  # order matters: prefixed units before bare ones
    (r"[kK]Ω|kohm", "킬로옴"), (r"MΩ|Mohm", "메가옴"), (r"Ω|ohm", "옴"),
    (r"[µμu]F", "마이크로패럿"), (r"nF", "나노패럿"), (r"pF", "피코패럿"),
    (r"[µμu]H", "마이크로헨리"), (r"mH", "밀리헨리"),
    (r"mA", "밀리암페어"), (r"[µμu]A", "마이크로암페어"), (r"A", "암페어"),
    (r"mV", "밀리볼트"), (r"kV", "킬로볼트"), (r"V", "볼트"),
    (r"mW", "밀리와트"), (r"W", "와트"),
    (r"MHz", "메가헤르츠"), (r"kHz", "킬로헤르츠"), (r"Hz", "헤르츠"),
    (r"°C|℃|도C", "도"), (r"mm", "밀리미터"), (r"%", "퍼센트"),
]
_UNIT_RES = [(re.compile(_NUM + u + r"(?![A-Za-z])"), word) for u, word in _UNITS]
_MARKDOWN = [
    (re.compile(r"`+"), ""), (re.compile(r"\*\*|__"), ""), (re.compile(r"(?m)^\s*#+\s*"), ""),
    (re.compile(r"(?m)^\s*[-*•]\s+"), ""), (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),
    (re.compile(r"(출처|참고|Sources?)\s*:.*$", re.I), ""), (re.compile(r"https?://\S+|www\.\S+"), ""),
    (re.compile(r"[|*_~>]"), " "),
]
_SYMBOLS = [("×", " 곱하기 "), ("±", " 플러스마이너스 "), ("→", ", "), ("≈", " 약 "), ("~", "에서 ")]


_DIGITS = "영일이삼사오육칠팔구"
_SERIAL_DIGITS = "공일이삼사오육칠팔구"  # part numbers read digit by digit: LM317 -> 엘엠 삼일칠
_NATIVE_ONES = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
_NATIVE_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
# Counters read with native Korean numbers (열여섯 개, 세 번째, 두 시간). 번 alone stays Sino (3번 핀 = 삼 번).
_NATIVE_COUNTERS = "개|명|번째|시간|살|마리|가지|군데|줄|장|바퀴|방울"


def sino(n: int) -> str:
    """Sino-Korean reading: 128 -> 백이십팔, 10000 -> 만."""
    if n == 0:
        return "영"
    out, group = [], 0
    while n:
        chunk, n = n % 10000, n // 10000
        if chunk:
            s = ""
            for pos, unit in ((3, "천"), (2, "백"), (1, "십"), (0, "")):
                d = chunk // 10 ** pos % 10
                if d:
                    s += ("" if d == 1 and pos else _DIGITS[d]) + unit
            if group == 1 and s == "일":
                s = ""
            out.append(s + ("", "만", "억", "조")[group])
        group += 1
    return "".join(reversed(out))


def native(n: int) -> str | None:
    """Native Korean counting form for 1..99 (16 -> 열여섯, 20 -> 스무); None outside that range."""
    if not 1 <= n <= 99:
        return None
    if n == 20:
        return "스무"
    return _NATIVE_TENS[n // 10] + _NATIVE_ONES[n % 10]


def spell_numbers(text: str) -> str:
    """Digits -> Korean words, for neural TTS that would otherwise read them unreliably."""
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)  # 1,000 -> 1000
    text = re.sub(r"[A-Za-z]+\d[A-Za-z0-9]*|\d+[A-Za-z][A-Za-z0-9]*",
                  lambda m: re.sub(r"\d", lambda d: _SERIAL_DIGITS[int(d.group())], m.group()), text)
    text = re.sub(r"(\d+)\.(\d+)", lambda m: f"{sino(int(m.group(1)))} 점 "
                  + "".join(_DIGITS[int(c)] for c in m.group(2)), text)
    text = re.sub(rf"(\d+)\s*({_NATIVE_COUNTERS})",
                  lambda m: f"{native(int(m.group(1))) or sino(int(m.group(1)))} {m.group(2)}", text)
    return re.sub(r"\d+", lambda m: sino(int(m.group())), text)


def first_chunk(text: str, max_chars: int = 16) -> tuple[str, str]:
    """Split a long opening at the first comma or !/? so the first audio starts sooner.

    Slow neural voices take about as long to make audio as to play it, so "좋아요!" alone is
    heard ~1 s earlier than the whole sentence.
    """
    if len(text) <= max_chars:
        return text, ""
    m = re.search(r"[,，!?！？]\s+", text[3:34])
    if not m:
        return text, ""
    cut = 3 + m.end()
    return text[:cut].strip(), text[cut:].strip()


def speakable(text: str) -> str:
    """Strip markup and spell out units so TTS reads them naturally (safety net for FR-31a)."""
    for rx, rep in _MARKDOWN:
        text = rx.sub(rep, text)
    for rx, word in _UNIT_RES:
        text = rx.sub(lambda m, w=word: f"{m.group(1)} {w}", text)
    for sym, word in _SYMBOLS:
        text = text.replace(sym, word)
    return re.sub(r"\s{2,}", " ", text).strip()


def times_ko(factor: float) -> str:
    """Zoom factor as spoken Korean: 2.0 -> "두 배", 2.5 -> "두 배 반"."""
    half = round(factor * 2) / 2
    whole = int(half)
    s = f"{_NATIVE_TIMES.get(whole, str(whole))} 배"
    return s + " 반" if half > whole else s


_NATIVE_TIMES = {1: "한", 2: "두", 3: "세", 4: "네"}
