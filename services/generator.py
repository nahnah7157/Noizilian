"""캐릭터 답변을 만드는 경계. 기본 구현에는 모델 호출이 없습니다."""

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
        """캐릭터 설정과 검색 결과를 받아 답변 문자열을 반환합니다.

        signal이 있으면 signal["scores"](-1~+1 감각 점수)와 signal["description"]을 프롬프트에 넣어
        외계인이 신호를 읽게 하세요. 지금은 받은 신호를 확인하는 데모 문장만 만듭니다.
        """
        if signal is not None:
            return f"{username}님의 신호를 받았어요: {signal['description']}. (데모 답변)"
        return (
            f"{username}님, ‘{question}’이라고 하셨군요. "
            "지금은 예시 답변만 제공하고 있어요."
        )
