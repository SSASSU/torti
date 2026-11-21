"""Project <-> git flow against a local bare repo standing in for GitHub (no network)."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from torti.project import Project, list_projects  # noqa: E402


def git(*args, cwd=None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def test_new_work_pushes_and_continue_elsewhere(tmp_path):
    remote = tmp_path / "remote.git"
    git("init", "--bare", "-b", "main", str(remote))

    proj, res = Project.create("LED 큐브 만들기", remote_url=str(remote), base=tmp_path / "pc1")
    assert res.ok, res.message
    assert (proj.root / "CLAUDE.md").read_text(encoding="utf-8").rstrip().endswith("@NOTES.md")
    assert list_projects(tmp_path / "pc1") == [proj.name]

    jpg = proj.save_capture(b"\xff\xd8fake")
    proj.append_log("이 저항 몇 옴이야?", "4.7 킬로옴으로 보여요.", jpg)
    proj.add_note("R3는 4.7킬로옴으로 바꿈")
    res = proj.sync("테스트 기록")
    assert res.ok and res.message == "올렸습니다", res.message
    assert "테스트 기록" in git("log", "--oneline", cwd=remote)

    # Continue on another machine: clone gets notes and log, but not photos.
    other, res = Project.clone(str(remote), base=tmp_path / "pc2")
    assert res.ok, res.message
    assert "R3는 4.7킬로옴" in (other.root / "NOTES.md").read_text(encoding="utf-8")
    logs = list((other.root / "log").glob("*.md"))
    assert logs and "4.7 킬로옴" in logs[0].read_text(encoding="utf-8")
    assert not (other.root / jpg).exists()

    # Back on the first machine, open() pulls the other side's changes.
    other.add_note("다른 PC에서 추가")
    assert other.sync().ok
    again, res = Project.open(proj.name, base=tmp_path / "pc1")
    assert res.ok, res.message
    assert "다른 PC에서 추가" in (again.root / "NOTES.md").read_text(encoding="utf-8")
    assert again.sync().message == "이미 최신입니다"


def test_clone_existing_claude_repo_keeps_its_files(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    git("init", "-b", "main", cwd=src)
    (src / "CLAUDE.md").write_text("# 기존 프로젝트 지침\n", encoding="utf-8")
    (src / ".gitignore").write_text("*.log", encoding="utf-8")
    git("add", "-A", cwd=src)
    git("commit", "-m", "init", cwd=src)

    proj, res = Project.clone(str(src), base=tmp_path / "pc")
    assert res.ok, res.message
    assert (proj.root / "CLAUDE.md").read_text(encoding="utf-8") == "# 기존 프로젝트 지침\n"
    assert (proj.root / ".gitignore").read_text(encoding="utf-8") == "*.log\ncaptures/\n.torti/\n"
    assert (proj.root / "log").is_dir()


def test_local_only_project(tmp_path):
    proj, res = Project.create("임시 작업", base=tmp_path)
    assert res.ok
    proj.add_note("메모")
    res = proj.sync()
    assert res.ok and "원격 저장소 없음" in res.message
