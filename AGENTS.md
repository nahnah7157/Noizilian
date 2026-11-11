# 프로젝트: 왹쿡 (Oek-Cook, 이전 이름 Noizilien)

골든 레코드에서 지구 요리를 보고 따라 만들다 실패한 외계인을, 말 대신 색·질감 타일을 주고받으며 도와 요리를 완성하는 캐릭터 챗봇입니다.

## 컨셉 (기준: config/chatbot_config.json)
- 요리 4단계: 재료 준비 → 손질 → 조리 → 플레이팅. 한 단계 = 한 턴
- 한 턴 안에서 타일을 여러 번 주고받는다. 외계인(AI, 실패 시 규칙)이 확신하면 다음 단계로. 단계마다 최대 10번(config.game.max_attempts), 10번째는 판단과 무관하게 넘어가고 결과는 쌓인 신호로 판정(자동 성공 아님)
- 외계인은 매번 타일 + 표정으로 응답한다
- 네 단계에서 확정된 타일이 요리 목표와 가까우면 성공, 멀면 실패 이미지 (햄버거·오므라이스·피자·라멘)
- 외계인 표정 이미지: alien_default·doubt·convinced·surprised·thinking·joy (config.expressions). 게임 진행 중 표정은 chatbot_service.turn_expression이 확신 변화로 고름(아래 "확신 표정"). 단계가 끝나면 판정과 상관없이(잘못 알아들음·10번째·마지막 단계 포함) convinced를 0.5초 보여 준 뒤 joy로 바뀌고 다음 응답까지 유지, 마지막 단계는 joy로 바뀐 뒤 결과 화면(chatbot.js updateGameState, 11/11). 진행 중 턴은 확신 표정 그대로. convinced·joy는 chat.html에서 preload. 배경: images/background/bg_* (단계별, style.css body[data-stage])
- 감각 규칙: Lucassen, Gevers, Gijsenij (2011) "Texture Affects Color Emotion" Table III. 근거는 data/knowledge/paper_rules.md의 R1~R15
- 색 언어 [앱 설정, 논문 근거 아님]: 색상 7구간(빨주노초파남보)은 종류·방법, 밝기·무늬는 정도. 뜻은 cooking_rules.md '색 언어', 숫자는 config.game.hue_zones·rules
- 쌓이는 이해: 외계인은 타일 하나를 고르지 않고 받은 타일이 쌓여 이해가 만들어진다(chatbot_service.stage_signal). 단계 결과는 쌓인 신호를 규칙으로 판정

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
| 자료 검색 (cooking_rules.md를 "## 메뉴 · 단계" 제목으로, record_lines.md를 타일 태그로) | services/retriever.py |
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
  - alien = {scores, word, expression, reading}, state = {dish, menu, stage_index, exchange_count, confidence, alien_scores, finals, verdicts, stage_metrics, last_expression, done}
  - 요리 게임 필드(추가만, 기존 필드 유지): menu, menu_image, stage_number(1~4), stage_name(select/prep/cook/plate), verdict(success/under/over/unstable), confidence, retry, attempts_left, alien_message, plating{hue, abnormal, hue_shift}, metrics(개발 확인용). stage_number·stage_name·verdict는 "방금 판정한 단계", stage 객체는 "지금 진행할 단계". result에 menu·verdicts·plating 추가
  - 단계 id(ingredient/prep/cook/plating)는 화면 배경·기록칸·레코드가 쓰므로 바꾸지 않는다. 화면용 이름은 config.game.stage_names
- generator.py의 first_guess / respond_to_tile / finish는 반환 형식(dict: scores, word, expression, reading, reply)을 유지한다

