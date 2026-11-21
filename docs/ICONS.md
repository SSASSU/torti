# Torti 아이콘 세트 요구사항 (v1)

> Torti GUI(PySide6), 시스템 트레이, 알림, 설치 파일, 작업 카드, 외부 기기(Stream Deck 등)에 들어가는 아이콘 전체 명세.
> 원칙: **"혹시 몰라서 이런 것까지 만들었다"** — 지금 요구사항에 쓰는 것(100%)에, 다음 확장에서 쓸 법한 것(+100%)까지 만든다.

---

## 0. 등급

| 등급 | 뜻 | 언제 필요 |
|---|---|---|
| **A** | 필수 | M1 MVP 화면·트레이에 바로 쓰임 |
| **B** | 권장 | M2(v1) 기능, 설정·기록 화면 |
| **C** | 혹시 몰라서 | 아직 계획에 없지만 나올 법한 기능, 외부 기기, 마케팅 |

---

## 1. 스타일 가이드

### 1.1 그리드와 선
| 항목 | 값 |
|---|---|
| 기준 캔버스 | **24×24**, `viewBox="0 0 24 24"` |
| 안전 여백 | 사방 2px (실제 그림 영역 20×20) |
| 키라인 | 원 지름 20 / 정사각형 18×18 / 가로형 20×16 / 세로형 16×20 |
| 선 굵기 | **2px**, 끝과 꺾임 모두 둥글게 (round cap, round join) |
| 모서리 반경 | 2px (작은 요소 1px) |
| 최소 간격 | 요소 사이 1.5px 이상 (16px로 줄여도 뭉개지지 않게) |
| 정렬 | 가로·세로 선은 픽셀 격자에 맞춤 (16px, 24px 모두 선명하게) |

### 1.2 변형 (모든 아이콘 공통)
| 변형 | 용도 | 등급 |
|---|---|---|
| `outline` | 기본 | A |
| `filled` | 선택됨, 켜짐, 활성 상태 | A |
| `16` 전용 | 16px에서 디테일을 줄인 버전 (트레이, 작은 버튼). 24px 그림을 그냥 축소하지 않는다 | A (트레이·상태 아이콘), B (나머지) |
| `duotone` | 강조 화면, 빈 상태, 온보딩 | C |

### 1.3 색
- 아이콘 원본은 **단색 `currentColor`**. 색은 앱 테마가 칠한다 (라이트/다크 자동).
- 컬러가 고정되는 것은 **상태 배지, 트레이 아이콘, 앱 아이콘, 일러스트**뿐.
- 상태 색만으로 구분하지 않는다. **모양으로도 구분**되게 그린다 (색약 고려).

| 토큰 | 의미 | 라이트 | 다크 |
|---|---|---|---|
| `state-idle` | 대기 | `#6B7280` | `#9CA3AF` |
| `state-listening` | 듣는 중 | `#2563EB` | `#60A5FA` |
| `state-working` | 받아쓰기·생각 중 | `#D97706` | `#FBBF24` |
| `state-speaking` | 말하는 중 | `#059669` | `#34D399` |
| `state-error` | 오류 | `#DC2626` | `#F87171` |
| `state-muted` | 꺼짐·일시정지 | `#9CA3AF` | `#6B7280` |
| `sync-ok` / `sync-pending` / `sync-error` | 동기화 | `#059669` / `#D97706` / `#DC2626` | `#34D399` / `#FBBF24` / `#F87171` |
| `danger` | 안전 경고 | `#B91C1C` 바탕 + 흰 그림 | 동일 |

### 1.4 분위기(mood) 색 — 작업 카드, 마스코트, 말투 배지
| 분위기 | 색 | 느낌 |
|---|---|---|
| 차분 | `#64748B` (슬레이트) | 낮고 고른 |
| 진지 | `#1E3A8A` (짙은 남색) | 단단하고 각진 |
| 활기 | `#F59E0B` (주황) | 튀고 둥근 |
| 장난스러움 | `#EC4899` (핑크) | 기울고 통통 튀는 |
| 친근 | `#10B981` (초록) | 부드럽고 둥근 |

