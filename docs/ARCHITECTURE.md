# 코드 구조

Flask 앱 하나가 화면과 API를 함께 제공합니다. 게임 규칙(감각 점수·판정)은 서버가 계산하고, 외계인의 판단·레코드 대사·그림 선택은 OpenAI를 쓰되 실패하면 규칙으로 대신합니다. 진행 상태(state)는 브라우저가 들고 다니고 서버는 저장하지 않습니다.

API 요청·응답 필드와 지켜야 할 규칙은 [AGENTS.md](../AGENTS.md)의 "코드 구조에서 지킬 것"이 기준입니다. 이 문서는 전체 지도입니다.

## 디렉터리

```text
app.py                         화면 라우트, API, 요청·state 검증, 호출 한도, asset 주소(?v=수정 시각)
config/chatbot_config.json     숫자·문구는 전부 여기: 단계·요리·색 언어·판정 기준·표정·인트로·소리
services/
  chatbot_service.py           1부 감각 점수(논문 공식) · 2부 이해 누적·판정·확신·표정 · 3부 응답 조립
  generator.py                 외계인 판단(decide_turn, OpenAI) · 레코드 대사(record_lines) · 규칙 대체 문장
  retriever.py                 cooking_rules.md를 "## 메뉴 · 단계" 제목으로 검색, record_lines.md 예시를 타일 태그로 검색
  image_selector.py            표정 그림 선택, 레코드 대사에 맞는 외계인 그림(문장부호 + 임베딩)
templates/                     index(시작) · detail(이름·성별 + 티저 영상) · chat(컷신·게임·결과)
public/assets/
  css/style.css                화면 전체(UI 색 변수는 맨 위 :root)
  js/chatbot.js                브라우저: 타일 작성기·감각 공식(서버와 같은 식)·게임 진행·결과 화면·소리
  images/ sounds/ video/       그림·효과음·배경음악·티저 영상
data/knowledge/                paper_rules.md(논문 근거 R1~R15) · cooking_rules.md(색 언어·요리 규칙) · record_lines.md(레코드 대사 예시)
data/images/                   화면에 쓰지 않는 참고용 그림
tests/test_smoke.py            스모크·규칙·API 테스트 (OpenAI는 mock, 실제 호출 없음)
docs/design/                   와이어프레임·참고 시안(읽기 전용)
```

## 요청 흐름

```text
GET /        시작 화면(히어로샷)
GET /detail  이름·성별 → 시작하기 → 티저 영상 → /chat?username=…&player=male|female
GET /chat    컷신 → 게임 → 결과 (chatbot.js)

POST /api/start   {dish?}                         → 첫 state·첫 단계
POST /api/chat    {message, username, signal, state}
                  → app.py: signal·state 검증(parse_state), 브라우저가 보낸 점수는 버리고 색·질감으로 다시 계산
                  → ChatbotService.play_turn()
                      감각 점수 → 판정값(game_metrics) → 쌓인 신호(stage_signal) → 단계 판정(judge_stage)
                      → 외계인 판단 generator.decide_turn (OpenAI, 실패·키 없음이면 규칙 확신)
                      → 표정 turn_expression → 다음 단계 또는 retry, 마지막 단계면 요리 결과(judge_menu_result)
                  → {reply, image, sources, alien, state, stage, dish, result, …}
POST /api/record  {dish, success, entries}       → 타일마다 레코드 대사·외계인 그림 (마지막 응답 직후 미리 요청)
GET  /health      앱 프로세스 응답 확인
```

OpenAI를 부르는 곳은 세 군데(외계인 판단, 레코드 대사, 그림 임베딩)이고, 모두 실패하거나 키가 없으면 규칙·예시로 대신해 게임은 끝까지 진행됩니다. IP별·하루 호출 한도는 `app.py`의 `llm_allowed`가 셉니다.

## 꼭 같이 고칠 것

- **감각 공식**은 `chatbot.js`(브라우저 미리보기)와 `chatbot_service.py` 1부(서버 판정) 두 곳에 있습니다. 한쪽을 고치면 다른 쪽도 고치고 테스트를 돌립니다. 근거는 `data/knowledge/paper_rules.md`, 규칙은 `.claude/rules/sense-model.md`.
- **API 응답 필드**를 바꾸면 `app.py`, `chatbot.js`, `tests/test_smoke.py`를 같이 고칩니다.
- 화면에 쓰는 **숫자·문구**는 코드보다 `config/chatbot_config.json`에서 먼저 찾습니다. 브라우저가 config를 직접 못 읽는 값(축 낱말 `SENSE_WORDS` 등)은 `chatbot.js`에 따로 있습니다.

## 검증

```bash
python -m unittest discover -s tests -v
```

화면 배치·연출·소리 순서는 자동 테스트가 보지 않습니다. 바꾼 뒤에는 1920×1080과 390×844에서 직접 확인합니다.