## 현재 진행 상황 (2026-11-07)
- 완료: 외계인 판단 AI 연결 (브랜치 feat/ai-decide, push 안 함). 실제 10판 측정까지 끝남
  - 1단계 규칙: judge_stage 연속 적합도(soft_fit, 코사인), reason(method/size/power/density/color), 손질=색상·크기·밀도, 조리=색상·무거움(power, hl)·밀도(wc 뺌), 플레이팅=요리별 center(판정 ±40, 결과 그림 색은 ±60 안이면 그대로)+밀도(max_roughness 60, 넘으면 unstable). seed·bluff·finalize 제거, seed는 그림용으로 세션마다 새로
  - 규칙 대체 확신 = 쌓인 적합도 × 일관성(이전 확신과 섞음). 일관성은 쌓인 신호가 최근 3장 동안 덜 흔들린 정도이고, 쌓인 적합도가 오르는 중이면 감점 없음(틀린 타일을 고쳐 보내면 손해가 없게), 멈춤 기준 confidence.thresholds는 시도마다 낮아져 규칙 경로는 5번 안에 끝남. max_attempts 네 단계 10, MAX_RECORD_ENTRIES 100
  - 성공 기준 후보 config.game.success(A·B·C), 지금 C(평균 적합도 0.8 + 플레이팅 정상)
  - 2단계 재료 선정: 타일 하나 = 재료 하나(read_ingredient: 색상 구간 + 거침칸 + 밝기). 메뉴 후보 = 재료 목록 일치 수 + 기존 온도·노이즈 매핑(aux 0.5). 규칙 대체 확신 = 1·2위 차이 × 1위에 맞은 타일 비율. 외계인은 대표 재료의 색으로 응답. menu는 확정 때만 채움(chatbot.js가 1단계 칸을 칠함)
  - 파(국물·물) 재료는 네 메뉴 모두에 있고 남(면)은 라멘 고유. 무작위로 눌러도 메뉴가 쏠리지 않게 남 구간을 좁혔다(225~265)
  - 3단계 AI 판단: generator.decide_turn이 타일마다 한 번 {confidence, advance, action}을 정함(8초, 재시도 없음, max_output_tokens 200). 실패·키 없음·config.game.llm_decide 꺼짐이면 규칙 대체. 응답 decision_source. 10번째는 final=true로 묻고 답과 무관하게 넘어감. 단계 결과는 항상 쌓인 신호를 규칙으로 판정
  - 확신 표정(11/11): AI는 표정을 고르지 않고, 서버가 실제로 쓴 확신(AI 또는 규칙)으로 정함(turn_expression, config.game.turn_expressions). 확신 오름 → convinced, 내림 → thinking, 쌓인 신호 변화(change) 큼 → surprised, 그대로 → doubt 중 가장 센 것. 직전 표정(state.last_expression, 단계가 바뀌면 null)은 빼서 연달아 안 나옴. 동점이면 doubt·thinking·surprised·convinced 순. 무작위 400판 측정: doubt 27·thinking 26·surprised 25·convinced 22%, 연속 0번(단, 재료 단계는 convinced 47%, 나머지 단계는 convinced 13~16%). verdict_expressions는 레코드 태그 대체용으로만 남음
  - 자신만만한 오답 제한: AI가 쌓인 적합도 0.3 미만에서 넘어가면 state.overconfident_advances에 세고 한 판 2번까지. 다 쓰면 서버가 advance=false, decision_source=openai_capped (config.game.overconfident). 재료 단계와 10번째는 안 셈
  - 레코드: 태그는 쌓인 신호 기준, 표정·그림은 게임 때 표정(history의 expression, 없으면 규칙). 오해 = 단계가 끝날 때 쌓인 판정이 success가 아님, 어긋난 단계가 없으면 중간에 어긋났던 첫 순간(pick_misreads). 타일 48개 넘으면 최근 48개만 GPT, 앞쪽은 예시 대사
  - 테스트는 tests/test_smoke.py 맨 앞에서 OPENAI_API_KEY를 비운다(실제 호출 방지). AI 경로는 mock
  - 4단계 호출 제한: app.py llm_allowed(메모리, lock). 환경 변수 LLM_PER_IP_PER_10MIN·RECORD_PER_IP_PER_10MIN·LLM_DAILY_LIMIT. 넘으면 use_llm=False로 규칙 대체(rule_limited). 판 로그는 GAME_LOG=1
  - 레코드 대기: 마지막 응답(state.done)을 받는 즉시 chatbot.js requestRecord가 요청한다. GPT 입력은 타일마다 예시 3개 번호만 넣고 글은 examples 목록에 한 번만
  - 레코드 GPT 응답: items(모든 타일) + pairs(오해 대사와 바로잡는 대사를 한 묶음, 개수 고정). 짝 타일은 pairs로 덮어쓴다. 외국어·물음표 위반·빈칸은 그 줄만 예시로, 짝은 둘 다 예시 짝으로 교체(_clean_lines). 절반 넘게 교체되면 source=openai_failed:too_many_replaced
  - 키 없는 대사: 태그 reason이 method면 record_lines.md의 method 섹션(방법이 틀렸을 때)을 쓴다
  - 재료 대표 색은 외계인 타일로 다시 그려도 같은 구간이 되게 골랐다. 색을 바꾸면 화면에서 구간이 유지되는지 다시 볼 것