### 1.5 납품 형식
| 산출물 | 규격 |
|---|---|
| SVG 원본 | 24×24, 최적화(SVGO), `transform`·래스터 이미지·폰트 사용 금지, 선은 path로 변환하지 않음(outline 변형) |
| PNG | 16, 20, 24, 32, 40, 48, 64, 96, 128, 256 px. Windows 배율 100/125/150/200/300% 대응 |
| 앱 아이콘 `.ico` | 16, 20, 24, 32, 40, 48, 64, 96, 256 (32bit 알파) |
| 트레이 아이콘 | 16, 20, 24, 32 px × **작업표시줄 라이트용(검은 그림) / 다크용(흰 그림)** 두 벌 |
| 애니메이션 | 상태 아이콘 일부: SVG 프레임 시퀀스(최소 8프레임, 12fps) 또는 Lottie JSON |
| 파일 이름 | `{분류}-{이름}[-{변형}][@{크기}].{확장자}` 영어 kebab-case. 예: `state-listening-filled@16.png` |
| 묶음 | `icons/svg/`, `icons/png/{크기}/`, `icons/tray/{light,dark}/`, `icons/app/`, `icons/anim/`, `icons/illust/` + Qt 리소스 파일 `icons.qrc` |

### 1.6 상표
- GitHub, Claude, Elgato, Windows 로고는 **직접 그리지 않는다.** 필요한 곳은 각 회사의 공식 로고 파일을 브랜드 가이드에 맞게 쓰거나, 일반 기호(저장소, AI, 카메라)로 대체한다.

---

## 2. 앱 · 브랜드 (`app-`, `brand-`)

| ID | 이름 | 쓰는 곳 | 등급 |
|---|---|---|---|
| `app-icon` | 앱 아이콘 (풀컬러) | 실행 파일, 작업표시줄, 시작 메뉴 | A |
| `app-icon-mono` | 앱 아이콘 단색 | 트레이 기본, 흑백 인쇄 | A |
| `app-icon-badge` | 앱 아이콘 + 상태 점 자리 | 작업표시줄 오버레이 | B |
| `brand-wordmark` | "Torti" 글자 로고 (가로/세로) | 스플래시, 정보 화면, README | B |
| `brand-splash` | 스플래시 이미지 (640×400) | 시작 로딩 (STT 모델 로드 중) | B |
| `brand-mascot` | 마스코트 '토르티' 기본형 (형태는 디자이너 재량) | 온보딩, 빈 상태 | C |
| `brand-mascot-{mood}` | 마스코트 분위기 5종: calm, serious, lively, playful, friendly | 작업 카드, 인사 화면 | C |
| `brand-mascot-{state}` | 마스코트 상태 6종: idle, listening, thinking, speaking, error, sleeping | 큰 상태 표시 모드 | C |
| `brand-social` | GitHub 소셜 미리보기 (1280×640) | 저장소 대표 이미지 | C |
| `brand-favicon` | 파비콘 (16, 32, 180) | 문서 사이트 | C |

---

## 3. 트레이 · 작업표시줄 (`tray-`) — 16/20/24/32, 라이트·다크 두 벌

화면을 안 보는 앱이라 트레이가 사실상 **유일한 상시 표시**다. 16px에서도 한눈에 구분돼야 한다.

| ID | 상태 | 모양 힌트 | 등급 |
|---|---|---|---|
| `tray-idle` | 대기 | 앱 단색 아이콘 | A |
| `tray-listening` | 듣는 중 | 아이콘 + 파란 점 / 귀·파형 | A |
| `tray-working` | 받아쓰기·생각 중 | 아이콘 + 주황 점 3개 | A |
| `tray-speaking` | 말하는 중 | 아이콘 + 초록 음파 | A |
| `tray-error` | 오류 | 아이콘 + 빨간 느낌표 | A |
| `tray-paused` | 호출어 일시정지 (FR-04c) | 아이콘 + 일시정지 막대 | A |
| `tray-mic-off` | 마이크 없음·음소거 | 아이콘 + 사선 마이크 | A |
| `tray-cli-offline` | Claude CLI 로그인 필요·연결 안 됨 | 아이콘 + 끊긴 고리 | A |
| `tray-limit` | 사용량 한도 도달 | 아이콘 + 모래시계 | A |
| `tray-syncing` | GitHub 동기화 중 | 아이콘 + 회전 화살표 (애니메이션) | B |
| `tray-sync-error` | 동기화 실패·충돌 | 아이콘 + 빨간 화살표 | B |
| `tray-analyzing` | 작업 분석 중 | 아이콘 + 돋보기 | B |
| `tray-gpu-off` | GPU 없음, CPU로 동작 중 | 아이콘 + 거북이 | C |
| `tray-update` | 업데이트 있음 | 아이콘 + 위 화살표 점 | C |

---

## 4. 음성 상태 (`state-`) — 메인 화면 큰 상태 표시, 애니메이션 포함

