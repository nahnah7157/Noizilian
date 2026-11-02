# 프로젝트: Noizilian

골든 레코드에서 지구 요리를 보고 따라 만들다 실패한 외계인을, 말 대신 색·질감 타일을 주고받으며 도와 요리를 완성하는 캐릭터 챗봇입니다.

## 컨셉 (기준: config/chatbot_config.json)
- 요리 4단계: 재료 준비 → 손질 → 조리 → 플레이팅. 한 단계 = 한 턴
- 한 턴 안에서 타일을 여러 번 주고받는다. 외계인의 확신이 기준(0.8)을 넘거나 최대 횟수(임시 4번)에 닿으면 다음 단계로
- 외계인은 매번 타일 + 표정으로 응답한다. 표정 이미지는 아직 없어서 단계별 포즈(기본 / 칼 / 프라이팬)를 대신 쓴다
- 네 단계에서 확정된 타일이 요리 목표와 가까우면 성공, 멀면 실패 이미지 (햄버거·오므라이스·피자·라멘)
- 외계인 이미지는 귀여운 그림체(alien_cute_*)만 쓴다
- 감각 규칙: Lucassen, Gevers, Gijsenij (2011) "Texture Affects Color Emotion" Table III. 근거는 data/knowledge/paper_rules.md의 R1~R15

## 스택
- Frontend: HTML/CSS/JS (templates/, public/assets/). 빌드 도구 없음
- Backend: Flask (app.py, services/)
- 모델: OpenAI (설정은 docs/MODEL_SETUP.md, 키는 로컬 .env에만)
- Python 3.12 (Conda 환경). 실행 방법과 팀 환경은 ENVIRONMENT.txt

## 파일 배치 (새 파일을 만들지 않는다)
베이스 코드의 파일 구조를 그대로 쓴다. 새 기능은 아래 중 가장 알맞은 기존 파일에 넣는다.

| 하는 일 | 파일 |
| --- | --- |
| 캐릭터·단계·요리·주고받기 설정 | config/chatbot_config.json |
| 논문 기준 등 챗봇이 참고할 자료 | data/knowledge/ |
| 자료 검색 | services/retriever.py |
| 외계인 응답 생성 (다음 추측 타일·표정·말). GPT 연결 자리 | services/generator.py |
| 이미지 선택 | services/image_selector.py, public/assets/images/ |
| 타일 → 감각 점수(1부), 확신·단계·요리 판정(2부), 응답 조립(3부) | services/chatbot_service.py |
| API 라우팅·요청 검증 | app.py |
| 화면 (학종이 작성기 + 채팅) | templates/, public/assets/css/, public/assets/js/chatbot.js |
| 테스트 | tests/test_smoke.py |

## 코드 구조에서 지킬 것
- 감각 공식은 두 곳에 있음: public/assets/js/chatbot.js(브라우저)와 services/chatbot_service.py 1부(서버). 한쪽을 고치면 다른 쪽도 같이 고친다
- 서버는 브라우저가 보낸 점수를 믿지 않고 색·질감 값으로 다시 계산한다
- 진행 상태(state)는 브라우저가 들고 다니고 서버는 저장하지 않는다. 서버는 받은 state를 app.py의 parse_state로 검증한다
- API 계약 (바꾸면 app.py, chatbot.js, 테스트를 같이 고친다)
  - POST /api/start {dish?} → {reply, image, sources, alien, state, stage, dish, result}
  - POST /api/chat {message, username, signal, state?} → 위와 같음. state가 없으면 기존 대화 흐름
  - alien = {scores, word, expression, reading}, state = {dish, stage_index, exchange_count, confidence, alien_scores, finals, done}
- generator.py의 first_guess / respond_to_tile / finish는 반환 형식(dict: scores, word, expression, reading, reply)을 유지한다