- 완료: 학종이 작성기, 4단계 요리 API 및 로직. 테스트 128개
- 완료: docs/design/03_stage1_ingredients.png 와이어프레임으로 채팅 화면 전면 재배치 (chat.html, style.css, chatbot.js)
  - 배경 가득 + 좌상단 제목(#title) + 가운데 외계인 이미지 하나만. 입력창·단계 안내 글·확신 막대·알림 전부 제거(게임 진행 중에는 한국어 설명 없음. 인트로·결과·결론 화면과 다음에 만들 미션은 짧은 문구 허용). 보내기는 message="타일" 고정(app.py 안 건드림)
  - 오른쪽: HSV 색 선택기(가로 채도·세로 명도 + 무지개 hue 막대, 클릭·드래그). 고른 HSV→RGB→CIELAB(L·C·h)로 변환해 signal.color로 보냄(chatbot.js 1번에 hsvToRgb·rgbToLch 추가). 크기·밀도 막대는 아이콘만
  - 왼쪽: 기록 2줄(윗줄 외계인+머리 아이콘·4단계 / 아랫줄 나+흰 원·4단계), 현재 단계 칸 하이라이트·교환마다 갱신(단계 끝나면 마지막 타일 고정). 큰 미리보기. 되돌리기(↺ 파랑)·보내기(✓ 초록) 아이콘 버튼. "패턴 바꾸기" 제거
- 완료: 결과 화면 골든 레코드 교체 (chat.html, style.css, chatbot.js 7번, image_selector.py, app.py)
  - golden_record_cut.png를 원본 기호를 지운 깨끗한 원판으로 교체
  - (화면 구성은 아래 "결과 화면 세 장 흐름"이 최신) 주고받은 타일을 나선 홈에 순서대로 새김(타일 무늬). 홈에 마우스를 올리면 ① 타일을 말로 옮긴 대사 ② 외계인 대사면 그림. (한때 넣었던 무작위 기호·3음 소리는 11/4에 뺌)
  - POST /api/record: OpenAI가 paper_rules.md 기준으로 타일마다 재료·손질·조리·플레이팅 대사를 만들고(generator.record_lines), 외계인 대사는 config.record.line_images 설명과 OpenAI 임베딩(text-embedding-3-small)으로 비교해 외계인 3장 중 그림을 고름(image_selector.pick_line_images). 키 없으면 data/knowledge/record_lines.md에서 고름
  - 요리 결과(success)를 /api/record에 함께 보내, 실패면 엉뚱한 요리 방법 대화를 여러 번, 성공이어도 한 번 넣음 (아래 "레코드 대사 태그" 참고)
  - 대화 순서: 12시에서 시작해 시계방향, 한 바퀴마다 안쪽 홈으로 이어짐
  - 논문 근거 문장과 결과 화면 외계인 대사(result-line)는 표시 안 함
- 완료: 외계인 대사 제거. config의 greeting·stages[].alien_line·result.success_line/fail_line 삭제, persona.speaking_style을 "말하지 않음"으로. generator.py의 "…지직" 대사 삭제 → alien.word는 항상 ""(형식 유지), reply는 괄호 지문만(화면에 안 보임). judge_dish 결과의 line 삭제
- 완료: 비주얼 에셋 적용 (config, generator.py, image_selector.py, style.css, chatbot.js, chat.html, index.html)
  - 표정: 시작 default / 교환 중엔 위 "확신 표정" / 단계가 끝나면(통과 이유와 무관) convinced → joy / 결과 화면 외계인은 요리 성공 alien_success, 실패 alien_fail. 단계별 포즈(alien_cute_a/b/c) 제거
  - 배경: 시작 bg_default, 단계별 bg_selection·bg_preparation·bg_cooking·bg_plating, 결과 화면 bg_result(흰 카드 없앰)
  - 결과 화면: 게임 화면처럼 1920×1080 스테이지(.result-content.stage)라 배경·음식·레코드가 같은 좌표를 씀. 테이블 윗면 y 590~910. 음식은 x 600·접시 끝 y 840·보이는 높이 380(음식별 투명 여백은 --fill·--foot로 보정, 음식 이미지를 바꾸면 다시 잴 것). 세로 화면은 배경을 115%로 키워 테이블을 내림. 스크롤 없음, 다시 하기 버튼 오른쪽 아래. 레코드 아래 안내·오류 문구 삭제(대사 실패는 브라우저 콘솔에만)
  - 레코드 대사 그림: 문장부호(?!·?·!)로 후보 표정을 좁힌 뒤, record.line_images의 표정별 예시 대사와 임베딩 유사도(가장 비슷한 예시)로 고름. 키 없으면 문장부호로만. 이미 쓴 표정·바로 앞과 같은 표정은 감점해 고루 섞음(image_selector.pick_diverse). 놀람은 ! 있을 때만, "모르"가 있으면 고민·의심. 시험 대사 18개 중 17개 맞음(전엔 6개). 
  - 이름 정하기 화면(detail.html): 배경 bg_road(11/11, 파일이 없으면 아래 겹의 bg_default가 보임), 가운데 플레이어 그림, 남성/여성 버튼으로 player_male/female 전환(CSS :has, JS 없음), 가운데 아래 이름 칸, 오른쪽 아래 시작하기. 소개 글·태그·닫기 버튼 제거. 고른 성별은 player=male|female로 /chat에 넘어가(app.py가 검증, chat.html data-player) 채팅 화면 기록 아랫줄 "나" 아이콘(흰 원 자리)이 player_male/female로 바뀜 11/11: 밤 골목 bg_road(1672×941, 인도 = 그림 높이 81~88%)에 발을 맞춤 — 가로는 85%(bottom = 50vh − 0.35 × max(100vh, 100vw×941/1672), 그림 아래 투명 여백 4.5%만큼 내림), 가로는 성별 | 이름을 한 줄로 낮게. 세로는 입력칸이 인도와 겹쳐 발을 82%에, 시작하기는 이름 칸 오른쪽 같은 줄
  - 채팅 화면 타일 기록(#tile-record)을 왼쪽 패널에서 꺼내 왼쪽 위 제목 오른쪽에 따로 띄움(칸 20px). 오른쪽 색 선택과 왼쪽 미리보기·보내기(✓)를 패널 하나(.signal-dock)로 합침
  - 반응형 게임 화면 (chat.html, style.css, chatbot.js 8번): 전환 기준은 orientation 하나(CSS @media·JS matchMedia 같음)
    - 가로: main.stage(1920×1080)를 scale=min(창너비/1920, 창높이/1080)로 가운데 확대·축소, 남는 곳은 --letterbox 여백. 배경은 body의 --bg를 스테이지가 그림
    - 가로 배치(1920×1080 기준): 기록칸 왼쪽 위, 패널 오른쪽 위(right 40·top 40·폭 430, 아래 끝 y 585라 조리 배경의 프라이팬(y 625~)·냄비를 안 가림. 위에서부터 색 네모·색상 막대 → 크기·밀도 막대 → 미리보기·↺·✓), 외계인 가운데 바닥(.signal-center 높이 700·bottom 10)
    - 외계인 발 맞춤: 표정 이미지마다 아래 투명 여백이 달라 style.css의 --foot 값으로 내림. 표정 이미지를 바꾸면 이 값도 다시 잴 것
    - 말풍선: .signal-center가 외계인 크기 상자라 그 상자 기준으로 머리 옆을 따라감. 가로는 머리 오른쪽, 세로는 외계인이 화면 폭을 다 써서 머리 왼쪽 위
    - 세로: 위에서부터 기록칸 → 외계인(패널 바로 위, 높이 최대 124vw) → 패널(내용 높이, 390×844에서 약 26%, 스크롤 없음). 패널은 [색 네모 | 색상·크기·밀도 막대] + [미리보기·↺·✓]. 터치 요소 --touch(44px) 이상
    - 기록칸은 윗줄 나, 아랫줄 외계인
    - 캔버스 실제 픽셀 = 보이는 크기 × 배율 × devicePixelRatio (색 네모 최대 1024, 미리보기 256, 레코드 1600). 레코드는 기준 좌표 600 고정(RECORD_SIZE)
    - 결과 화면도 같은 --stage-scale을 씀. record-tip 위치는 showTip이 화면 좌표를 배율로 나눠 계산하고 스테이지 안으로 제한
    - 기록 박스는 칸 90px·아이콘 90px, 제목 글자 없애고 그 자리=왼쪽 위
  - 레코드 대사 지시문(generator._lines_with_openai)에 외계인 감정 6가지와 흐름을 넣어, 외계인 대사가 질문만 되지 않게 함
- 완료 (팀원 feat/turn-flow에서 가져옴): 되돌리기(↺) = 보낸 타일 취소, 말풍선·타일 날아가기 연출 (chatbot.js, style.css, chat.html)
  - ↺: 보내기 직전 스냅샷(state·history 길이·단계·보낸 타일 값)을 undoStack에 쌓고, 누르면 마지막 스냅샷으로 복원(선택기는 취소한 타일 값으로). 단계가 바뀌면 비움. 되돌릴 게 없거나 응답 대기 중이거나 done이면 비활성. app.py 안 고침(이전 state 재전송)
  - 기록칸은 단계가 끝날 때만 채움(stageFinished). 진행 중엔 외계인 머리 위 말풍선(#alien-think)에 외계인이 방금 답한 타일(이번 단계에 아직 안 보냈으면 "…", 11/9 변경). 꼬리 달린 말풍선, 깜박임은 11/9에 뺌. 단계 끝나면 두 타일이 기록칸으로 날아감(flyTile)
  - 가져오지 않은 것: 반응형 원복(이쪽 반응형 유지), 레코드 아래 안내 문구, 레코드 대사 단계별 병렬 호출(그림 겹침 감점이 대화 전체에 걸리도록 한 번에 요청. 서버의 wrong 필드는 남아 있음·하위호환)
- 완료: 단계 힌트 (chatbot.js, style.css): 게임 시작과 단계가 바뀔 때(타일 날아가기 뒤) 약 1.8초 화면을 어둡게 하고 배경 속 그 단계 물건만 밝힘. 좌표는 HINT_AREAS(1920×1080 기준), 튜토리얼에서도 쓸 수 있게 highlightAreas(영역, 시간)로 분리. 막은 스테이지 맨 아래(z-index 0)라 패널·외계인은 위에 보이고 클릭은 통과. 세로 화면은 배경 가운데만 보여서 보이는 면적 30% 미만 영역은 뺌(지금은 플레이팅만 강조). 모션 줄이기면 빛 없이 0.8초
- 완료: 인트로 대화 장면 (chat.html, style.css, chatbot.js 0번, config.intro, app.py intro_view). 11/11 피그마 시안으로 교체
  - 흐름(11/11): 시작 화면 시작하기 또는 최종 카드 처음으로 → 이름 화면 → 시작하기 → 티저 영상(detail.html 오버레이, 클릭 직후라 소리와 함께 재생. 비율 유지·남는 곳 검정, 오른쪽 위 skip은 확인창 없이 바로, 끝나거나 skip하면 /chat. 파일이 없거나 재생이 막히면 바로 /chat, 소리 끄기면 음소거) → 컷신(게임 화면에 들어올 때마다, 저장 안 함) → 1단계. 다시 요리하기는 영상·컷신 없이 1단계. 다 보거나 skip → 확인창 "네"면 startCooking → /api/start·단계 힌트. 다시 하기는 인트로 없이
  - 1920×1080 스테이지: 배경 intro_bg + rgba(14,19,21,.8) 덮개. 왼쪽 외계인(intro_alien 한 장, expression 무시, 158·120·482×724), 오른쪽 주인공(이름 화면에서 고른 성별의 기본 player_male·player_female, config.intro.player_portraits. 1050·-4·816×1088 안에 contain), 뒤에 보라 radial 타원. 말하는 쪽 그대로, 듣는 쪽 brightness(.6)
  - 대화창: y 678부터 높이 402 띠(rgba(10,13,15,.8)). 이름(학교안심 마법사, 나 #F6B981·외계인 #B6F4F0, 주인공은 config.intro.player_name "나")과 대사(프리젠테이션 Regular, 흰색, 한 글자씩)가 한 줄(left 225·띠 기준 top 166·간격 70·이름 칸 180·60px). 다음 버튼 #B6F4F0 알약(1604·914). 아무 데나 클릭·스페이스·엔터도 넘김
  - skip: 오른쪽 위(1675·47) 알약 → 확인창(655×406, 가운데) "네"(#CDD1D7) = 끝내고 게임 시작, "아니요"(#B6F4F0) = 계속(Esc도 닫음, 열리면 아니요에 포커스)
  - effect panel(5번째 줄): 게임 타일 패널(.signal-dock)을 복제해 678·181·532×436 자리에 --fit배로 줄여 아래에서 올라옴(0.5초), 끝까지 유지. 보여 주기만(inert). 복제본은 id가 같아서 인트로를 닫을 때 지움. shake·nod는 남아 있음(지금 대사엔 안 씀). tiles·highlight·image 효과는 삭제
  - 글꼴: style.css 맨 위 @font-face. 학교안심 마법사 = jsDelivr @kfonts/hakgyoansim-mabeopsa@0.1.0, 프리젠테이션 = jsDelivr gh/projectnoonnu/2404@1.0 (둘 다 OFL). 못 불러오면 IBM Plex Sans KR 등으로
  - 세로 화면(시안 없음): 초상화는 대화창 위에 작게(외계인 26%·주인공 74%), 대화창 아래 28dvh(이름 위·대사 아래), 패널은 위쪽 30dvh. 색·글꼴·버튼 모양은 가로와 같음. 모션 줄이기면 글자 한 번에·애니메이션 없음
- 완료: 결과 화면 세 장 흐름 (chat.html, style.css, chatbot.js 6·7번). .result-content의 data-screen으로 dish → record → end, 오른쪽 아래 "다음 ▶", 짧은 페이드(모션 줄이기면 즉시). 11/11 돔 공개·최종 카드로 교체
  - ① 돔 공개(data-reveal covered → lifting → revealed): 돔(images/result/dome_cover.png, 없으면 CSS 은색 돔)과 그 아래 요리는 x 860(가운데에서 살짝 왼쪽)·접시 끝 y 850·높이 300, 외계인은 x 1080 테이블 뒤(--show로 잘라 잘린 끝 y 583)이고 덮여 있는 동안은 기본(alien_default, --show .74). 돔은 숨 쉬는 글로우 + 2.6초마다 좌우로 짧게 흔들흔들(±4도, transform-origin 테두리), 올리면 scale 1.05(글자 없음, 모션 줄이기면 없음). 돔 위치·크기·배지 값은 직접 맞춘 것이라 바꾸지 말 것, 누르면 살짝 들렸다 하늘로 0.8초(DOME_FLY_MS = @keyframes dome-fly), 다 날아간 뒤 외계인 alien_success/fail + 배지 그림(images/result/text_success·text_fail, 요리 위에 통통 등장) + "다음 ▶". 모션 줄이기면 바로 공개. 세로는 요리 40%·외계인 62%. 외계인·돔 그림을 바꾸면 --show·크기를 다시 볼 것
  - ② 레코드 left 560·top 110·지름 800. 주변은 반투명 남보라 덮개(::before), 레코드 둘레는 천천히 밝아졌다 어두워지는 금빛(record-glow). 띠 band 0.07·pitch 0.08, 한 바퀴 타일 수 = max(12, 타일 수 ÷ 3)이라 최대 3바퀴. 대사는 ①에서 미리 요청하고, 오는 동안 "외계인이 신호를 보내는 중이에요". 툴팁에 감각 의미 추가(서버 lines[i].meaning 우선, 없으면 tileMeaning)
  - ③ 최종 카드(docs/design/final_record_ref.png 구성, renderCard): FINAL RECORD 탭 / 왼쪽 칸 = 레코드(같은 .record-disc를 옮김) + 고른 성별 player_male·female 상반신(칸 폭 160%로 키워 위쪽만) + 지구인(이름 화면 이름) + 요리 시도 횟수("N번째 요리" = localStorage oekcook.dishCount, 끝까지 한 판마다 +1, 막히면 1) / 오른쪽 칸 = 배지 그림 + 최종 요리(응답 dish.name) + 요리 그림(플레이팅 색 그대로) + 실패 원인(result.verdicts에서 success가 아닌 단계: 손질·조리·플레이팅 색 실패, 없으면 요리 과정 실패) 또는 성공 포인트 "완벽한 소통" / 아래 결론 문장(성공 "요리도 신호도 완벽하게 전해졌어요." 실패 "요리는 조금 이상했지만, 신호는 전해졌어요.") / 버튼 기록 저장(Mint, saveCard가 canvas에 카드를 직접 그려 PNG 내려받기, oekcook-record-N.png) · 다시 요리하기(Pink, startCooking) · 처음으로(Lavender, index). 세로는 위아래로 쌓고 왼쪽 칸 아랫줄에 지구인·시도 횟수(360×740까지 스크롤 없음)
  - 축 낱말 SENSE_WORDS는 브라우저가 config를 못 받아 chatbot.js에 있음. config.axis_labels를 바꾸면 같이 고칠 것
  - 콘솔 시험: 게임을 끝낸 뒤 oekcook.showResult({success, image, verdicts, plating:{hue_shift}})
- 완료: 시작 화면 히어로샷 (index.html, style.css, 11/11): 가로 images/title/hero_landscape, 세로 hero_portrait를 cover(로고가 그림에 있어 제목 글자·표정 외계인 삭제). 시작하기는 큰 Mint 알약 — 가로 그림은 음식이 가운데 아래 91~96%까지라 가로는 로고 아래 빈 싱크대 쪽(left 25%·bottom 7dvh), 세로는 음식 아래 가운데(bottom 6dvh). 그림을 바꾸면 버튼 자리를 다시 볼 것
- 완료: UI 규칙 통일 (style.css, 11/11): :root 변수 --navy #241D60(외곽선·글자) --mint #65E8DF(주요 버튼) --pink #F4AEDC(보조 버튼) --lavender #AAA0EE(패널·입력 컨트롤) --lime #C9F06E(진행·긍정: 성공 단계 칸, 지금 기록칸) --paper(카드·입력칸 안쪽), --ui-line(3px 남보라) --ui-radius(18px) --ui-drop(아래 5px 그림자, 흐림 없음). 버튼(.start-button·↺✓·?·성별)은 누르면 translate 3px + 그림자 2px. 패널(타일 패널·기록칸·진행 표시·이름 칸)은 Lavender, 카드(결론·툴팁·도움말·말풍선·레코드 상태)는 paper + 외곽선 + 그림자. 크기·밀도 막대는 Lavender 홈 + Mint 손잡이. 글꼴 한국기계연구원체(jsDelivr @noonnu/kimm-bold@0.1.0, MIT, Bold 하나). 인트로(대화창·skip·확인창)는 피그마 시안 그대로 둠
- 완료: 소리 (config.sounds, app.py bot_view, chatbot.js 6-0, index·detail 템플릿의 짧은 스크립트, 11/11)
  - 경로·볼륨은 config.sounds 한곳. 파일이 없거나 재생이 막히면 조용히 건너뜀(play() 실패 → "skip" 이벤트). src 빈 칸 = 아직 없음(alien_doubt·tile_pick 자리)
  - 효과음: start = 시작 화면 시작하기·최종 카드 다시 요리하기·처음으로(→ 이름 화면)(data-sound="start"), button = 그 밖의 모든 버튼(문서 click 위임, 성별 label 포함), tile_send = ✓(앞 1.2초 + 0.25초 페이드, 새로 울리면 이전 것 끊음), convinced = 외계인 그림이 alien_convinced로 바뀌는 순간(setAlienImage: 단계 끝 CONVINCED_IMAGE, 대화 중 showAlien. 이미 convinced면 안 울림). 단계 끝은 이 소리가 끝난 뒤(최대 CONVINCED_MAX_MS 1.6초, 꺼짐·막힘이면 바로) 다음 단계 힌트, 마지막 단계는 그 뒤에 결과 화면(afterSound), hint = 단계 힌트 빛 시작, stage = 빛이 사라지기 시작(HINT_FADE_AT 0.8 = area-hint-fade 80%), result = 결과 화면(돔이 덮인 화면)이 열리자마자 배경음악 정지와 함께 한 번(holdBgmForResult), success/fail = 돔이 사라지는 순간(revealDish done, 외계인·배지와 같은 순간)
  - 배경음악 bgm: 인트로가 뜰 때 startBgm(다시 요리하기는 startCooking에서, 이미 나오면 그대로). 자동재생이 막히면 첫 pointerdown·keydown 때 다시. 시작·이름 화면·티저 영상 동안엔 없음. 결과 화면이 열리면 멈췄다가 성공·실패 소리가 끝나면(실패·없음 포함) fade_in_ms(1초)로 다시
  - 링크·폼 이동(시작하기·처음으로·이름 화면 시작하기)은 소리가 들리게 0.25초 늦춰 이동
  - 소리 켜기/끄기: 모든 페이지 오른쪽 위 .sound-toggle(가로 36px·top 4 = 타일 패널 top 40·인트로 skip top 47 위, 세로 44px — 세로 인트로 skip은 top 64로 내림), localStorage oekcook.muted(막히면 켜짐). 끄면 배경음악·✓ 소리도 바로 멈춤
- asset_url(app.py)은 파일 수정 시각을 ?v=로 붙인다(11/11). 배포 뒤 브라우저가 옛 chatbot.js·style.css를 캐시로 써서 바뀐 화면이 안 보이던 문제 방지
- 배포: Render 무료 인스턴스(main에 merge하면 자동 재배포). 환경 변수에 OpenAI 키 없음 → 레코드 대사는 record_lines.md 예시, 그림은 문장부호 규칙으로만 고름. 호출 제한은 코드에 있음(LLM_*·RECORD_* 환경 변수). 시연·제출 전에 키를 넣을 것
- 완료: 요리 게임 규칙 (config.game, chatbot_service.py 2-2부, app.py parse_state, generator.act, retriever.py, data/knowledge/cooking_rules.md, chat.html·style.css·chatbot.js, tests) — 테스트 59개
  - 1단계 첫 타일 = 메뉴 결정(따뜻·차가움 × 노이즈 높음·낮음 → pizza/hamburger/ramen/omurice), 조리 판정에는 안 씀. 바로 손질로
  - 판정값 0~100: size=크기 막대(freq), roughness·noise=밀도 막대(oct), heat=논문 wc(R4, 메뉴 결정용), power=논문 hl(R6), hue·sat=HSV 색상·채도(서버가 LCh→sRGB로 되찾음). 단계별 쓰임은 위 "진행 중" 참고
  - 확신 기준 이상이면 다음 단계, 아니면 retry. max_attempts에서 쌓인 신호로 확정
  - main(#10 feat/layout, #11 feat/panel-size)과 합침(11/4): 가로 화면은 팀원 배치(외계인 바닥, 타일 패널 오른쪽 위, 결과 화면 스테이지)를 따르고 진행 표시는 위 가운데로. 세로 화면은 외계인을 배경 창에 고정하는 이쪽 배치를 유지(팀원의 세로 결과 화면 규칙은 그대로)
  - 왼쪽 아래 ? (그림 images/ui/hint_icon.png, 둥실 위아래로 뜸. 가로 120px·세로 60px 버튼, 세로 화면은 진행 표시 왼쪽): 마우스를 올리거나 누르면 "재료들을 보아하니 이런 걸 만들 수 있을 거 같아~" + 요리 4개 성공 그림 (app.py chat()이 config.dishes에서 넘김). 지금 만드는 요리는 끝날 때까지 화면에 안 나옴
  - 외계인 표정·행동 묘사 alien_message는 decide_turn이 정하고, 규칙 대체 때는 verdict_expressions·config.game.messages. 행동 묘사는 화면에 글로 안 보임
  - 화면: 오른쪽 위(세로 화면은 패널 위) 진행 표시(4단계 칸 판정 색. 재요청 ↻+남은 시도 점은 11/9에 뺌. 메뉴는 끝날 때까지 숨김 — 메뉴 그림은 11/4에 뺌), 외계인 반응 애니메이션, 플레이팅 hue_shift를 결과 그림에 입힘 (조리대 위 요리 그림은 11/4에 뺌)
- 완료: 레코드 대사 태그·검색 (data/knowledge/record_lines.md, retriever.search_lines, generator.record_lines, chatbot_service.py record_tags·pick_misreads, config.record.moods) — fallback_lines 삭제
  - 브라우저는 판정을 보내지 않아 서버가 색·질감으로 다시 판정함(record_tags). chatbot.js·app.py 안 고침. 외계인 타일은 앞 지구인 타일의 판정, 단계 첫 타일은 start
  - 오해: pick_misreads 하나가 정함(기준은 위 "진행 중" 참고). 바로 다음 지구인 타일이 바로잡음
  - 검색: 단계·말한 쪽이 같은 예시를 오해 > 판정 > 감정 순으로 정렬, 같은 순위는 임베딩 유사도(키 없으면 무작위). record_lines.md는 매번 읽어서 고치면 바로 반영
  - GPT: 타일마다 판정·적합도·오해·표정·의미·예시 5개를 넘기고, 판마다 기분 하나. 응답의 타일 번호·말한 쪽이 입력과 다르면 전부 예시 대사로(칸 밀림 방지), 판 안 같은 대사는 그 줄만 예시로 교체
  - 다양성: 예시 264줄, 기분 10가지. 지시문에서 물음표는 doubt·surprised만, 외계인 대사 모양을 바꿔 가며, 지구인은 한 문장으로 제한
  - 키 없을 때: 태그가 맞는 예시를 판 안 중복 없이 무작위로. 오해와 바로잡는 대사는 misread=짝이름으로 이어짐
- 다음 작업 순서
  1. 사람이 직접 해 보기: 색으로 방법을 맞추는 난이도, AI가 묻는 횟수(무작위 입력은 단계당 7번까지 감)
  2. 요리 재료 이미지 → 단계별 화면 연결, 레코드 예시(record_lines.md) 말투 다듬기, README·공개 URL 최종 확인
  3. 배포 전: Render에 키와 호출 제한 환경 변수 넣기, X-Forwarded-For로 IP가 제대로 잡히는지 확인
- 팀 확정 필요: config의 "초안: 팀 확정 필요" 값(확신 기준·상승 폭·최대 횟수·요리 목표 점수·성공 거리), 표정 고르는 기준(generator.py), 레코드 예시(record_lines.md), 결과 화면을 음식+레코드 한 화면으로 둘지(와이어프레임은 07 → 11 따로)

## 디자인 규칙
- 색·모양은 style.css 맨 위 :root 변수(--navy·--mint·--pink·--lavender·--lime·--paper·--ui-*)를 쓴다. 새 색상 하드코딩 금지 (인트로는 피그마 시안 값, 옛 채팅 화면 CSS는 안 쓰는 코드라 그대로)
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
