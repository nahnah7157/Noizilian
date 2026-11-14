# 지식 자료

서버가 실제로 읽는 자료입니다. 고치면 다음 요청부터 바로 반영됩니다(서버 재시작 불필요). 개인정보, 저작권이 확인되지 않은 자료, API 키는 넣지 마세요.

| 파일 | 내용 | 읽는 곳 |
|---|---|---|
| `paper_rules.md` | 논문 근거 R1~R15 (Lucassen, Gevers, Gijsenij 2011 "Texture Affects Color Emotion" Table III) | 감각 공식의 근거. 공식은 `services/chatbot_service.py` 1부와 `public/assets/js/chatbot.js` 두 곳 |
| `cooking_rules.md` | 외계인의 색 언어와 메뉴·단계별 요리 규칙 [앱 설정, 논문 근거 아님] | `services/retriever.py`가 "## 메뉴 · 단계" 제목으로 찾아 외계인 판단(OpenAI)에 넘김 |
| `record_lines.md` | 레코드 대사 예시(단계·말한 쪽·판정·감정 태그) | `services/retriever.py`가 타일 태그로 거름. 키가 있으면 OpenAI 대사의 예시, 없으면 그대로 사용 |

숫자(판정 범위·확신 기준 등)는 이 폴더가 아니라 `config/chatbot_config.json`에 있습니다.
