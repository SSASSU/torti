"""Local handling of control utterances (VC-01..VC-04) and the photo-or-not decision (FR-16)."""

from __future__ import annotations

import re

# command -> keywords (spaces removed). Matched only for short utterances so that
# questions that merely contain a keyword ("그만큼 넣어야 돼?") still go to the AI.
_COMMANDS = {  # checked in order: the worker commands come before "stop"/"cancel" they contain
    "work_stop": ("작업멈춰", "작업그만", "작업중단", "작업취소", "작업스톱"),
    "work_undo": ("되돌려", "작업되돌", "원상복구", "방금거취소"),
    "stop": ("멈춰", "그만", "스톱", "정지", "조용"),
    "repeat": ("다시말해", "다시한번", "뭐라고", "다시얘기", "한번더"),
    "new": ("새대화", "처음부터", "리셋", "새로시작"),
    "cancel": ("취소", "됐어"),
    "slower": ("천천히",),
    "faster": ("빠르게", "빨리말해"),
    "sync": ("저장해", "올려줘", "푸시해", "깃허브에올려", "동기화"),
    "reanalyze": ("다시분석", "새로분석", "작업다시봐", "프로젝트다시봐", "다시살펴"),
}

# VC-07: "기록해 둬, R3는 4.7킬로로 바꿨어" -> note text
_NOTE = re.compile(r"^\s*(기록해\s*[둬줘놔]|메모해\s*[둬줘놔]|적어\s*[둬줘놔]|메모)\s*[:,.]?\s*(?P<body>\S.*)$")


def match_note(text: str) -> str | None:
    m = _NOTE.match(text)
    return m.group("body").strip() if m else None
_MAX_EXTRA = 5  # characters allowed around the keyword ("다시 말해줘", "그만해")


def _compact(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text)


def match_command(text: str) -> str | None:
    if "?" in text:  # Whisper marks questions; "이거 잘 됐어?" is a question, not "cancel"
        return None
    t = _compact(text)
    for cmd, words in _COMMANDS.items():
        for w in words:
            if w in t and len(t) <= len(w) + _MAX_EXTRA:
                return cmd
    return None


# Words that point at the work in front of the camera.
_DEICTIC = re.compile(
    r"(^|\s)(이|저|그)\s|이거|이게|이건|이것|요거|저거|그거|여기|거기|방금|지금|보여|봐|보이|어때|어떠|어떻|괜찮|"
    r"맞아|맞나|맞지|상태|색띠|각인|몇 ?옴|납땜한|붙인|꽂은|위치|어디|자리|짚어|표시|무슨 부품|뭐야|"
    r"읽어|읽혀|읽을|글씨|글자|적혀|써 ?있|모델명|품번|보드|기판|칩|핀"  # reading print on parts needs the photo
)


def needs_image(text: str, mode: str = "auto") -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return bool(_DEICTIC.search(text))


# Zoom (precision work): "확대해", "더 확대", "세 배 확대", "아두이노 핀 확대해 줘", "축소", "원래대로".
_ZOOM_RESET = re.compile(r"원래\s*대로|원래\s*화면|전체\s*(화면|보기|보여)|확대\s*(풀어|해제|그만|취소)|줌\s*아웃")
_ZOOM_OUT = re.compile(r"축소|작게\s*(보여|봐)")
_ZOOM_IN = re.compile(r"확대(?!경)|크게\s*(보여|봐)|가까이\s*(보여|봐)|줌\s*인")
_ZOOM_TIMES = re.compile(r"(\d(?:\.\d)?|한|두|세|네)\s*배\s*(로)?")
_ZOOM_FILLER = re.compile(r"(좀|더|조금|살짝|한번|여기|거기|저기|이거|그거|저거|화면|카메라|이|그|저)(를|을|좀)?")
_JOSA_END = re.compile(r"(\s*(쪽|부분|근처|주변|위치|자리))?\s*(을|를|이|가|은|는|만|도)?\s*$")
_KOREAN_TIMES = {"한": 1, "두": 2, "세": 3, "네": 4}


def match_zoom(text: str) -> tuple[str, str | None, float | None] | None:
    """("in" | "out" | "reset", target to find or None, absolute factor or None), or None if not a zoom request."""
    t = text.strip().rstrip(".!")
    if len(t) > 30:
        return None
    if "?" in t and not re.search(r"(줄래|줘|래요|봐)\s*\?$", t):  # "확대하면 보여?" is a question
        return None
    t = t.rstrip("?")
    if _ZOOM_RESET.search(t):
        return ("reset", None, None)
    m = _ZOOM_IN.search(t)
    if m:
        before = t[:m.start()]
        times = None
        tm = _ZOOM_TIMES.search(before)
        if tm:
            times = float(_KOREAN_TIMES.get(tm.group(1), tm.group(1)))
            before = before[:tm.start()] + before[tm.end():]
        words = [w for w in re.sub(r"한\s+번", "한번", before).split() if not _ZOOM_FILLER.fullmatch(w)]
        target = _JOSA_END.sub("", " ".join(words)).strip(" ,")
        return ("in", target or None, times)
    if _ZOOM_OUT.search(t):
        return ("out", None, None)
    return None
