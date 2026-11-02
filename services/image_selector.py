"""답변과 맞는 이미지를 고르는 경계.

1차 구현: 라벨(단계·표정·결과)로 config에 적힌 이미지 경로를 고른다.
- 요리가 끝났으면 음식 성공/실패 이미지
- 표정 이미지가 config.expressions에 있으면 그 표정
- 없으면 지금 단계의 포즈 이미지 (재료 준비 a 기본 / 손질 b 칼 / 조리 c 프라이팬 / 플레이팅 a)
레코드 외계인 대사 그림: config.record.line_images의 그림 설명과 대사의 임베딩 유사도로 고른다.
"""

import logging
import math
import os

EMBEDDING_MODEL = "text-embedding-3-small"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


def match_images(texts: list[str], images: dict, embed) -> list[str]:
    """문장마다 설명이 가장 비슷한 그림 URL을 고른다. embed(문장 목록) → 벡터 목록."""
    paths = list(images)
    vectors = embed(texts + [images[p] for p in paths])
    image_vectors = vectors[len(texts):]
    return [_url(max(zip(paths, image_vectors), key=lambda pv: _cosine(vector, pv[1]))[0]) for vector in vectors[:len(texts)]]


def pick_line_images(texts: list[str], character: dict) -> tuple[list[str], str]:
    """외계인 대사마다 어울리는 그림 URL. 키가 없거나 실패하면 그림을 차례로 돌려 붙인다.
    반환: (URL 목록, "openai" | "no_key" | "openai_failed")
    """
    images = {k: v for k, v in ((character.get("record") or {}).get("line_images") or {}).items() if not k.startswith("_")}
    if not texts or not images:
        return [], "empty"
    source = "no_key"
    if os.getenv("OPENAI_API_KEY"):
        try:
            from openai import OpenAI

            client = OpenAI(timeout=20.0, max_retries=2)
            return match_images(texts, images, lambda batch: [
                d.embedding for d in client.embeddings.create(model=EMBEDDING_MODEL, input=batch).data]), "openai"
        except Exception:
            logging.getLogger(__name__).exception("대사 그림 임베딩 실패")
            source = "openai_failed"
    paths = list(images)
    return [_url(paths[i % len(paths)]) for i in range(len(texts))], source


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