| ID | 상태 (상태 머신) | 애니메이션 | 등급 |
|---|---|---|---|
| `state-idle` | IDLE | 천천히 숨쉬기 (선택) | A |
| `state-listening` | LISTENING | 입력 레벨에 반응하는 파형 | A |
| `state-transcribing` | TRANSCRIBING | 파형 → 글자 줄 | A |
| `state-thinking` | THINKING | 점 3개 순차 깜빡임 | A |
| `state-speaking` | SPEAKING | 스피커 음파 | A |
| `state-interrupted` | 끼어들기(Barge-in) | 음파가 끊기는 컷 | A |
| `state-no-speech` | 말소리 없음 | 빈 말풍선 | A |
| `state-cancelled` | 취소 | 되돌림 화살표 | A |
| `state-error` | 오류 | 흔들림 1회 | A |
| `state-hold` | 누른 채 말하는 중 (Push-to-talk) | 눌린 버튼 + 파형 | A |
| `state-follow-up` | 후속 질문 대기 (FR-07) | 줄어드는 원형 타이머 | B |
| `state-sleeping` | 호출어 꺼짐 | Zz | B |
| `state-waking` | 호출어 감지 | 반짝 | B |

---

## 5. 입력 · 트리거 (`input-`)

| ID | 이름 | 등급 |
|---|---|---|
| `input-mic` / `input-mic-off` | 마이크 / 음소거 | A |
| `input-mic-level` | 입력 레벨 미터 (막대 0~4 단계, 5장) | A |
| `input-hotkey` | 전역 단축키 (키캡) | A |
| `input-pedal` / `input-pedal-pressed` | 풋 페달 / 밟힘 | A |
| `input-tap` | 탭 방식 (한 번 누르기) | A |
| `input-hold` | 홀드 방식 (누르고 있기) | A |
| `input-wake-word` / `input-wake-word-off` | 호출어 켬 / 끔 | A |
| `input-vad` | 발화 끝 자동 감지 (무음 구간) | B |
| `input-noise-suppression` | 소음 억제 (흡연기 팬 등) | B |
| `input-sensitivity` | 호출어·VAD 감도 슬라이더 | B |
| `input-text` | 텍스트로 질문 (FR-05) | B |
| `input-headset` | 헤드셋 마이크 | C |
| `input-calibrate` | 마이크 소음 측정·보정 | C |
| `input-gesture` | 손짓 트리거 (카메라) | C |
| `input-stream-deck` | Stream Deck 키 트리거 | C |

---

## 6. 음성 출력 (`voice-`)

| ID | 이름 | 등급 |
|---|---|---|
| `voice-speaker` / `voice-speaker-off` | 스피커 / 음소거 | A |
| `voice-volume-0..3` | 음량 단계 4장 | A |
| `voice-tts` | 음성 합성 (말하는 입) | A |
| `voice-replay` | 다시 말해줘 (VC-02) | A |
| `voice-stop` | 멈춰 (VC-01) | A |
| `voice-slower` / `voice-faster` | 천천히 / 빠르게 (VC-04) | A |
| `voice-pitch-up` / `voice-pitch-down` | 음높이 | B |
| `voice-style` | 목소리 분위기 (분위기에 따라 자동) | B |
| `voice-speech-level` | 반말 / 존댓말 전환 (두 장) | B |
| `voice-earcon` | 효과음 켜기/끄기 | B |
| `voice-neural` | 신경망 TTS 엔진 | C |
| `voice-clone` | 내 목소리 등록 (음성 복제) | C |

---

## 7. 음성 명령 (`cmd-`) — 도움말 화면, 명령 목록, 토스트

| ID | 발화 | 등급 |
|---|---|---|
| `cmd-stop` | 멈춰, 그만 | A |
| `cmd-repeat` | 다시 말해줘 | A |
| `cmd-new-chat` | 새 대화 | A |
| `cmd-cancel` | 취소 | A |
| `cmd-note` | 기록해 둬 (메모 추가) | A |
| `cmd-sync` | 깃허브에 올려줘 | A |
| `cmd-reanalyze` | 작업 다시 살펴봐 | A |
| `cmd-recapture` | 사진 다시 찍어서 봐줘 (VC-05) | B |
| `cmd-zoom` | 확대해서 봐줘 (VC-06) | B |
| `cmd-detail` | 자세히 말해줘 (FR-31b) | B |
| `cmd-wake-off` | 호출어 꺼 | B |
| `cmd-timer` | 타이머 3분 (VC-08) | C |
| `cmd-next-step` | 다음 단계 | C |
| `cmd-checklist` | 체크리스트 읽어줘 | C |
| `cmd-measure` | 측정값 기록 (예: 4.98볼트 기록) | C |

