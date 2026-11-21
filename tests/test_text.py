import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from torti.intent import match_command, match_note, needs_image  # noqa: E402
from torti.speech_text import SentenceSplitter, first_chunk, sino, speakable, spell_numbers  # noqa: E402


def test_korean_number_reading():
    assert sino(128) == "백이십팔" and sino(350) == "삼백오십" and sino(10000) == "만" and sino(1100) == "천백"
    assert spell_numbers("LED 16개, 3번 핀") == "LED 열여섯 개, 삼번 핀"
    assert spell_numbers("4.7 킬로옴, 350도") == "사 점 칠 킬로옴, 삼백오십도"
    assert spell_numbers("LM317과 1N5408") == "LM삼일칠과 일N오사공팔"
    assert spell_numbers("세 번째 말고 2번째, 20개") == "세 번째 말고 두 번째, 스무 개"
    assert spell_numbers("1,000 옴") == "천 옴"


def test_first_chunk_splits_long_opening_at_comma():
    assert first_chunk("좋아요! 이제 LED 열여섯 개를 달 차례예요.") == ("좋아요!", "이제 LED 열여섯 개를 달 차례예요.")
    assert first_chunk("네, 우퍼 구멍부터 뚫어요.") == ("네, 우퍼 구멍부터 뚫어요.", "")  # comma within 3 chars: keep
    head, rest = first_chunk("우퍼 구멍 지름은 백이십팔 밀리미터이고, 트위터 쪽은 기록이 없어요.")
    assert head == "우퍼 구멍 지름은 백이십팔 밀리미터이고," and rest == "트위터 쪽은 기록이 없어요."
    assert first_chunk("짧은 문장.") == ("짧은 문장.", "")


def test_splitter_streams_sentences_and_keeps_decimals():
    s = SentenceSplitter()
    out = []
    for chunk in ["4.", "7킬로옴으로 보여요", ". 멀티미터로", " 확인하세요.", " 끝"]:
        out += s.feed(chunk)
    assert out == ["4.7킬로옴으로 보여요.", "멀티미터로 확인하세요."]
    assert s.flush() == ["끝"]


def test_splitter_joins_tiny_fragments():
    s = SentenceSplitter(min_chars=6)
    assert s.feed("네. 괜찮아 보여요. ") == ["네. 괜찮아 보여요."]


def test_speakable_units_and_markdown():
    assert speakable("**4.7kΩ** 저항") == "4.7 킬로옴 저항"
    assert speakable("10µF, 350°C, 5V, 20mA") == "10 마이크로패럿, 350 도, 5 볼트, 20 밀리암페어"
    assert speakable("- VCC는 8번 핀") == "VCC는 8번 핀"
    assert speakable("1kΩ×100") == "1 킬로옴 곱하기 100"


def test_commands():
    assert match_command("멈춰") == "stop"
    assert match_command("그만해.") == "stop"
    assert match_command("다시 말해줘") == "repeat"
    assert match_command("새 대화") == "new"
    assert match_command("취소") == "cancel"
    assert match_command("천천히 말해줘") == "slower"


def test_questions_are_not_commands():
    assert match_command("그만큼 넣어야 돼?") is None
    assert match_command("이거 잘 됐어?") is None
    assert match_command("인두 온도 몇 도로 해야 돼") is None


def test_sync_and_note():
    assert match_command("깃허브에 올려줘") == "sync"
    assert match_command("저장해") == "sync"
    assert match_note("기록해 둬, R3는 4.7킬로옴으로 바꿨어.") == "R3는 4.7킬로옴으로 바꿨어."
    assert match_note("메모: 플럭스 다 씀") == "플럭스 다 씀"
    assert match_note("이 저항 기록해 둬도 돼?") is None


def test_needs_image():
    assert needs_image("이 저항 몇 옴이야?")
    assert needs_image("방금 납땜한 거 괜찮아?")
    assert not needs_image("인두 온도 몇 도로 해야 돼?")
    assert not needs_image("플럭스는 왜 써?")
    assert needs_image("플럭스는 왜 써?", "always")
