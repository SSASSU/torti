# Torti

납땜·전자 조립 작업용 **음성 + 비전 AI 도우미** (Windows GUI).

페달을 밟고 질문 → 책상 위 캠(Elgato 등)으로 작업물 캡처 → AI가 보고 음성으로 답변.

- 요구사항: [docs/REQUIREMENTS.md](docs/REQUIREMENTS.md)
- 메인 플로우: **음성 입력 → AI 보조 → 음성 출력** (GUI는 보조)
- 구성: **Windows 네이티브** (음성·STT·TTS 로컬) + **Claude CLI** 연동
- 작업 관리: 작업 1개 = GitHub 저장소 1개. 기록·메모를 저장소에 올려 이어서 작업
- 상태: **M0 스파이크** (콘솔 음성 루프 동작, GUI 전)

## 설치

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt

# 자연스러운 남성 목소리 (Chatterbox, GPU). 없으면 Windows 기본 음성으로 동작
py -3.12 -m venv .venv-tts
.venv-tts\Scripts\python -m pip install --no-deps -r requirements-tts.txt
```

라이브러리, 모델, 다운로드 캐시는 모두 프로젝트 폴더 안(`.venv*/`, `.cache/`)에 둡니다.
각 venv에 `pip.ini`(`cache-dir = <repo>\.cache\pip`)를 두면 pip 캐시도 프로젝트 안에 쌓입니다.

## GUI 실행

```powershell
.venv\Scripts\python -m torti --mic "Wave:3"          # 옵션은 %LOCALAPPDATA%\Torti\settings.json에 저장됨
```

- 말하기: F1(왼손)·페달·화면 버튼 (탭하면 자동 종료, 누른 채 말하면 뗄 때 종료). 말하기 어려우면 입력창에 입력
- 작업: 새 작업 / GitHub에서 이어서 / 기존 폴더 열기. 열면 저장소를 분석해 분야·진행 상황·말투를 맞춤
- 자료 띄우기: 회로도·도면 이미지를 띄우면 질문과 위치 표시가 그 자료 기준
- 위치 질문("D3 자리 어디야?")은 화면에 강조 표시
- 세션…: 작업 폴더에서 쓰던 Claude Code 세션을 불러와 이어서 대화

라이브러리와 모델은 모두 프로젝트 폴더 안(`.venv*/`, `.cache/`)에 둡니다.

## M0 콘솔 실행

준비물: Python 3.12, NVIDIA GPU(선택), [Claude CLI](https://code.claude.com) 구독 로그인.

```powershell
# 음성 루프: F1(또는 F1로 매핑한 페달)을 누르고 말하기
.venv\Scripts\python spike\m0_console.py --mic "Wave:3"

# 새 작업 시작 (미리 만든 빈 GitHub 저장소에 연결)
.venv\Scripts\python spike\m0_console.py --mic "Wave:3" --new "LED 큐브" --remote https://github.com/<user>/<repo>.git

# GitHub 저장소에서 이어서 하기 / 로컬 작업 이어서 하기
.venv\Scripts\python spike\m0_console.py --clone https://github.com/<user>/<repo>.git
.venv\Scripts\python spike\m0_console.py --project "LED-큐브"
```

음성 명령: "멈춰", "다시 말해줘", "새 대화", "취소", "천천히/빠르게", "기록해 둬, …", "깃허브에 올려줘".
작업 데이터와 기록은 `%LOCALAPPDATA%\Torti`에 저장됩니다.

점검용 스크립트: `spike/devices_check.py`(장치), `spike/bench_cli.py`(CLI 지연), `spike/e2e_selftest.py`(마이크 없이 전체 1회), `pytest tests`.