---

## 8. 카메라 · 비전 (`cam-`)

| ID | 이름 | 등급 |
|---|---|---|
| `cam-camera` / `cam-camera-off` | 카메라 / 꺼짐 | A |
| `cam-switch` | 카메라 선택·전환 | A |
| `cam-capture` | 캡처 (셔터) | A |
| `cam-photo-attached` | 이 질문에 사진 첨부됨 | A |
| `cam-no-photo` | 사진 없이 질문 (FR-16) | A |
| `cam-photo-auto` | 사진 자동 판단 모드 | A |
| `cam-roi` | 관심 영역 지정 (점선 사각형 + 손잡이) | B |
| `cam-zoom-in` / `cam-zoom-out` | 확대 / 축소 | B |
| `cam-retake` | 다시 찍기 | B |
| `cam-resolution` | 해상도 배지 3장: 720, 1080, 4K | B |
| `cam-exposure` | 밝기·노출 | B |
| `cam-focus` | 초점 | B |
| `cam-light` | 조명 켜기 (Key Light 등 연동 대비) | C |
| `cam-microscope` | 보조 카메라: USB 현미경 (FR-14) | C |
| `cam-multi` | 카메라 2대 동시 | C |
| `cam-grid` | 격자 표시 | C |
| `cam-flip` / `cam-rotate` | 좌우 반전 / 회전 | C |
| `cam-privacy` | 사람 가림 (개인정보 보호 영역) | C |
| `cam-overhead` | 위에서 내려다보는 거치 (설치 안내) | C |
| `cam-compare` | 이전 사진과 비교 | C |

---

## 9. AI · 대화 (`ai-`)

| ID | 이름 | 등급 |
|---|---|---|
| `ai-question` | 사용자 질문 말풍선 | A |
| `ai-answer` | 토르티 답변 말풍선 | A |
| `ai-thinking` | 생각 중 | A |
| `ai-new-chat` | 새 대화 (맥락 초기화) | A |
| `ai-model-fast` | 빠른 모델 (번개) | A |
| `ai-model-accurate` | 정확한 모델 (과녁) | A |
| `ai-safety-notice` | "AI 답변은 참고용" 고지 (NFR-07) | A |
| `ai-uncertain` | 판독 불확실, 확인 필요 | A |
| `ai-cli` | Claude CLI 상태 (일반 터미널 기호, 상표 로고 아님) | A |
| `ai-login-required` | 로그인 필요 | A |
| `ai-usage-limit` | 사용량 한도 | A |
| `ai-billing-warning` | API 키 감지, 과금 위험 경고 (NFR-04b) | A |
| `ai-effort` | 생각 깊이 (low~max 단계 5장) | B |
| `ai-copy` | 답변 복사 | B |
| `ai-regenerate` | 다시 답하기 | B |
| `ai-feedback-up` / `ai-feedback-down` | 좋아요 / 별로예요 | C |
| `ai-confidence-high/mid/low` | 확신도 3단계 | C |
| `ai-source-notes` / `ai-source-datasheet` / `ai-source-photo` | 답변 근거 표시: 메모 / 데이터시트 / 사진 | C |

---

## 10. 작업(프로젝트) · GitHub (`proj-`, `git-`)

| ID | 이름 | 등급 |
|---|---|---|
| `proj-project` | 작업 (폴더 + 공구) | A |
| `proj-new` | 새 작업 | A |
| `proj-continue` | 이어서 하기 | A |
| `proj-clone` | 저장소에서 가져오기 | A |
| `proj-list` | 작업 목록 | A |
| `proj-brief` | 작업 브리핑 (문서 + 돋보기) | A |
| `proj-analyzing` | 분석 중 (애니메이션) | A |
| `proj-reanalyze` | 다시 분석 | A |
| `proj-notes` | 메모 (NOTES.md) | A |
| `proj-log` | 작업 기록 (log/) | A |
| `proj-instructions` | 작업 지침 (CLAUDE.md) | A |
| `proj-datasheet` | 데이터시트 PDF | B |
| `proj-next-step` | 다음 단계 | A |
| `proj-progress` | 진행률 (0, 25, 50, 75, 100% 다섯 장) | B |
| `proj-checklist` | 작업 순서 체크리스트 | B |
| `proj-archive` | 완료된 작업 보관 | C |
| `proj-template` | 작업 템플릿 | C |
| `proj-share` | 작업 공유 | C |
| `git-repo` | 저장소 (일반 기호) | A |
| `git-repo-private` | 비공개 저장소 (자물쇠) | A |
| `git-sync` | 동기화 (양방향 화살표) | A |
| `git-synced` | 최신 상태 (체크) | A |
| `git-pending` | 올릴 변경 있음 (점) | A |
| `git-push` / `git-pull` | 올리기 / 받기 | A |
| `git-commit` | 커밋 (점과 선) | A |
| `git-conflict` | 충돌 (FR-57) | A |
| `git-offline` | 원격 없음·오프라인 | A |
| `git-photos-local` | 사진은 로컬에만 (FR-56) | A |
| `git-photos-push` | 사진도 올리기 켬 | B |
| `git-branch` | 브랜치 | C |
| `git-history` | 커밋 기록 | C |

