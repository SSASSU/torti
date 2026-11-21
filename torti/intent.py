"""Local handling of control utterances (VC-01..VC-04) and the photo-or-not decision (FR-16)."""

from __future__ import annotations

import re

# command -> keywords (spaces removed). Matched only for short utterances so that
# questions that merely contain a keyword ("그만큼 넣어야 돼?") still go to the AI.
_COMMANDS = {
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
    r"(^|\s)(이|저|그)\s|이거|이게|이건|이것|요거|저거|그거|여기|거기|방금|지금|보여|봐줘|봐 |보이|어때|괜찮|"
    r"맞아|맞나|맞지|상태|색띠|각인|몇 ?옴|납땜한|붙인|꽂은|위치|어디|자리|짚어|표시|무슨 부품|뭐야"
)


def needs_image(text: str, mode: str = "auto") -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return bool(_DEICTIC.search(text))
