# 프로젝트: Noizilian

말 대신 색·질감·노이즈로 외계인과 세 번 신호를 주고받고, 그 대화를 기호가 새겨진 레코드 한 장으로 남기는 캐릭터 챗봇입니다.

## 목표
- 기획서: docs/prd.md. 핵심 사용자와 시나리오는 여기 기준 (작성 예정)
- 대화는 3턴: 정체성 → 감정 → 우호적 접촉. 최종 결과물은 대화가 새겨진 레코드 이미지
- 감각 규칙: Lucassen, Gevers, Gijsenij (2011) "Texture Affects Color Emotion" Table III 색 질감 공식

## 스택
- Frontend: HTML/CSS/JS (templates/, public/assets/). 빌드 도구 없음
- Backend: Flask (app.py, services/)
- 모델: OpenAI (설정은 docs/MODEL_SETUP.md, 키는 로컬 .env에만)
- Python 3.12 (Conda 환경). 실행 방법과 팀 환경은 ENVIRONMENT.txt

## 코드 구조에서 지킬 것
- 감각 공식은 두 곳에 있음: public/assets/js/chatbot.js(브라우저)와 services/chatbot_service.py(서버). 한쪽을 고치면 다른 쪽도 같이 고치고 tests/test_smoke.py를 실행
- 서버는 브라우저가 보낸 점수를 믿지 않고 색·질감 값으로 다시 계산함
- 화면 ↔ 서버 계약은 POST /api/chat의 {message, username, signal} → {reply, image, sources}. 바꾸면 app.py, chatbot.js, 테스트를 같이 고침

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
