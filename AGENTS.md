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

## 현재 진행 상황 (2026-11-01)
- 완료: 학종이 작성기, 4단계 요리 API 및 로직, 화면 연결(chatbot.js, chat.html, style.css). 와이어프레임 기반 레이아웃 3단계 완료(1/3: HTML/CSS, 2/3: 색상 선택 UI + 질감 슬라이더, 3/3: 타일 기록 갱신). 테스트 38개
- 외계인 응답은 아직 임시 규칙(추측을 사용자 쪽으로 절반씩 옮김). GPT로 바꿀 예정
- 다음 작업 순서
  1. GPT 연결: generator.py의 respond_to_tile·first_guess를 OpenAI 호출로 교체 (docs/MODEL_SETUP.md 참고)
  2. 검색: retriever.py가 현재 단계의 축에 맞는 paper_rules.md 기준을 찾아 GPT에 넘김
  3. 레코드 생성, 디자인 토큰(tokens.css), 배포
- 팀 확정 필요: config에서 "초안: 팀 확정 필요"가 붙은 값(확신 기준·상승 폭·최대 횟수·요리 목표 점수·성공 거리), 요리 이름 화면 표시 여부, 표정 이미지, 레코드에 새길 타일 범위

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
