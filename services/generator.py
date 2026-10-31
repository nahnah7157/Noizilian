"""외계인 캐릭터 답변을 생성하는 모듈 (Lucassen 등 2011 논문 규칙 및 페르소나 반영)"""

from .retriever import KnowledgeHit


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

