"""답변과 맞는 이미지를 고르는 경계.

1차 구현: 라벨(단계·표정·결과)로 config에 적힌 이미지 경로를 고른다.
- 요리가 끝났으면 음식 성공/실패 이미지
- 표정 이미지가 config.expressions에 있으면 그 표정
- 없으면 지금 단계의 포즈 이미지 (재료 준비 a 기본 / 손질 b 칼 / 조리 c 프라이팬 / 플레이팅 a)
2차 구현(예정): data/images/의 장면 설명과 답변 문장의 임베딩 유사도로 고른다.
"""


def _url(path: str | None) -> str | None:
    """config의 'assets/images/...' 경로를 브라우저 주소 '/assets/images/...'로 바꾼다."""
    return f"/{path.lstrip('/')}" if path else None


class DemoImageSelector:
    def select(
        self,
        reply: str,
        character: dict,
        stage: dict | None = None,
        expression: str | None = None,
        result: dict | None = None,
    ) -> str | None:
        """브라우저에서 열리는 이미지 URL을 반환한다. 고를 이미지가 없으면 None."""
        if result:
            return _url(result.get("image"))
        expressions = character.get("expressions") or {}
        chosen = expressions.get(expression or "")
        if isinstance(chosen, dict) and chosen.get("image"):
            return _url(chosen["image"])
        if stage:
            return _url(stage.get("pose_image"))
        return None
