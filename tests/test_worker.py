import subprocess

from torti.intent import match_command
from torti.project import Project, load_state, save_state
from torti.sessions import recent_exchanges
from torti.visual import TagFilter
from torti.worker import Worker, describe


def test_work_order_tag_is_not_spoken():
    f = TagFilter()
    out = f.feed("작업자에게 맡길게요. <작업 지시=\"buttons.py에 C 버튼을 4번 핀으로") + f.feed(" 추가\"/>")
    assert out.strip() == "작업자에게 맡길게요." and f.work_order == "buttons.py에 C 버튼을 4번 핀으로 추가"


def test_worker_commands_win_over_stop_and_cancel():
    assert match_command("작업 멈춰") == "work_stop"
    assert match_command("작업 취소") == "work_stop"
    assert match_command("되돌려줘") == "work_undo"
    assert match_command("멈춰") == "stop"


def test_describe_steps():
    assert describe({"name": "Edit", "input": {"file_path": "C:/p/src/main.cpp"}}) == ("edit", "수정 main.cpp")
    assert describe({"name": "Bash", "input": {"command": "pio run"}}) == ("run", "$ pio run")


def test_queue_while_busy(tmp_path):
    events = []
    w = Worker(Project(tmp_path), lambda k, d: events.append(d))
    from torti.worker import Task

    w.task = Task("첫 작업")  # running
    assert w.start("빌드해") == "queued" and w.queue == ["빌드해"]
    assert "대기 1건" in w.status_note()
    assert w.stop() and w.queue == []


def test_project_state_roundtrip(tmp_path):
    save_state(tmp_path, voice_session="abc")
    save_state(tmp_path, worker_session="def")
    s = load_state(tmp_path)
    assert s["voice_session"] == "abc" and s["worker_session"] == "def" and s["updated"] > 0


def test_recent_exchanges(tmp_path):
    import json

    p = tmp_path / "s.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "[사진 두 장: 어쩌고]\n보드 뭐야?"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "찾아볼게요."}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "..."}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Brook 보드예요. <표시 상자=\"1,2,3,4\"/>"}]}},
    ]
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines), encoding="utf-8")
    assert recent_exchanges(p) == [("me", "보드 뭐야?"), ("torti", "찾아볼게요. Brook 보드예요.")]
