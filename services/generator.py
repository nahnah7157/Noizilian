"""외계인 캐릭터 답변을 생성하는 모듈 (Lucassen 등 2011 논문 규칙 및 페르소나 반영)"""

from .retriever import KnowledgeHit

AXES = ("wc", "mf", "hs", "hl")

# 표정별 상황 설명 (괄호 안 지문). 표정 키는 config.expressions와 같다.
NARRATION = {
    "confused": "외계인이 고개를 갸웃하며 타일을 다시 내밉니다.",
    "curious": "외계인이 당신의 타일을 따라 하며 조금씩 맞춰 봅니다.",
    "sure": "외계인이 확신에 찬 눈빛으로 고개를 끄덕입니다.",
    "happy": "외계인이 접시를 들고 기뻐합니다.",
    "sad": "외계인이 접시를 내려다보며 시무룩해집니다.",
}


class DemoGenerator:
    def generate(
        self,
        question: str,
        username: str,
        character: dict,
        knowledge: list[KnowledgeHit],
        signal: dict | None = None,
    ) -> str:
        """외계인 페르소나와 감각 신호(signal), 논문 규칙(paper_rules.md)을 반영한 답변 생성."""
        turn_id = character.get("current_turn_id", "identity")

        # 신호가 있는 경우 감각 점수와 논문 기준(R1~R15)을 해석에 반영
        signal_text = ""
        if signal is not None:
            scores = signal.get("scores", {})
            desc = signal.get("description", "")
            # 점수 해석 (R1: wc, mf, hs, hl / R3: 단단함은 질감, R4: 따뜻함은 색 등)
            wc = scores.get("wc", 0)  # 따뜻함(-) / 차가움(+)
            mf = scores.get("mf", 0)  # 남성적(-) / 여성적(+)
            hs = scores.get("hs", 0)  # 단단함(-) / 부드러움(+)
            hl = scores.get("hl", 0)  # 무거움(-) / 가벼움(+)

            # 외계인의 반응형 깨진 한국어 및 잡음 구성
            reaction = []
            if wc < -0.3:
                reaction.append("뜨거… 앗.")
            elif wc > 0.3:
                reaction.append("차갑… 시원…")

            if hs < -0.3:
                reaction.append("딱딱… 단단… [R3]")
            elif hs > 0.3:
                reaction.append("부들… 부드러… [R3]")

            signal_text = f" …지직. {username}의 신호 [{desc}] 수신. " + " ".join(reaction)
        else:
            signal_text = " …지직. 신호 대기 중…"

        # 턴별 외계인 반응 멘트 구성
        if signal is not None:
            return (
                f"{username}님의 신호를 받았어요: {signal['description']}. "
                f"…지직. " + " ".join(reaction) + "\n"
                "(외계인이 신호를 더듬거리며 따라 하며 경계를 조금 풉니다.)"
            )

        return (
            f"…지직. {username}… ‘{question}’…?\n"
            "(외계인이 낯선 신호를 호기심 어린 눈으로 바라봅니다. 타일을 움직여 첫 번째 신호를 보내보세요.)"
        )

    # ── 요리 단계 응답 ──────────────────────────────────────────
    # 지금은 GPT 연결 전 임시 규칙이다. 나중에 respond_to_tile()과 first_guess()의 내용을
    # OpenAI 호출로 바꾸면 된다. 반환 형식(dict)은 그대로 유지한다:
    #   scores     외계인의 다음 추측 타일 점수 {wc, mf, hs, hl} (-1~+1). 화면이 이 점수로 타일을 그린다
    #   word       깨진 한국어 1~2단어
    #   expression 표정 키 (confused / curious / sure / happy / sad)
    #   reading    외계인이 사용자 타일을 어떻게 읽었는지 (개발 확인용, 화면에 안 보임)
    #   reply      채팅창에 보일 문장 (word + 지문)

    def first_guess(self, stage: dict, dish: dict, character: dict,
                    previous: dict | None = None, reason: str | None = None) -> dict:
        """단계가 시작될 때 외계인의 첫 추측. 임시 규칙: 레코드를 거꾸로 기억해 목표의 반대쪽 절반에서 시작한다."""
        target = dish.get("targets", {}).get(stage["id"], {})
        scores = {a: 0.0 for a in AXES}
        for axis, value in target.items():
            scores[axis] = round(-0.5 * value, 3)
        word = stage.get("alien_line", "…?")
        if previous is None:
            expression, note = "confused", f"외계인이 '{stage['name']}' 타일을 내밉니다."
        elif reason == "confident":
            expression, note = "sure", f"'{previous['name']}' 확정! 외계인이 '{stage['name']}' 타일을 내밉니다."
        else:
            expression, note = "confused", f"외계인이 확신은 없지만 '{stage['name']}' 단계로 넘어갑니다."
        return {
            "scores": scores,
            "word": word,
            "expression": expression,
            "reading": "단계 시작: 첫 추측",
            "reply": f"…지직. {word}\n({note})",
        }

    def respond_to_tile(self, stage: dict, dish: dict, character: dict, signal: dict,
                        alien_scores: dict, update: dict, knowledge: list[KnowledgeHit],
                        username: str = "사용자", message: str = "") -> dict:
        """사용자 타일을 읽고 다음 추측을 정한다. 임시 규칙: 그 단계의 축에서 사용자 쪽으로 절반 다가간다."""
        user = signal["scores"]
        scores = dict(alien_scores)
        for axis in stage["axes"]:
            scores[axis] = round(alien_scores[axis] + 0.5 * (user[axis] - alien_scores[axis]), 3)
        agreed = update["step"] > 0
        expression = "curious" if update["confidence"] >= 0.4 else "confused"
        word = "맞음…?" if agreed else "아님…? 이거…?"
        return {
            "scores": scores,
            "word": word,
            "expression": expression,
            "reading": f"{signal.get('description', '')} / 확신 {update['confidence']}",
            "reply": f"…지직. {word}\n({NARRATION[expression]})",
        }

    def finish(self, result: dict, dish: dict, character: dict) -> dict:
        """네 단계가 끝나 요리가 완성됐을 때의 반응."""
        expression = "happy" if result["success"] else "sad"
        line = result.get("line") or ("맛…!" if result["success"] else "이상…?")
        done = "완성했습니다!" if result["success"] else "만들었지만 뭔가 이상합니다."
        return {
            "scores": None,
            "word": line,
            "expression": expression,
            "reading": f"요리 판정 거리 {result['distance']}",
            "reply": f"{line}\n(외계인이 {dish['name']}을(를) {done})",
        }