---

## 11. 작업 분야 배지 (`domain-`) — 작업마다 분야가 다르다 (FR-59)

작업 카드, 브리핑 화면, 트레이 툴팁에 붙는 분야 배지. **24px 아이콘 + 원형 배지(색 바탕) 두 벌**.

| ID | 분야 | 등급 |
|---|---|---|
| `domain-soldering` | 납땜 (인두) | A |
| `domain-electronics` | 전자 회로 (칩) | A |
| `domain-firmware` | 펌웨어·코딩 (`</>` + 칩) | A |
| `domain-3d-printing` | 3D 프린팅 (노즐 + 레이어) | A |
| `domain-woodworking` | 목공 (톱·대패) | A |
| `domain-assembly` | 조립 (나사·렌치) | A |
| `domain-repair` | 수리·분해 | A |
| `domain-general` | 기타 작업 | A |
| `domain-laser` | 레이저 커팅·각인 | B |
| `domain-cnc` | CNC 가공 | B |
| `domain-metal` | 금속 가공·용접 | B |
| `domain-painting` | 도색·에어브러시 | B |
| `domain-sewing` | 재봉·가죽 | B |
| `domain-resin` | 레진·몰딩 | B |
| `domain-keyboard` | 키보드 빌드 (키캡) | B |
| `domain-robotics` | 로봇 | B |
| `domain-power` | 전원·배터리 | B |
| `domain-audio` | 오디오 (스피커) | B |
| `domain-lighting` | 조명·LED | B |
| `domain-drone` | 드론·RC | C |
| `domain-cosplay` | 코스프레·소품 | C |
| `domain-model-kit` | 프라모델 | C |
| `domain-jewelry` | 공예·액세서리 | C |
| `domain-car` | 자동차·바이크 정비 | C |
| `domain-plumbing` | 집수리·배관 | C |
| `domain-gardening` | 원예·스마트팜 | C |
| `domain-cooking` | 요리 (혹시 몰라서) | C |

---

## 12. 분위기 · 말투 (`mood-`) — 브리핑 결과, 작업 카드

| ID | 이름 | 등급 |
|---|---|---|
| `mood-calm` | 차분 | A |
| `mood-serious` | 진지 | A |
| `mood-lively` | 활기 | A |
| `mood-playful` | 장난스러움 | A |
| `mood-friendly` | 친근 | A |
| `mood-banmal` / `mood-jondaetmal` | 반말 / 존댓말 | A |
| `mood-custom` | 사용자 지정 말투 (NOTES.md "## 말투") | B |
| `mood-auto` | 자동 (작업에 맞춤) | B |

---

## 13. 도구 · 부품 (`tool-`, `part-`) — 메모·기록·체크리스트·브리핑의 그림 기호

### 13.1 전자
| ID | 이름 | 등급 |
|---|---|---|
| `part-resistor` | 저항 (색띠) | A |
| `part-capacitor` / `part-capacitor-polar` | 커패시터 / 전해 (극성) | A |
| `part-diode` | 다이오드 | A |
| `part-led` | LED | A |
| `part-transistor` | 트랜지스터 | B |
| `part-ic-dip` / `part-ic-smd` | IC (DIP / SMD) | A |
| `part-header` | 헤더 핀·커넥터 | B |
| `part-pcb` | PCB | A |
| `part-wire` | 전선 | B |
| `part-switch` / `part-button` | 스위치 / 택트 버튼 | B |
| `part-battery` / `part-battery-holder` | 배터리 / 홀더 | B |
| `part-fuse` | 퓨즈 | B |
| `part-transformer` | 변압기 | C |
| `part-motor` / `part-servo` | 모터 / 서보 | C |
| `part-sensor` | 센서 | C |
| `part-mcu` | 마이크로컨트롤러 보드 (일반형, 상표 없이) | B |
| `part-crystal` | 크리스털 | C |
| `part-inductor` | 인덕터 | C |
| `part-relay` | 릴레이 | C |
| `part-heatsink` | 방열판 | C |