## 현재 진행 상황 (2026-11-02)
- 완료: 학종이 작성기, 4단계 요리 API 및 로직. 테스트 39개
- 완료: docs/design/03_stage1_ingredients.png 와이어프레임으로 채팅 화면 전면 재배치 (chat.html, style.css, chatbot.js)
  - 배경 가득 + 좌상단 제목(#title) + 가운데 외계인 이미지 하나만. 입력창·단계 안내 글·확신 막대·알림 전부 제거(게임 화면에 한국어 설명 없음). 보내기는 message="타일" 고정(app.py 안 건드림)
  - 오른쪽: HSV 색 선택기(가로 채도·세로 명도 + 무지개 hue 막대, 클릭·드래그). 고른 HSV→RGB→CIELAB(L·C·h)로 변환해 signal.color로 보냄(chatbot.js 1번에 hsvToRgb·rgbToLch 추가). 크기·밀도 막대는 아이콘만
  - 왼쪽: 기록 2줄(윗줄 외계인+머리 아이콘·4단계 / 아랫줄 나+흰 원·4단계), 현재 단계 칸 하이라이트·교환마다 갱신(단계 끝나면 마지막 타일 고정). 큰 미리보기. 되돌리기(↺ 파랑)·보내기(✓ 초록) 아이콘 버튼. "패턴 바꾸기" 제거
- 완료: 결과 화면 골든 레코드 교체 (chat.html, style.css, chatbot.js 7번, image_selector.py, app.py)
  - golden_record_cut.png를 원본 기호를 지운 깨끗한 원판으로 교체 (원본 golden_record.png는 그대로)
  - 주고받은 타일마다 무작위 기호 3개(한 묶음)를 나선 홈에 새김. 묶음에 마우스를 올리면 ① 타일 점수 + 무작위 3음 패턴 소리(Web Audio, [앱 설정] 무거움→음높이·따뜻함→장/단조·단단함→파형) ② 타일을 말로 옮긴 대사 ③ 외계인 대사면 그림
  - POST /api/record: OpenAI가 paper_rules.md 기준으로 타일마다 재료·손질·조리·플레이팅 대사를 만들고(generator.record_lines), 외계인 대사는 config.record.line_images 설명과 OpenAI 임베딩(text-embedding-3-small)으로 비교해 외계인 3장 중 그림을 고름(image_selector.pick_line_images). 키 없으면 config.record.fallback_lines
  - 요리 결과(success)를 /api/record에 함께 보내, 실패면 엉뚱한 요리 방법 대화를 여러 번, 성공이어도 한 번 넣음 (키 없으면 fallback_lines.wrong)
  - 대화 순서: 12시에서 시작해 시계방향, 한 바퀴(12타일)마다 안쪽 홈으로 이어짐
  - 논문 근거 문장과 결과 화면 외계인 대사(result-line)는 표시 안 함
- 완료: 외계인 대사 제거. config의 greeting·stages[].alien_line·result.success_line/fail_line 삭제, persona.speaking_style을 "말하지 않음"으로. generator.py의 "…지직" 대사 삭제 → alien.word는 항상 ""(형식 유지), reply는 괄호 지문만(화면에 안 보임). judge_dish 결과의 line 삭제
- 외계인 응답은 아직 임시 규칙(추측을 사용자 쪽으로 절반씩 옮김). GPT로 바꿀 예정
- 다음 작업 순서
  1. GPT 연결: generator.py의 respond_to_tile·first_guess를 OpenAI 호출로 교체 (docs/MODEL_SETUP.md 참고)
  2. 검색: retriever.py가 현재 단계의 축에 맞는 paper_rules.md 기준을 찾아 GPT에 넘김
  3. 디자인 토큰(tokens.css), 배포
- 팀 확정 필요: 부엌 전용 배경 이미지(지금은 background_basic.png 유지), config의 "초안: 팀 확정 필요" 값(확신 기준·상승 폭·최대 횟수·요리 목표 점수·성공 거리), 표정 이미지, 레코드 소리 대응·대체 대사(fallback_lines)

## 디자인 규칙
- 색, 간격, 폰트는 public/assets/css/tokens.css의 변수만 사용. 새 색상 하드코딩 금지 (tokens.css는 레퍼런스 확정 후 작성 예정)
- 레퍼런스 이미지: docs/design/
- 레퍼런스는 구조와 분위기만 참고. 로고, 일러스트, 사진, 문구는 가져오지 않음

## 작업 규칙
- 한 번에 한 기능만. 끝나면 실행하고 확인하는 방법을 알려줄 것
- 새 라이브러리를 추가하기 전에 먼저 물어볼 것. 추가하면 requirements.txt와 ENVIRONMENT.txt를 같이 고칠 것
- .env와 API 키는 절대 커밋하지 않음
- main에 직접 커밋하지 않음. 브랜치 → PR → 리뷰 → merge
- 커밋 메시지는 feat / fix / docs / test / refactor / style / chore 접두어 사용
- 바꾼 뒤에는 python -m unittest discover -s tests -v 로 테스트
- 작업이 끝날 때마다 "현재 진행 상황"을 갱신한다
