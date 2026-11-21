import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from torti.sessions import read_session, sessions_for, slug  # noqa: E402
from torti.visual import TagFilter, parse_marks, wants_pointing  # noqa: E402


def test_pixel_tags_become_fractions():
    marks = parse_marks('<표시 상자="640,180,704,252" 라벨="D3"/> <없음/>', size=(1280, 720))
    assert len(marks) == 1 and marks[0].label == "D3"
    assert marks[0].box == (500, 250, 550, 350)
    assert marks[0].pixels(1600, 900) == (800, 225, 880, 315)


def test_bad_tags_are_ignored():
    assert parse_marks('<표시 상자="10,10,5,5"/>', size=(100, 100)) == []  # inverted box
    assert parse_marks('<표시 상자="a,b,c,d"/>') == []
    assert parse_marks("<없음/>") == []


def test_tag_filter_keeps_tags_out_of_speech_while_streaming():
    f = TagFilter()
    out = "".join(f.feed(chunk) for chunk in ["D3는 위쪽 줄 세 번째예요. <표", '시 상자="500,250,550,', '350" 라벨="D3"/>'])
    out += f.flush()
    assert out.strip() == "D3는 위쪽 줄 세 번째예요."
    assert [m.label for m in f.marks] == ["D3"]


def test_where_questions_trigger_pointing():
    assert wants_pointing("D3 자리 어디야?")
    assert wants_pointing("이 칩 1번 핀 위치 짚어줘")
    assert not wants_pointing("인두 온도 몇 도야?")


def _write_session(path: Path, cwd: str, texts: list[str]) -> None:
    lines = [{"type": "session-owner", "sessionId": path.stem}]
    for t in texts:
        lines.append({"type": "user", "cwd": cwd, "message": {"role": "user", "content": t}})
    lines.append({"type": "user", "cwd": cwd, "message": {"role": "user",
                                                          "content": [{"type": "tool_result", "content": "x"}]}})
    path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")


def test_sessions_for_folder(tmp_path):
    work = tmp_path / "원목 스피커"
    other = tmp_path / "하트 LED00"  # different Korean name, same slug length
    work.mkdir()
    other.mkdir()
    projects = tmp_path / "claude-projects"
    folder = projects / slug(work)
    folder.mkdir(parents=True)
    _write_session(folder / "aaa.jsonl", str(work), ["앞판 구멍 지름 몇이었지?", "트리머 날은?"])
    _write_session(folder / "bbb.jsonl", str(other), ["다른 폴더 세션"])
    _write_session(folder / "ccc.jsonl", str(work), ["<command-name>/clear</command-name>"])
    found = sessions_for(work, projects)
    assert [s.id for s in found] == ["aaa"]
    assert found[0].title == "앞판 구멍 지름 몇이었지?" and found[0].user_turns == 2
    assert read_session(folder / "bbb.jsonl", work) is None