### 13.2 공구 · 재료
| ID | 이름 | 등급 |
|---|---|---|
| `tool-soldering-iron` | 인두 | A |
| `tool-solder` | 실납 | A |
| `tool-flux` | 플럭스 | A |
| `tool-multimeter` | 멀티미터 | A |
| `tool-tweezers` | 핀셋 | B |
| `tool-desolder-pump` / `tool-desolder-wick` | 솔더 흡입기 / 솔더 윅 | B |
| `tool-fume-extractor` | 흡연기 | B |
| `tool-helping-hands` | 집게 스탠드 | B |
| `tool-magnifier` | 확대경 | B |
| `tool-hot-air` | 열풍기 | C |
| `tool-oscilloscope` | 오실로스코프 | C |
| `tool-power-supply` | 파워 서플라이 | C |
| `tool-heat-shrink` | 수축 튜브 | C |
| `tool-glue-gun` | 글루건 | C |
| `tool-screwdriver` / `tool-wrench` / `tool-pliers` / `tool-cutter` | 드라이버 / 렌치 / 플라이어 / 니퍼 | B |
| `tool-caliper` / `tool-ruler` | 캘리퍼스 / 자 | B |
| `tool-clamp` | 클램프 | B |
| `tool-drill` / `tool-saw` / `tool-trimmer` / `tool-sander` | 드릴 / 톱 / 트리머 / 샌더 | B |
| `tool-sandpaper` / `tool-wood-glue` | 사포 / 목공풀 | C |
| `tool-filament` / `tool-nozzle` / `tool-print-bed` | 필라멘트 / 노즐 / 베드 | B |
| `tool-laptop` / `tool-usb-cable` | 노트북 / USB 케이블 (펌웨어 작업) | B |
| `tool-brush` / `tool-airbrush` | 붓 / 에어브러시 | C |
| `tool-needle` / `tool-sewing-machine` | 바늘 / 재봉틀 | C |

---

## 14. 안전 · 경고 (`safety-`) — 답변 강조, 브리핑 주의사항, 토스트

경고 표지판 형태(삼각형·원형)로 통일. **빨강 바탕 + 흰 그림** 컬러판과 단색판 두 벌.

| ID | 이름 | 등급 |
|---|---|---|
| `safety-hot` | 화상 주의 (뜨거운 표면) | A |
| `safety-high-voltage` | 감전·고전압 | A |
| `safety-short` | 단락 | A |
| `safety-power-on` | 전원 연결된 채 작업 중 | A |
| `safety-fumes` | 유해 연기 (환기) | A |
| `safety-sharp` | 날붙이·회전 공구 | A |
| `safety-battery` | 배터리 화재·팽창 | B |
| `safety-eye` | 보안경 착용 | B |
| `safety-esd` | 정전기 주의 | B |
| `safety-polarity` | 극성 주의 | B |
| `safety-ventilation` | 환기 | B |
| `safety-gloves` | 장갑 착용 | C |
| `safety-ear` | 귀 보호 (소음) | C |
| `safety-chemical` | 화학약품 (레진, 용제) | C |
| `safety-fire` | 화재 | C |
| `safety-first-aid` | 응급처치 | C |

---

## 15. 기록 · 히스토리 (`hist-`)

| ID | 이름 | 등급 |
|---|---|---|
| `hist-history` | 기록 목록 | A |
| `hist-day` | 날짜별 (달력) | B |
| `hist-search` | 기록 검색 | B |
| `hist-filter` | 필터 (사진 있음, 오류, 끼어들기) | B |
| `hist-audio` | 녹음 재생 (WAV) | B |
| `hist-photo` | 사진 썸네일 자리 | B |
| `hist-latency` | 지연시간 (스톱워치) | B |
| `hist-export` | Markdown 내보내기 (FR-62) | C |
| `hist-bookmark` | 중요 표시 | C |
| `hist-timeline` | 작업 타임라인 | C |
| `hist-stats` | 사용량·통계 | C |

---

## 16. 설정 (`set-`)

