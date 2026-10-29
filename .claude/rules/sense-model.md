---
paths:
  - "services/**/*.py"
  - "public/assets/js/noizilian/**/*.js"
  - "data/knowledge/**"
  - "config/chatbot_config.json"
  - "tests/test_signal.py"
---

# 감각 모델과 외계인 응답 규칙

- 색·질감과 감정의 관계는 data/knowledge/paper_rules.md(Lucassen 외 2011)가 기준이다. 감각 점수, 외계인 응답, 노이즈 생성을 바꾸기 전에 이 파일을 먼저 읽는다
- 근거를 말할 때는 paper_rules.md의 번호(R1~R15)를 쓰고, [논문] / [공식 계산] / [앱 설정]을 구분한다. 논문에 없는 내용을 논문 근거처럼 쓰지 않는다
- 단단함–부드러움은 질감만으로 표현한다(R3). 따뜻함–차가움은 색으로 표현한다(R4)
- 외계인의 반응(다가가기, 따라 하기 등)은 논문에 없는 설계다. AI가 정하되, 만든 신호의 뜻은 Table III 공식으로 검증한다
- 공식은 두 곳에 있다: services/sense_model.py와 public/assets/js/noizilian/senseModel.js·library.js. 한쪽을 고치면 다른 쪽도 같이 고치고 python -m unittest discover -s tests -v 를 실행한다
