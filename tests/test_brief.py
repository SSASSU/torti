import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from torti.brief import BRIEF_VERSION, CACHE, MOOD_VOICE, Brief, fingerprint, load_cached  # noqa: E402
from torti.prompts import build_system_prompt  # noqa: E402


def make_project(root: Path) -> Path:
    (root / "log").mkdir(parents=True)
    (root / "captures").mkdir()
    (root / "NOTES.md").write_text("# 하트 LED\n## 조립 순서\n1. LED\n2. 저항\n", encoding="utf-8")
    (root / "log" / "2026-11-20.md").write_text("- 질문: LED 방향?\n", encoding="utf-8")
    return root


def test_fingerprint_tracks_project_files_not_photos_or_cache(tmp_path):
    root = make_project(tmp_path / "p")
    fp = fingerprint(root)
    (root / "captures" / "a.jpg").write_bytes(b"x" * 100)
    (root / ".torti").mkdir()
    (root / ".torti" / "brief.json").write_text("{}", encoding="utf-8")
    assert fingerprint(root) == fp
    (root / "NOTES.md").write_text("# 하트 LED\n## 조립 순서\n1. LED\n2. 저항\n", encoding="utf-8")
    assert fingerprint(root) == fp
    (root / "NOTES.md").write_text("# 하트 LED\n## 조립 순서\n1. LED\n2. 콘덴\n", encoding="utf-8")  # same size
    assert fingerprint(root) != fp


def test_cache_is_used_only_while_fresh(tmp_path):
    root = make_project(tmp_path / "p")
    brief = Brief(title="하트 LED", mood="장난스러움", speech_level="반말", greeting="가자, 저항 달 차례야.")
    (root / CACHE.parent).mkdir()
    cache = {"version": BRIEF_VERSION, "fingerprint": fingerprint(root), "brief": brief.__dict__}
    (root / CACHE).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    assert load_cached(root) == brief
    (root / CACHE).write_text(json.dumps({**cache, "version": BRIEF_VERSION - 1}, ensure_ascii=False),
                              encoding="utf-8")
    assert load_cached(root) is None  # older briefing format: analyze again
    (root / CACHE).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    with (root / "log" / "2026-11-20.md").open("a", encoding="utf-8") as f:
        f.write("- 질문: 저항 몇 옴?\n")
    assert load_cached(root) is None


def test_prompt_and_voice_follow_brief():
    brief = Brief(title="12V 충전기", summary="납축전지 충전기", status="변압기 배선 끝",
                  next_steps=["LM317 방열판 달기"], key_facts=["출력 13.8 볼트"], cautions=["AC 220볼트 노출"],
                  mood="진지", speech_level="존댓말", tone="짧고 단호하게")
    prompt = build_system_prompt(brief)
    assert "[현재 작업]" in prompt and "LM317 방열판 달기" in prompt and "AC 220볼트 노출" in prompt
    assert "분위기: 진지, 존댓말. 짧고 단호하게" in prompt
    assert brief.voice() == MOOD_VOICE["진지"]
    assert "연결된 작업이 없다" in build_system_prompt(None)


def test_domain_drives_role_and_stt_vocabulary():
    brief = Brief(title="원목 스피커 박스", domain="목공", assistant_role="재단과 접합 순서를 챙기는 조수",
                  vocabulary=["자작합판", "도미노", "트리머"])
    prompt = build_system_prompt(brief)
    assert "분야: 목공" in prompt and "네 역할: 재단과 접합 순서를 챙기는 조수" in prompt
    assert "납땜" not in prompt
    assert brief.stt_prompt() == "목공 작업 중 질문. 토르티, 자작합판, 도미노, 트리머."