| ID | 이름 | 등급 |
|---|---|---|
| `set-settings` | 설정 (톱니) | A |
| `set-devices` | 장치 (마이크·스피커·캠 묶음) | A |
| `set-hotkey` | 단축키 | A |
| `set-model` | AI 모델 | A |
| `set-voice` | 목소리 | A |
| `set-stt` | 음성 인식 모델 | A |
| `set-gpu` / `set-cpu` | GPU (CUDA) / CPU 폴백 | B |
| `set-storage` | 저장 위치 | B |
| `set-privacy` | 개인정보 (로컬 처리) | B |
| `set-cli-path` | CLI 경로 | B |
| `set-startup` | 윈도우 시작 시 실행 | B |
| `set-language` | 언어 | C |
| `set-theme` | 테마 (라이트/다크) | C |
| `set-debug` | 로그·진단 | B |
| `set-update` | 업데이트 | C |
| `set-about` | 정보 | B |
| `set-reset` | 초기화 | C |
| `set-backup` | 설정 백업/복원 | C |

---

## 17. 공통 UI (`ui-`)

A 등급: `ui-add`, `ui-remove`, `ui-edit`, `ui-save`, `ui-close`, `ui-check`, `ui-info`, `ui-warning`, `ui-error`, `ui-help`, `ui-refresh`, `ui-more`(⋯), `ui-menu`, `ui-search`, `ui-chevron-{up,down,left,right}`, `ui-expand`, `ui-collapse`, `ui-play`, `ui-pause`, `ui-stop`, `ui-record`, `ui-folder-open`, `ui-file`, `ui-image`, `ui-link-external`, `ui-copy`, `ui-minimize-to-tray`, `ui-pin`, `ui-unpin`, `ui-eye`, `ui-eye-off`, `ui-lock`, `ui-unlock`, `ui-clock`, `ui-keyboard`

B 등급: `ui-undo`, `ui-redo`, `ui-paste`, `ui-download`, `ui-upload`, `ui-sort`, `ui-filter`, `ui-drag-handle`, `ui-bell`, `ui-bell-off`, `ui-star`, `ui-trash`, `ui-back`, `ui-forward`, `ui-fullscreen`, `ui-exit-fullscreen`, `ui-split-view`, `ui-list-view`, `ui-grid-view`

C 등급: `ui-qr`, `ui-phone`, `ui-share`, `ui-print`, `ui-cloud`, `ui-wifi-off`, `ui-battery-level`, `ui-moon`, `ui-sun`

---

## 18. 알림 · 토스트 (`toast-`) — 32px 컬러, 윈도우 알림 앱 로고 256px

| ID | 상황 | 등급 |
|---|---|---|
| `toast-success` / `toast-warning` / `toast-error` / `toast-info` | 기본 4종 | A |
| `toast-synced` | GitHub에 올렸어요 | A |
| `toast-analysis-done` | 작업 분석 완료 | A |
| `toast-limit` | 사용량 한도 | A |
| `toast-login-expiring` | Claude 로그인 만료 임박 | B |
| `toast-device-lost` | 마이크·카메라 연결 끊김 | A |
| `toast-gpu-fallback` | GPU를 못 써서 CPU로 전환 | B |
| `toast-timer-done` | 타이머 끝 (VC-08) | C |
| `toast-app-logo` | 윈도우 알림용 앱 로고 (256 PNG) | A |

---

## 19. 빈 상태 · 온보딩 일러스트 (`illust-`) — 128/256px, duotone 또는 컬러

| ID | 화면 | 등급 |
|---|---|---|
| `illust-welcome` | 첫 실행 환영 | A |
| `illust-safety` | 안전 고지 (AI 답변은 참고용) | A |
| `illust-cli-login` | Claude CLI 로그인 안내 | A |
| `illust-no-project` | 작업 없음 → 새 작업 만들기 | A |
| `illust-no-history` | 기록 없음 | B |
| `illust-no-camera` | 카메라 없음·연결 안 됨 | B |
| `illust-no-mic` | 마이크 신호 없음 (음소거 확인 안내) | A |
| `illust-pedal-setup` | 페달 연결·키 매핑 안내 | B |
| `illust-camera-setup` | 캠을 위에서 책상 전체가 보이게 거치 | B |
| `illust-wake-word` | 호출어 연습 | C |
| `illust-all-synced` | 모두 동기화됨 | C |
| `illust-analyzing` | 작업 분석 중 (큰 애니메이션) | B |
| `illust-github-connect` | 저장소 연결 안내 | B |
| `illust-error` | 알 수 없는 오류 | B |

---

## 20. 외부 기기 · 배포물 (혹시 몰라서) (`ext-`, `pkg-`)

