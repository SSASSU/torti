"""Compare two demo projects with opposite moods: analysis -> briefing -> short project-grounded answers.

Runs in a throwaway TORTI_DATA. Speaks each project's greeting in its mood's voice.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["TORTI_DATA"] = tempfile.mkdtemp(prefix="torti_brief_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from torti.brief import analyze  # noqa: E402
from torti.claude_cli import ClaudeCli  # noqa: E402
from torti.project import Project  # noqa: E402
from torti.prompts import build_system_prompt  # noqa: E402
from torti.tts import SapiTts  # noqa: E402

DEMOS = {
    "하트 LED 생일선물": """# 하트 LED 생일선물 작업 메모

## 목표
조카(7살) 생일 선물. 하트 모양 기판에 LED 16개, 버튼 누르면 반짝이는 패턴이 바뀜.

## 부품 목록 (BOM)
- ATtiny85 (DIP-8), 8핀 소켓
- 빨간 LED 5mm 16개, 저항 220옴 16개
- 택트 스위치 1개, CR2032 홀더 1개, 슬라이드 스위치 1개

## 조립 순서
1. 8핀 소켓 (ATtiny85는 마지막에 꽂기)
2. 저항 220옴 16개
3. LED 16개 (긴 다리가 + 쪽, 기판의 동그란 패드)
4. 택트 스위치, 슬라이드 스위치
5. CR2032 홀더

## 말투

## 메모
""",
    "12V 납축전지 충전기": """# 12V 납축전지 충전기 작업 메모

## 목표
캠핑용 12V 7Ah 납축전지 충전기. 220V 변압기 + 브리지 정류 + LM317 정전압 13.8V.

## 부품 목록 (BOM)
- 변압기 220V -> 18V 2A, 퓨즈 홀더 + 1A 퓨즈
- 브리지 다이오드 KBP206, 전해 콘덴서 4700uF 35V
- LM317T + 방열판, 저항 240옴, 가변저항 5킬로옴
- 출력 다이오드 1N5408 (역류 방지)

## 조립 순서
1. 퓨즈 홀더와 변압기 1차측 배선 (전원 뽑고 작업)
2. 브리지 다이오드, 평활 콘덴서
3. LM317 방열판 장착
4. 전압 조정 저항, 가변저항으로 13.8V 맞추기
5. 출력 다이오드, 단자

## 말투

## 메모
""",
}
DEMOS["원목 스피커 박스"] = """# 원목 스피커 박스 작업 메모

## 목표
책상용 2웨이 패시브 스피커 한 쌍. 18mm 자작합판, 내부 용적 6리터, 베이스 리플렉스 포트.

## 재료 / 공구
- 18mm 자작합판 1장, 우드글루 (타이트본드 2), 도미노 5mm
- 트리머 + 원형 가이드 (우퍼 구멍 지름 128mm), 클램프 6개
- 마감: 오일 스테인 (Rubio Monocoat)

## 작업 순서
1. 재단 (앞판, 뒤판, 옆판 2, 위아래판)
2. 앞판 우퍼, 트위터 구멍 트리머 가공
3. 도미노 홈 가공 후 가조립
4. 접착, 클램핑 (24시간)
5. 샌딩 120, 180, 240방
6. 오일 마감

## 말투

## 메모
"""
LOGS = {
    "원목 스피커 박스": "# 2026-11-20 작업 기록\n\n## 15:40:00\n- 질문: 재단 끝났어. 앞판 구멍 지름 몇이었지?\n- 답변: 우퍼 128밀리.\n",
    "하트 LED 생일선물": "# 2026-11-20 작업 기록\n\n## 21:10:02\n- 질문: 소켓 방향 어디야?\n- 답변: 홈이 하트 위쪽.\n\n## 21:25:40\n- 질문: 저항 다 달았어\n- 답변: 좋아, 이제 LED.\n",
    "12V 납축전지 충전기": "# 2026-11-20 작업 기록\n\n## 20:02:11\n- 질문: 퓨즈 홀더 배선 끝났어\n- 답변: 전원 연결 전에 1차측 절연 확인하세요.\n",
}
UTTERANCES = ["가자!", "인두 온도 몇 도로 할까?", "다음 뭐 해?"]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    tts = SapiTts()
    only = sys.argv[1:]  # optional: names of demos to run
    for name, notes in DEMOS.items():
        if only and name not in only:
            continue
        proj, _ = Project.create(name)
        (proj.root / "NOTES.md").write_text(notes, encoding="utf-8")
        (proj.root / "log" / "2026-11-20.md").write_text(LOGS[name], encoding="utf-8")
        t = time.perf_counter()
        brief = analyze(proj.root)
        print(f"\n=== {name}  (분석 {time.perf_counter() - t:.0f}s)")
        print(f"분야: {brief.domain} | 역할: {brief.assistant_role}\nSTT 힌트: {brief.stt_prompt()}")
        print(f"분위기: {brief.mood}, {brief.speech_level} | {brief.tone} | voice(rate,pitch)={brief.voice()}")
        print(f"진행: {brief.status}\n다음: {brief.next_steps}\n주의: {brief.cautions}")
        print(f"첫마디: {brief.greeting}")
        rate, pitch = brief.voice()
        tts.set_style(rate, pitch)
        tts.say(brief.greeting)

        cli = ClaudeCli(build_system_prompt(brief), model="haiku", effort="low", cwd=proj.root)
        cli.start()
        for u in UTTERANCES:
            answer = next(v for k, v in cli.ask(u) if k == "result").text
            print(f"  Q {u}\n  A {answer}")
        cli.stop()
        tts.wait_done()
    tts.close()


if __name__ == "__main__":
    main()
