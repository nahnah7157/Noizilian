"""검색·답변 생성·이미지 선택을 연결해 API 응답을 조립합니다."""

from .generator import DemoGenerator
from .image_selector import DemoImageSelector
from .retriever import DemoRetriever


class ChatbotService:
    def __init__(self, retriever=None, generator=None, image_selector=None):
        self.retriever = retriever or DemoRetriever()
        self.generator = generator or DemoGenerator()
        self.image_selector = image_selector or DemoImageSelector()

    def generate_response(
        self,
        user_message: str,
        username: str = "사용자",
        character: dict | None = None,
        signal: dict | None = None,
    ) -> dict:
        """`reply`, `image`, `sources`로 이루어진 응답을 반환합니다.

        signal은 sense_model.parse_signal()이 만든 학종이 신호(색·질감·감각 점수·설명)입니다.
        """
        knowledge = self.retriever.search(user_message)
        character = character or {}
        if signal is None:
            reply = self.generator.generate(user_message, username, character, knowledge)
        else:
            reply = self.generator.generate(user_message, username, character, knowledge, signal=signal)
        image = self.image_selector.select(reply, character)
        return {
            "reply": reply,
            "image": image,
            "sources": list(dict.fromkeys(hit.title for hit in knowledge)),
        }