| ID | 규격 | 쓰는 곳 | 등급 |
|---|---|---|---|
| `ext-streamdeck-key-*` | 72×72, 144×144 (@2x) 키 이미지 | Stream Deck 키: 말하기, 멈춤, 다시 말해줘, 새 대화, 캡처, 동기화, 다시 분석, 호출어 켬/끔 (각 켜짐·꺼짐 상태) | C |
| `ext-streamdeck-action` | 20×20, 40×40 | Stream Deck 플러그인 동작 목록 | C |
| `ext-streamdeck-category` | 28×28, 56×56 | Stream Deck 플러그인 분류 | C |
| `ext-streamdeck-plugin` | 256×256, 512×512 | 플러그인 대표 아이콘 | C |
| `ext-obs-overlay` | 투명 PNG 상태 배지 (256) | 작업 방송·녹화 화면에 상태 표시 | C |
| `ext-phone-companion` | 앱 아이콘 (iOS·Android 규격) | 폰으로 상태 보기 | C |
| `pkg-installer-wizard` | Inno Setup 큰 이미지 (164×314 및 고DPI 배수) | 설치 마법사 | B |
| `pkg-installer-small` | Inno Setup 작은 이미지 (55×58 및 고DPI 배수) | 설치 마법사 상단 | B |
| `pkg-installer-icon` | .ico | 설치 파일 | B |
| `pkg-uninstall` | .ico | 제거 프로그램 | C |
| `pkg-readme-badges` | 상태 배지 (SVG) | README | C |

---

## 21. 수량 요약

| 분류 | A | B | C |
|---|---|---|---|
| 앱·브랜드 | 2 | 3 | 15 (마스코트 11종 포함) |
| 트레이 | 9 | 3 | 2 |
| 음성 상태 | 10 | 3 | 0 |
| 입력·트리거 | 9 | 4 | 4 |
| 음성 출력 | 9 | 5 | 2 |
| 음성 명령 | 7 | 4 | 4 |
| 카메라·비전 | 7 | 10 | 9 |
| AI·대화 | 11 | 3 | 7 |
| 작업·GitHub | 24 | 4 | 5 |
| 작업 분야 | 8 | 11 | 8 |
| 분위기·말투 | 7 | 2 | 0 |
| 도구·부품 | 13 | 30 | 22 |
| 안전·경고 | 6 | 5 | 5 |
| 기록 | 1 | 6 | 4 |
| 설정 | 6 | 7 | 5 |
| 공통 UI | 39 | 19 | 9 |
| 알림 | 8 | 2 | 1 |
| 일러스트 | 5 | 7 | 2 |
| 외부 기기·배포물 | 0 | 3 | 8 |
| **합계 (그림 기준, 대략)** | **약 180** | **약 130** | **약 110** |

- 그림 약 420개 × 변형(outline/filled, 16 전용, 라이트/다크 트레이) × PNG 크기 → 파일은 수천 개. **SVG 원본만 손으로 만들고 PNG·ICO·qrc는 스크립트로 생성**한다.
- 만드는 순서: **A 등급 전체 → 트레이 16px 최적화 → B → C**.

---

## 22. AI 이미지 생성 시 공통 프롬프트 (선택)

여러 번 나눠 생성해도 같은 세트처럼 보이게, 모든 요청에 아래 문장을 붙인다.

```
Minimal line icon, 24x24 grid, 2px uniform stroke, rounded caps and joins,
2px corner radius, no fill, single color black on transparent background,
centered with 2px padding, consistent optical weight, no text, no gradients,
no shadows, no brand logos, pixel-aligned horizontal and vertical lines.
Subject: {아이콘 설명 영어로}
```

- 생성 결과는 래스터이므로 **최종본은 SVG로 다시 그리거나 벡터화 후 선 굵기와 격자를 정리**한다.
- 상태 색, 분위기 색은 생성 단계가 아니라 앱 테마에서 입힌다.

---

## 23. 검수 체크리스트

- [ ] 16px로 줄여도 트레이 상태 9종(A)이 서로 구분된다
- [ ] 라이트·다크 작업표시줄 모두에서 트레이 아이콘이 보인다
- [ ] 색을 빼도(흑백) 상태가 모양으로 구분된다
- [ ] 같은 분류 안에서 선 굵기, 모서리, 여백이 일정하다
- [ ] 상표 로고를 직접 그린 것이 없다
- [ ] 파일 이름이 규칙을 따르고 `icons.qrc`에 모두 등록됐다
- [ ] 애니메이션 아이콘은 첫 프레임만으로도 의미가 통한다
